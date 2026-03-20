Node:
  id: unique_id
  ip: address
  type: Entry | Relay | Exit
  role: Master | Slave
  location: country
  capacity:
    bandwidth: Mbps
    cpu_score: relative_score
  allowed_usage:
    streaming: true/false
    gaming: true/false
    browsing: true/false
  allow_relay: true/false