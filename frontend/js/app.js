const { createApp, ref, computed, onMounted } = Vue;

const API_BASE = '/api';

createApp({
    setup() {
        const currentTab = ref('dashboard');
        
        const health = ref({ ok: false });
        const nodes = ref([]);
        const routes = ref([]);
        const metrics = ref([]);
        
        const showNodeModal = ref(false);
        const form = ref({
            name: '', location: '', ip: '', port: 443, 
            role: 'slave', node_type: 'entry', 
            bandwidth_mbps: 1000, transport: 'quic'
        });

        const tabTitle = computed(() => {
            const map = {
                dashboard: 'System Overview',
                nodes: 'Server Management',
                routes: 'Routing Table',
                metrics: 'Performance Metrics'
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
            } catch (e) {
                console.error("API Error", e);
                health.value.ok = false;
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
            } catch(e) {
                alert("Failed to delete node.");
            }
        };

        const toggleNodeState = async (node) => {
            try {
                await axios.patch(`${API_BASE}/nodes/${node.id}`, { is_active: !node.is_active });
                fetchData();
            } catch(e) {
                alert("Failed to toggle state.");
            }
        };

        const generateRoutes = async () => {
            try {
                await axios.post(`${API_BASE}/routes/generate`, { max_routes: 10 });
                fetchData();
            } catch (e) {
                alert("Failed to generate routes: " + (e.response?.data?.detail || e.message));
            }
        };

        const getNodeName = (id) => {
            if(!id) return '';
            const n = nodes.value.find(x => x.id === id);
            return n ? n.name : id.split('-')[0];
        };

        onMounted(() => {
            fetchData();
            setInterval(fetchData, 10000); // Poll every 10s
        });

        return {
            currentTab, tabTitle,
            health, nodes, routes, metrics,
            showNodeModal, form,
            submitNode, deleteNode, toggleNodeState, generateRoutes, getNodeName
        };
    }
}).mount('#app');
