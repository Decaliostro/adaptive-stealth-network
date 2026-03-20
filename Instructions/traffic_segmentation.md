TrafficTypes:

  streaming:
    requirement: high bandwidth
    preferred_nodes: high capacity Exit

  gaming:
    requirement: low latency
    preferred_nodes: closest Entry + fastest route

  browsing:
    requirement: balanced
    preferred_nodes: any stable node

  api:
    requirement: stable + low overhead

    FUNCTION assign_route(traffic_type):

  SELECT route based on traffic_type requirements