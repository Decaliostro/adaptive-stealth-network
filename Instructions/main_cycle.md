LOOP every 5 seconds:

  FOR each route:
    measure(route)
    update_state(route)

  FOR each traffic_type:
    best_route = select_best(route_pool)

    IF current_route != best_route:
      switch_route(traffic_type, best_route)