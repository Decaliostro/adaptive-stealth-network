const { createApp, ref, computed, onMounted } = Vue;

const API_BASE = '/api';

createApp({
    setup() {
        const currentTab = ref('dashboard');
        
        const health = ref({ ok: false });
        const nodes = ref([]);
        const routes = ref([]);
        const metrics = ref([]);
        const users = ref([]);
        const settings = ref({});
        
        const showNodeModal = ref(false);
        const form = ref({
            name: '', location: '', ip: '', port: 443, 
            role: 'slave', node_type: 'entry', 
            bandwidth_mbps: 1000, transport: 'quic'
        });

        const showUserModal = ref(false);
        const userForm = ref({
            username: '', data_limit_gb: null, speed_limit_mbps: null, expire_at: null
        });

        const qrCodeData = ref(null);

        const tabTitle = computed(() => {
            const map = {
                dashboard: 'System Overview',
                nodes: 'Server Management',
                routes: 'Routing Table',
                metrics: 'Performance Metrics',
                users: 'User Subscriptions',
                settings: 'System Configuration'
            };
            return map[currentTab.value];
        });

        const fetchData = async () => {
            try {
                const res = await axios.get(`${API_BASE}/health`);
                health.value.ok = res.data.status === 'ok';
                
                const resNodes = await axios.get(`${API_BASE}/nodes`);
                nodes.value = resNodes.data;
                
                const resRoutes = await axios.get(`${API_BASE}/routes`);
                routes.value = resRoutes.data;
                
                const resMetrics = await axios.get(`${API_BASE}/metrics?limit=20`);
                metrics.value = resMetrics.data;

                const resUsers = await axios.get(`${API_BASE}/users`);
                users.value = resUsers.data;
            } catch (e) {
                console.error("API Error", e);
                health.value.ok = false;
            }
        };

        const fetchSettings = async () => {
            try {
                const res = await axios.get(`${API_BASE}/settings`);
                settings.value = res.data;
            } catch (e) { console.error(e); }
        };

        const saveSettings = async () => {
            try {
                await axios.patch(`${API_BASE}/settings`, settings.value);
                alert("Settings saved successfully.");
            } catch (e) {
                alert("Failed to save settings.");
            }
        };

        const submitNode = async () => {
            try {
                await axios.post(`${API_BASE}/nodes`, form.value);
                showNodeModal.value = false;
                form.value = {name: '', location: '', ip: '', port: 443, role: 'slave', node_type: 'entry', bandwidth_mbps: 1000, transport: 'quic'};
                fetchData();
            } catch(e) {
                alert("Failed to add node: " + (e.response?.data?.detail || e.message));
            }
        };

        const deleteNode = async (id) => {
            if(!confirm("Are you sure you want to remove this node?")) return;
            try {
                await axios.delete(`${API_BASE}/nodes/${id}`);
                fetchData();
            } catch(e) { alert("Failed to delete node."); }
        };

        const toggleNodeState = async (node) => {
            try {
                await axios.patch(`${API_BASE}/nodes/${node.id}`, { is_active: !node.is_active });
                fetchData();
            } catch(e) { alert("Failed to toggle state."); }
        };

        const submitUser = async () => {
            try {
                // filter nulls to avoid passing empty strings
                const payload = { ...userForm.value };
                if(!payload.data_limit_gb) delete payload.data_limit_gb;
                if(!payload.speed_limit_mbps) delete payload.speed_limit_mbps;
                if(!payload.expire_at) delete payload.expire_at;

                await axios.post(`${API_BASE}/users`, payload);
                showUserModal.value = false;
                userForm.value = {username: '', data_limit_gb: null, speed_limit_mbps: null, expire_at: null};
                fetchData();
            } catch (e) {
                alert("Failed to add user: " + (e.response?.data?.detail || e.message));
            }
        };

        const deleteUser = async (id) => {
            if(!confirm("Are you sure you want to remove this user?")) return;
            try {
                await axios.delete(`${API_BASE}/users/${id}`);
                fetchData();
            } catch(e) { alert("Failed to delete user."); }
        }

        const showQRCode = async (u) => {
            try {
                const res = await axios.get(`/api/sub/${u.client_uuid}`);
                qrCodeData.value = atob(res.data); // decode base64
                
                setTimeout(() => {
                    document.getElementById('qrcode').innerHTML = '';
                    new QRCode(document.getElementById('qrcode'), {
                        text: qrCodeData.value,
                        width: 180,
                        height: 180,
                        colorDark : "#000000",
                        colorLight : "#ffffff",
                        correctLevel : QRCode.CorrectLevel.L
                    });
                }, 100);
            } catch(e) {
                alert("Cannot generate QR code: " + (e.response?.data?.detail || e.message));
            }
        };

        const copyToClipboard = async (text) => {
            try {
                await navigator.clipboard.writeText(text);
                alert("Copied to clipboard!");
            } catch (err) {
                alert("Failed to copy text.");
            }
        }

        const generateRoutes = async () => {
            try {
                await axios.post(`${API_BASE}/routes/generate`, { max_routes: 10 });
                fetchData();
            } catch (e) { alert("Failed to generate routes: " + (e.response?.data?.detail || e.message)); }
        };

        const getNodeName = (id) => {
            if(!id) return '';
            const n = nodes.value.find(x => x.id === id);
            return n ? n.name : id.split('-')[0];
        };

        onMounted(() => {
            fetchData();
            fetchSettings();
            setInterval(fetchData, 10000); // Poll every 10s
        });

        return {
            currentTab, tabTitle,
            health, nodes, routes, metrics, users, settings,
            showNodeModal, form,
            showUserModal, userForm, qrCodeData,
            submitNode, deleteNode, toggleNodeState, generateRoutes, getNodeName,
            submitUser, deleteUser, showQRCode, copyToClipboard, saveSettings
        };
    }
}).mount('#app');
