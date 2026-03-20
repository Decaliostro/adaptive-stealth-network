FUNCTION generate_routes(nodes):

  routes = []

  IF only one node:
    routes.append(SingleNodeRoute)

  ELSE:
    FOR each Entry:
      FOR each Relay (optional):
        FOR each Exit:
          routes.append(E → R → X)

  LIMIT routes to best N combinations