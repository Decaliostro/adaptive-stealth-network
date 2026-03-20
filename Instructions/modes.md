Modes:

  SingleNode:
    description: Работа через один сервер
    route: Client → Server → Internet

  MultiNode:
    description: Цепочка серверов для анонимности
    route: Client → Entry → Relay → Exit → Internet

  Hybrid:
    description: Смешанный режим
    behavior:
      - простой трафик → SingleNode
      - чувствительный трафик → MultiNode