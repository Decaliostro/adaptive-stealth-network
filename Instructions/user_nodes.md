FUNCTION add_slave(node):

  VALIDATE node
  ADD to node pool
  ASSIGN role:
    IF high bandwidth → Exit
    IF stable → Entry
    ELSE → Relay