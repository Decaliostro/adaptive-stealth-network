NodeTypes:

  Entry:
    description: Точка входа клиента
    role: Принимает соединение
    requirement: стабильность, маскировка трафика

  Relay:
    description: Промежуточный узел
    role: Передача трафика
    requirement: может быть менее мощным

  Exit:
    description: Выход в интернет
    role: Финальный узел
    requirement: высокая пропускная способность

  Master:
    description: Основной управляющий сервер
    role: Хранит конфигурацию и список узлов

  Slave:
    description: Пользовательские или дополнительные сервера
    role: Используются как Entry / Relay / Exit