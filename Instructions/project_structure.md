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