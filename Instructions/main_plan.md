0. Основные цели реализации
Поднять ядро сети (Sing-box / VLESS / QUIC + TLS) на сервере.
Сделать backend, который хранит список нод и маршрутов, их состояние и метрики.
Сделать controller, который на клиенте управляет маршрутизацией, fallback и адаптацией под DPI.
Обеспечить масштабируемость, relay и master/slave, возможность добавления пользовательских серверов.
Реализовать traffic segmentation (streaming/gaming/browsing/API) и распределение нагрузки.
Сделать telemetry и recovery механизмы.

1. Структура проекта
adaptive-stealth-network/
├─ backend/
│   ├─ app.py                  # REST API для управления нодами
│   ├─ models.py               # ORM-модели (Node, Route, Metrics)
│   ├─ routes.py               # Endpoints для API
│   ├─ scheduler.py            # Периодический сбор метрик
│   ├─ db.sqlite (или Postgres) # База данных
├─ controller/
│   ├─ main.py                 # Основной цикл выбора маршрутов
│   ├─ metrics.py              # Измерение latency, packet loss, throughput
│   ├─ scoring.py              # Алгоритм оценки маршрутов
│   ├─ switcher.py             # Логика переключения маршрутов
│   ├─ traffic_assign.py       # Распределение трафика по типам
│   ├─ transport_adapt.py      # QUIC/TCP fallback
│   ├─ recovery.py             # Recovery блокированных маршрутов
├─ config/
│   ├─ nodes.yaml              # Список узлов с параметрами
│   ├─ traffic_rules.yaml      # Traffic segmentation правила
├─ utils/
│   ├─ logger.py               # Логирование
│   ├─ helpers.py              # Общие функции
├─ README.md

2. Backend (Master/Slave + Node Management)
Цель: хранить и обновлять информацию о всех нодах, маршрутах и их состоянии.
Модули:
models.py – Node, Route, Metrics
scheduler.py – сбор метрик с серверов (ping, throughput, uptime)
routes.py – REST API:
GET /nodes – список нод
POST /nodes – добавить новую ноду (slave)
GET /routes – доступные маршруты
PATCH /routes/:id – обновление состояния маршрута
Особенности:
Master хранит полную конфигурацию сети.
Slave может реплицировать часть информации (для децентрализации).
Можно разрешить пользователям использовать сервер как relay (allow_relay).
3. Controller (Client-side Logic)
Цель: адаптивно выбирать маршруты для каждого типа трафика, переключаться при блокировках, fallback на один сервер.
Модули:
metrics.py – измерение latency, packet loss, handshake success, throughput
scoring.py – оценка маршрутов по формуле
switcher.py – переключение маршрутов, cooldown, prevention of flapping
traffic_assign.py – сегментация трафика (streaming/gaming/browsing/API)
transport_adapt.py – QUIC ↔ TCP fallback
recovery.py – восстановление заблокированных маршрутов
main.py – основной цикл: сбор метрик → scoring → выбор маршрута → switch
Особенности:
Работает как отдельный процесс на клиенте.
Поддерживает fallback на один сервер.
Многопоточная поддержка для разных типов трафика (streaming/gaming/etc.).
4. Node / Route Lifecycle

flowchart LR
    Client -->|connect| Entry
    Entry --> Relay
    Relay --> Exit
    Exit --> Internet

    subgraph Metrics
      Entry --> metrics
      Relay --> metrics
      Exit --> metrics
    end

    subgraph Controller
      metrics --> scoring
      scoring --> switch_decision
      switch_decision --> apply_route
      apply_route --> Client
    end



5. Traffic Segmentation
Streaming: мощные Exit, high bandwidth
Gaming: минимальная latency, ближайшие Entry + Exit
Browsing: слабые серверы, баланс latency/throughput
API: стабильные серверы, low overhead
Controller назначает маршруты по типу трафика через traffic_assign.py.
6. Recovery & Anti-DPI
Recovery: повторная проверка заблокированных маршрутов каждые 60–120 сек
Anti-DPI:
jitter (10–50ms)
случайные reconnect intervals
избегание постоянных пакетных паттернов
7. Adding User Nodes (Master/Slave)
POST /nodes → добавить slave
node может быть Entry/Relay/Exit
node может разрешать использование как relay (allow_relay = true)
Traffic segmentation распределяет нагрузку по мощности сервера
8. Transport Adaptation
QUIC (UDP) основной
TCP fallback при блокировках
Авто-переключение Entry/Exit при длительных ошибках
9. Fallback Logic
Priority:
1. смена Exit
2. смена Relay
3. смена Entry
4. fallback на SingleNode
10. Основной цикл работы (Controller)
LOOP every 5 sec:
    measure metrics
    update route states
    score routes
    assign route per traffic type
    switch if needed
    detect failures (timeout, reset, UDP fail)
    fallback transport if needed
    recover blocked routes every 60–120 sec
11. Разработка через Claude Code
Шаги:
Создать backend API (Python / FastAPI) для управления нодами и маршрутами.
Реализовать controller модуль (Python / Go) по псевдологике из спецификации.
Настроить конфиги нод и traffic rules (nodes.yaml, traffic_rules.yaml).
Настроить Sing-box на серверах, подключение через API к backend.
Запустить тестовую сеть с одним сервером → добавить slave → протестировать multi-node.
Внедрить recovery и anti-DPI поведение.
Расширять сеть с новыми серверными нодами и распределением трафика.