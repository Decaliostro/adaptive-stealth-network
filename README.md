# Adaptive Stealth Network

Адаптивная сетевая система маршрутизации трафика с anti-DPI, multi-node routing (Entry → Relay → Exit), Master/Slave архитектурой, traffic segmentation и интеграцией с Sing-box.

## 🏗️ Архитектура

```
Client ──→ Entry Node ──→ Relay Node ──→ Exit Node ──→ Internet
              │                │              │
              └────── Metrics Collection ─────┘
                           │
                    Controller (scoring,
                     switching, recovery)
                           │
                    Backend API (FastAPI)
                           │
                    SQLite / PostgreSQL
```

### Компоненты

| Компонент     | Описание |
|---------------|----------|
| **Backend**   | FastAPI REST API — управление нодами, маршрутами, метриками |
| **Controller**| Клиентский движок — адаптивный выбор маршрутов, fallback, anti-DPI |
| **Config**    | YAML конфигурации нод, трафика, настроек |
| **Sing-box**  | Прокси-ядро (VLESS + Reality + QUIC/TCP) |

## 🚀 Быстрый старт

### Установка одной строкой (One-Line Installer)
Самый быстрый способ развернуть контроллер на чистом сервере (настроит Docker, скачает репозиторий и запустит Web-панель):
```bash
bash <(curl -sL https://raw.githubusercontent.com/Decaliostro/adaptive-stealth-network/master/install.sh)
```

### Требования

