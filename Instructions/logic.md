SYSTEM:

  INIT nodes
  GENERATE routes
  LOOP:
    measure routes
    score routes
    select best per traffic type
    switch if needed
    detect failures
    adapt transport
    recover routes