- Python 3.10+
- [Sing-box](https://sing-box.sagernet.org/) (для работы controller)
- Docker (опционально)

### 1. Установка зависимостей

```bash
cd adaptive-stealth-network
python -m venv venv
source venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### 2. Запуск Backend

```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

Backend доступен на `http://localhost:8000`:
- **Swagger UI**: http://localhost:8000/docs
- **Health check**: http://localhost:8000/api/health

### 3. Добавление нод

Через API (curl):

```bash
# Добавить Entry ноду
curl -X POST http://localhost:8000/api/nodes \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Entry DE",
    "ip": "203.0.113.10",
    "port": 443,
    "node_type": "entry",
    "role": "master",
    "location": "DE",
    "bandwidth_mbps": 500,
    "cpu_score": 85
  }'

# Добавить Exit ноду
curl -X POST http://localhost:8000/api/nodes \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Exit US",
    "ip": "192.0.2.30",
    "port": 443,
    "node_type": "exit",
    "role": "slave",
    "location": "US",
    "bandwidth_mbps": 1000,
    "cpu_score": 90
  }'

# Добавить Relay ноду (разрешить использование как relay)
curl -X POST http://localhost:8000/api/nodes \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Relay NL",
    "ip": "198.51.100.20",
    "port": 443,
    "node_type": "relay",
    "role": "slave",
    "location": "NL",
    "allow_relay": true
  }'
```

### 4. Генерация маршрутов

```bash
curl -X POST http://localhost:8000/api/routes/generate \
  -H "Content-Type: application/json" \
  -d '{"max_routes": 10}'
```

### 5. Запуск Controller

```bash
python -m controller.main
```

Controller автоматически:
- Получает ноды и маршруты с backend
- Измеряет метрики каждые 5 сек
- Оценивает и ранжирует маршруты
- Переключает маршруты при деградации
- Восстанавливает заблокированные маршруты
- Применяет anti-DPI jitter

## 🐳 Docker

```bash
# Сборка и запуск
docker-compose up --build

# Только backend
docker build -t asn-backend .
docker run -p 8000:8000 asn-backend
```

## 📡 API Endpoints

| Method | Endpoint | Описание |
|--------|----------|----------|
| `GET` | `/api/nodes` | Список нод |
| `POST` | `/api/nodes` | Добавить ноду |
| `GET` | `/api/nodes/{id}` | Детали ноды |
| `PATCH` | `/api/nodes/{id}` | Обновить ноду |
| `DELETE` | `/api/nodes/{id}` | Удалить ноду |
| `GET` | `/api/routes` | Список маршрутов |
| `POST` | `/api/routes/generate` | Генерация маршрутов |
| `PATCH` | `/api/routes/{id}` | Обновить маршрут |
| `GET` | `/api/metrics` | Метрики |
| `POST` | `/api/metrics` | Записать метрики |
| `GET` | `/api/health` | Health check |

## 🔄 Traffic Segmentation

| Тип трафика | Приоритет | Требования |
|-------------|-----------|------------|
| **Gaming** | Latency | < 80ms, loss < 2% |
| **Streaming** | Throughput | > 10 Mbps, loss < 5% |
| **API** | Stability | < 200ms, errors minimal |
| **Browsing** | Balanced | Стабильные ноды |

## 🛡️ Fallback Strategy

При блокировке маршрута, контроллер автоматически:

1. **Смена Exit** → сохраняя Entry и Relay
2. **Смена Relay** → сохраняя Entry и Exit
3. **Смена Entry** → полная замена пути
4. **SingleNode** → fallback на один сервер

## 🔧 Тестирование

```bash
# Запуск всех тестов
pytest tests/ -v

# Тест конкретного модуля
pytest tests/test_scoring.py -v

# С покрытием
pytest tests/ --cov=controller --cov=backend -v
```

### Тест fallback

```bash
# 1. Запустить backend
uvicorn backend.app:app --reload &

# 2. Добавить ноды и сгенерировать маршруты (см. выше)

# 3. Запустить controller
python -m controller.main &

# 4. Симулировать блокировку: деактивировать ноду
curl -X PATCH http://localhost:8000/api/nodes/{node_id} \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'

# 5. Наблюдать в логах: controller переключит маршрут
```

## 📁 Структура проекта

```
adaptive-stealth-network/
├── backend/
│   ├── __init__.py
│   ├── app.py              # FastAPI entry point
│   ├── database.py         # SQLAlchemy async engine
│   ├── models.py           # ORM: Node, Route, MetricRecord
│   ├── routes.py           # REST API endpoints
│   ├── schemas.py          # Pydantic validation
│   └── scheduler.py        # Background metrics collection
├── controller/
│   ├── __init__.py
│   ├── main.py             # Main control loop
│   ├── metrics.py          # Latency/loss/throughput measurement
│   ├── scoring.py          # Route scoring algorithm
│   ├── switcher.py         # Route switching + cooldown
│   ├── traffic_assign.py   # Traffic segmentation
│   ├── transport_adapt.py  # QUIC ↔ TCP fallback
│   ├── recovery.py         # Blocked route recovery
│   ├── anti_dpi.py         # Anti-DPI countermeasures
│   └── singbox_manager.py  # Sing-box config + process management
├── config/
│   ├── nodes.yaml          # Node definitions
│   ├── traffic_rules.yaml  # Traffic type rules
│   └── settings.yaml       # Global settings
├── utils/
│   ├── __init__.py
│   ├── logger.py           # Structured logging
│   └── helpers.py          # Common utilities
├── tests/
│   ├── test_scoring.py
│   ├── test_traffic_assign.py
│   ├── test_recovery.py
│   └── test_api.py
├── Instructions/           # Project specification documents
├── Dockerfile
├── docker-compose.yaml
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## ⚙️ Конфигурация

Все параметры настраиваются через `config/settings.yaml`:

- `loop_interval` — интервал цикла контроллера (по умолчанию 5 сек)
- `scoring_weights` — веса для формулы оценки маршрутов
- `cooldown_sec` — cooldown между переключениями (30 сек)
- `recovery_min/max_interval` — интервал recovery (60–120 сек)
- `anti_dpi.min/max_jitter_ms` — jitter для anti-DPI (10–50 мс)

## 📄 License

Private project. All rights reserved.
