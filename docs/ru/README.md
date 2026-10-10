[EN](https://github.com/madgagarin/holarchy/blob/main/README.md) | [ES](https://github.com/madgagarin/holarchy/blob/main/docs/es/README.md) | **RU**

# Оркестратор Holarchy

[![Лицензия: MPL 2.0](https://img.shields.io/badge/License-MPL%202.0-brightgreen.svg)](https://opensource.org/licenses/MPL-2.0)
[![Версия PyPI](https://img.shields.io/pypi/v/holarchy.svg)](https://pypi.org/project/holarchy/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/release/python-3110/)

**Holarchy** — это высокопроизводительный оркестратор на базе конечных автоматов, предназначенный для управления длительными процессами ИИ и распределенными задачами. Он является ядром **Холархической Логической Сети (HLN)**, координируя **Холоны** (воркеры) через протокол **RXON**.

## 🚀 Основные возможности

- **Современный типизированный FSM**: Декларативные декораторы `@bp.start`, `@bp.step`, `@bp.decide`, `@bp.end`, классы `StatesGroup`, `State`, нативные модели `@dataclass` и `msgspec.Struct` (с прозрачной поддержкой Pydantic через duck-typing).
- **5 чистых зон хранения**: Четкое разделение доменных зон `input`, `steps`, `history`, `meta` и `output`.
- **Консультативная AI-маршрутизация и Replay-тестирование**: Принцип Host-Owned Choice, безопасный fallback, чеки выполнения `ExecutionReceipt` и CLI офлайн-оценки дрейфа решений (`holarchy replay evaluate`).
- **Автогенерация OpenAPI 3.1 и брендовая документация**: Спецификация на `/openapi.json` и интерактивный UI тестирования на `/docs`.
- **4-уровневое In-Memory кэширование и мемоизация**: Субмиллисекундная отдача спецификаций и графов благодаря потокобезопасному LRU/FIFO кэшу схем в `rxon`, кэшированию пространственной топологии DAG в `Blueprint`, а также предсериализованным байтам OpenAPI 3.1 JSON и HTML документации в `OrchestratorEngine` с автоматической инвалидацией при регистрации блупринтов.
- **Zero-Trust карточки инцидентов (Evidence Cards)**: Мгновенный постмортем-анализ через `GET /jobs/{id}/evidence?format=md` с классификацией первопричин.
- **Высокая производительность**: Индексация очередей через **ZSET**, механизм **Work Stealing** (кража задач) на Lua и атомарные переходы состояний.
- **Безопасность Zero Trust и слой политик**: Полная реализация `SecurityContext`, криптографическое подписание задач HMAC-SHA256 (`sig`) через `ORCHESTRATOR_SECRET_KEY`, проверка цепочек идентичности (Identity Chains) и гранулярные политики выполнения скиллов (`allowed_skills`).
- **Human-in-the-Loop Scoped Approval**: Безопасные одноразовые токены подтверждения (`approval_token`) для внешних вебхуков (Email, Slack, Telegram) без компрометации мастер-токенов клиентов.
- **Атомарность CAS и безопасность Watcher**: Защита от состояний гонки через CAS-транзакции (`update_job_state_atomic`) с гарантией невозможности перезаписи терминальных статусов таймаутами.
- **Строгая валидация конфигурации в проде**: Fail-safe контроль запуска (`ENVIRONMENT=production`), блокирующий старт при наличии дефолтных токенов или отсутствии секретных ключей.
- **Защита глубин холархии**: Настраиваемый лимит (`MAX_HOLARCHY_DEPTH`) для предотвращения бесконечной рекурсии суб-блупринтов с автоматической карантинизацией джобов.
- **Инфраструктура Middleware**: Гибкий `MiddlewareChain` для перехвата запросов, ответов хендлеров, входящих результатов и отправляемых задач.
- **D-DNA Криптоаудит**: CLI-инструменты верификации истории событий (`holarchy.cli.audit`), гарантирующие защиту цепочки от подделки.
- **Защита данных**: **Envelope Encryption** (шифрование конвертов) для токенов в Redis, строгая изоляция клиентов и защита от повторов (Replay Protection).
- **Работа с файлами**: Высокопроизводительный Async S3 стриминг через библиотеку `obstore`.
- **Observability**: Сквозная распределенная трассировка **Оркестратор ↔ Воркер** на базе **OpenTelemetry**, визуализация пространственного графа DAG (`/dag`) и метрики в реальном времени.

Этот документ служит исчерпывающим руководством для разработчиков, желающих создавать пайплайны (блупринты) и встраивать Оркестратор в свои приложения.

## Оглавление

- [Архитектура: Оркестратор, Блупринты и Воркеры](#архитектура-оркестратор-блупринты-и-воркеры)
- [Установка](#установка)
- [Быстрый старт: Использование в качестве библиотеки](#быстрый-старт-использование-в-качестве-библиотеки)
- [Ключевые концепции: JobContext и Actions](#ключевые-концепции-jobcontext-и-actions)
- [Cookbook Блупринтов: Ключевые возможности](#cookbook-блупринтов-ключевые-возможности)
  - [Условные переходы](#условные-переходы)
  - [Делегирование задач Воркерам (dispatch_task)](#делегирование-задач-воркерам-dispatch_task)
  - [Параллельное выполнение и Агрегация (Fan-out/Fan-in)](#параллельное-выполнение-и-агрегация-fan-outfan-in)
  - [Внедрение зависимостей (DataStore)](#внедрение-зависимостей-datastore)
  - [Нативный Планировщик (Native Scheduler)](#нативный-планировщик-native-scheduler)
  - [S3 Payload Offloading (Работа с файлами)](#s3-payload-offloading-работа-с-файлами)
  - [Уведомления через вебхуки](#уведомления-через-вебхуки)
- [Конфигурация для Production](#конфигурация-для-production)
  - [Файлы конфигурации](#файлы-конфигурации)
  - [Отказоустойчивость](#отказоустойчивость)
  - [Высокая доступность и Распределенная блокировка](#высокая-доступность-и-распределенная-блокировка)
  - [Бэкенд хранилища](#бэкенд-хранилища)
  - [Безопасность](#безопасность)
  - [Наблюдаемость](#наблюдаемость)
- [Руководство участника](#руководство-участника)
  - [Настройка окружения](#настройка-окружения)
  - [Запуск тестов](#запуск-тестов)

## Архитектура: Оркестратор, Блупринты и Воркеры

Holarchy разделяет логику управления рабочими процессами и распределенное выполнение вычислений на три основных компонента:

- **Оркестратор (`OrchestratorEngine`)**: Центральный координатор, управляющий персистентным состоянием задач, маршрутизацией, валидацией схем данных, повторными попытками и распределением задач через потоки Redis.
- **Блупринты (`Blueprint`)**: Декларативные графы состояний (конечные автоматы), определяющие этапы выполнения, правила переходов, схемы агрегации данных и обработчики шагов бизнес-процесса.
- **Воркеры (`Worker`)**: Автономные узлы выполнения, подключающиеся к оркестратору по модели обратного опроса через HTTP. Воркеры регистрируют поддерживаемые навыки и аппаратные ресурсы, получают задачи, выполняют вычислительную логику в изолированных каталогах и возвращают результаты.

В архитектуре HLN (Holarchical Logic Network) оркестратор отвечает за управление графом состояний, а воркеры предоставляют стандартизированные оболочки выполнения. Благодаря рекурсивной композиции экземпляр оркестратора может быть запущен внутри воркера, формируя многоуровневые иерархические кластеры.

## Экосистема

Holarchy является частью более широкой экосистемы:

- **[Протокол RXON](https://github.com/madgagarin/rxon)**: Легковесный протокол обратного соединения, обеспечивающий межузловое взаимодействие во всей экосистеме HLN.
- **[Holonode SDK](https://github.com/madgagarin/holonode)**: Официальный Python SDK для создания воркеров, подключаемых к этому движку.
- **[HLN (Holarchical Logic Network)](https://github.com/madgagarin/hln)**: Архитектурный паттерн, манифест и спецификация самоподобных холархий.
- **[Полный пример (Full Example)](https://github.com/madgagarin/holarchy-full-example)**: Готовый эталонный проект, демонстрирующий совместную работу движка и воркеров.

## Установка

- **Установка только ядра движка:**

  ```bash
  pip install holarchy
  ```

- **Установка с поддержкой Redis (рекомендуется для production):**

  ```bash
  pip install "holarchy[redis]"
  ```

- **Установка с поддержкой хранилища истории (SQLite, PostgreSQL):**

  ```bash
  pip install "holarchy[history]"
  ```

- **Установка с поддержкой телеметрии (OpenTelemetry):**

  ```bash
  pip install "holarchy[telemetry]"
  ```

- **Установка с поддержкой S3 (Payload Offloading):**

  ```bash
  pip install "holarchy[s3]"
  ```

- **Установка всех зависимостей, включая тестовые:**
  ```bash
  pip install "holarchy[all,test]"
  ```

## Статусы заданий (Job Statuses)

Задания в Holarchy проходят через различные состояния:

| Статус                 | Тип           | Описание                                                        |
| :--------------------- | :------------ | :-------------------------------------------------------------- |
| `pending`              | Промежуточный | Задание создано, ожидает постановки в очередь.                  |
| `running`              | Промежуточный | Активное выполнение логики блюпринта или задач.                 |
| `waiting_for_worker`   | Промежуточный | Задача отправлена, ожидается её захват воркером.                |
| `waiting_for_human`    | Промежуточный | Приостановлено, ожидается ручное подтверждение.                 |
| `waiting_for_parallel` | Промежуточный | Ожидание завершения всех параллельных подзадач.                 |
| `finished`             | **Финальный** | Успешно завершено. **Результат доступен.**                      |
| `failed`               | **Финальный** | Ошибка в логике или на стороне воркера. **Результат доступен.** |
| `cancelled`            | **Финальный** | Отменено пользователем или системой вручную.                    |
| `error`                | **Финальный** | Критическая системная ошибка инфраструктуры.                    |
| `quarantined`          | **Финальный** | Помещено в карантин (например, при нарушении контракта).        |

### Современная наблюдаемость

Holarchy спроектирована с учетом глубокой наблюдаемости по стандарту **OpenTelemetry**. Это дает:

- **Распределенная трассировка**: Отслеживание запросов через всю сеть HLN (Оркестратор ↔ Воркер).
- **Метрики в реальном времени**: Мониторинг длины очередей, здоровья воркеров и задержек выполнения.
- **OTLP Native**: Прямая отправка данных в Jaeger, Prometheus или Grafana.

Чтобы включить поддержку телеметрии при установке:

```bash
pip install "holarchy[telemetry]"
```

Подробности в [**Руководстве по системе наблюдения**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/observability.md).

## Быстрый старт: Использование в качестве библиотеки

Вы можете легко интегрировать и запустить движок оркестратора внутри вашего собственного приложения.

> **Совет:** В v1.0.0 используйте декларативные декораторы `@bp.start(State)`, `@bp.step(State, condition=...)` и `@bp.end(State)`. Легаси-декоратор `@bp.handler(state_name)` сохраняется для полной обратной совместимости.

```python
# my_app.py
from asyncio import Event, run
from dataclasses import dataclass

from holarchy import Blueprint, OrchestratorEngine
from holarchy.config import Config
from holarchy.context import ActionFactory
from holarchy.fsm import State, StatesGroup
from holarchy.storage import MemoryStorage


@dataclass
class OrderInput:
    order_id: int
    amount: float


class OrderFlow(StatesGroup):
    start = State()
    finalize = State()


storage = MemoryStorage()
config = Config()
config.CLIENT_TOKEN = "my-secret-client-token"
config.GLOBAL_WORKER_TOKEN = "my-secret-worker-token"

bp = Blueprint(name="order_pipeline", api_version="v1", api_endpoint="/jobs/order")


@bp.start(OrderFlow.start)
async def process_start(data: OrderInput, actions: ActionFactory) -> State:
    """Начальное состояние для каждого нового задания."""
    print(f"Заказ #{data.order_id} принят, сумма: {data.amount}")
    return OrderFlow.finalize


@bp.end(OrderFlow.finalize)
async def process_finalize(context) -> dict[str, str]:
    """Конечное состояние. Пайплайн заканчивается здесь."""
    print(f"Задание {context.job_id} завершено.")
    return {"status": "completed"}


engine = OrchestratorEngine(storage, config)
engine.register_blueprint(bp)


async def main() -> None:
    await engine.start()
    try:
        await Event().wait()
    finally:
        await engine.stop()


if __name__ == "__main__":
    try:
        run(main())
    except KeyboardInterrupt:
        print("\nОстановка сервера.")
```

### Жизненный цикл движка: `run()` vs. `start()`

`OrchestratorEngine` предлагает два способа запуска сервера:

- **`engine.run()`**: Это простой, **блокирующий** метод. Он полезен для отдельных скриптов, где оркестратор является единственным основным компонентом. Он управляет запуском и остановкой сервера за вас. Не следует использовать его внутри `async def` функции, которая является частью большего приложения, так как это может конфликтовать с циклом событий.

- **`await engine.start()`** и **`await engine.stop()`**: Это неблокирующие методы для интеграции движка в большее `asyncio` приложение.
  _ `start()` настраивает и запускает веб-сервер в фоне.
  _ `stop()` корректно останавливает сервер и очищает ресурсы.
  Пример "Быстрый старт" выше демонстрирует правильный способ использования этих методов.

## Ключевые концепции

### Высокопроизводительная Архитектура

Holarchy спроектирована для высоконагруженных сред с тысячами конкурентных воркеров.

- **Стандартизированный Holon Matching (RXON)**: Высокопроизводительная маршрутизация с использованием Redis.
  - **Унифицированный подбор**: Переход на формализованную логику подбора из `rxon`. Все проверки ресурсов (CPU, RAM, GPU и пользовательские свойства) строго регламентированы стандартом протокола HLN.
  - **Умное сравнение чисел**: Автоматическое выполнение проверок **GE (Больше или равно)** для чисел.
  - **Deep Schema Matching**: Приоритет отдается воркерам, чья `input_schema` соответствует параметрам задачи.
  - **Overflow Strategy**: Автоматический перелив нагрузки на более дорогих воркеров, если дешевые перегружены (`queue_length > SOFT_LIMIT`).
  - **Hot Cache & Skill Awareness**: Учет загруженных AI-моделей в памяти воркеров.
  - **Work Stealing**: Свободные воркеры могут атомарно «красть» задачи из очередей перегруженных коллег на скорости O(1).
  - **Load Balancing**: Оптимистичное управление нагрузкой для предотвращения перегрузки узлов.
  - **Эффективная сеть**: TCP Keep-Alive и сжатие ответов Zstd/Gzip.
  - **Асинхронный логгинг**: Неблокирующая обработка логов через `QueueHandler`.
  - **Offloaded IO**: Вынос тяжелой сериализации в потоки и оптимизация индексов БД для истории.
- **Саморегулирующаяся репутация**:
  - **Система штрафов**: Мгновенное снижение репутации за нарушение контракта (-0.2) или критические сбои.
  - **Цикл восстановления**: Небольшие бонусы к репутации за каждое успешное выполнение (+0.001).
  - **Reputation Guard**: Автоматическое игнорирование узлов с репутацией ниже `REPUTATION_MIN_THRESHOLD`.
- **Zero Trust Security (Нулевое доверие)**:
  - **mTLS (Mutual TLS)**: Взаимная аутентификация Оркестратора и Воркеров по сертификатам.
  - **STS (Security Token Service)**: Механизм ротации токенов.
  - **Атомарное управление состоянием**: Использование Lua-скриптов и транзакций Redis для обеспечения консистентности при экстремальных параллельных нагрузках.
- **Архитектура на базе контрактов**:
  - **Валидация API**: Строгая проверка входных данных (`input`) против контрактов Блюпринтов.
  - **Контроль результатов**: Автоматическая проверка ответов воркеров на соответствие их `output_schema`.
  - **Ghost Signaling**: Блюпринты могут генерировать кастомные события через `actions.send_event()`.
- **Network Visibility**:
  - **Skill Catalog**: Агрегированный маркетплейс всех уникальных навыков и контрактов в реальном времени.
  - **Global Registry**: Контракты хранятся в Redis для консистентности всего кластера.
- **Bi-directional Heartbeats**: Двусторонний канал связи, где оркестратор посылает срочные команды в ответ на оптимизированные Heartbeat с использованием Jitter (защита от Thundering Herd).
- **Non-Blocking I/O**:
  - **Вебхуки**: Отправляются через параллельный пул фоновых воркеров.
  - **S3 Streaming**: Константное потребление памяти при передаче файлов любого размера.

## Книга Рецептов: Ключевые возможности

### 1. Условные переходы

Передавайте условия напрямую в `@bp.step()` (или `@bp.handler()`) для создания ветвлений условной логики. Условия задаются как декларативные **`FastF`-выражения** из библиотеки `fast-magic-filter` и разрешаются через 4-уровневый каскад `StepScope` (текущий скоуп $\rightarrow$ `input` $\rightarrow$ `steps`).

```python
from holarchy import Blueprint, Context, F, State, StatesGroup


class Flow(StatesGroup):
    decision = State()
    urgent_processing = State()
    priority_lane = State()
    normal_processing = State()


# Прямое сопоставление полей input через StepScope
@bp.step(Flow.decision, condition=F.type == "urgent")
async def handle_urgent(ctx: Context):
    ctx.actions.go_to(Flow.urgent_processing)


# Составное условие с логическим И
@bp.step(Flow.decision, condition=(F.priority >= 8) & (F.active == True))
async def handle_priority(ctx: Context):
    ctx.actions.go_to(Flow.priority_lane)


# Шаг по умолчанию, если ни одно предыдущее условие не совпало
@bp.step(Flow.decision)
async def handle_default(ctx: Context):
    ctx.actions.go_to(Flow.normal_processing)
```

**Поддерживаемый синтаксис условий:**

| Паттерн                            | Пример                              |
| ---------------------------------- | ----------------------------------- |
| Доступ к атрибуту                  | `F.status == "done"`                |
| Доступ по ключу словаря            | `F.data["key"] == 42`               |
| Логические AND / OR / NOT          | `(F.x > 0) & (F.y < 10)`, `~F.flag` |
| Операторы сравнения                | `F.score >= 80`, `F.retries < 3`    |
| `in` / `not_in`                    | `F.role.in_(["admin", "mod"])`      |
| Регулярные выражения (`re.search`) | `F.text.regexp(r"^done")`           |
| Агрегаторы списков                 | `(F.tags[...] == "vip").any()`      |
| Произвольная функция               | `F.value.func(my_predicate)`        |

> **Примечание:** Отсутствующие атрибуты и промежуточные значения `None` обрабатываются безопасно — возвращается `False` вместо `AttributeError`. Это намеренное улучшение по сравнению с `magic-filter`.

### 2. Делегирование задач Воркерам (`dispatch_task`)

Это основная функция для делегирования работы. Оркестратор поставит задачу в очередь и будет ждать, пока воркер заберет ее и вернет результат.

```python
@bp.step
async def transcode_video(input: dict, actions: ActionFactory):
    actions.dispatch_task(
        task_type="video_transcoding",
        params={"input_path": input.get("path")},
        # Определяем следующий шаг на основе статуса ответа воркера
        transitions={
            "success": "publish_video",
            "failure": "transcoding_failed",
            "needs_review": "manual_review",  # Пример кастомного статуса
        },
    )
```

Если воркер вернет статус, не указанный в `transitions`, задание автоматически перейдет в состояние сбоя.

### 3. Параллельное выполнение и Агрегация (Fan-out/Fan-in)

Запуск нескольких задач одновременно и сбор их результатов. **Изоляция состояния веток** предотвращает гонки данных при одновременном возврате результатов.

```python
# 1. Fan-out: Отправка нескольких задач для агрегации в одно состояние
@bp.step
async def process_files(input: dict, actions: ActionFactory):
    tasks_to_dispatch = [{"task_type": "file_analysis", "params": {"file": file}} for file in input.get("files", [])]
    # Используйте dispatch_parallel, чтобы отправить все задачи сразу.
    # Все успешные задачи неявно приведут к состоянию 'aggregate_into'.
    actions.dispatch_parallel(tasks=tasks_to_dispatch, aggregate_into="aggregate_results")


# 2. Fan-in: Сбор результатов с помощью декоратора @aggregator
@bp.aggregator
async def aggregate_results(aggregation_results, steps, actions):
    # Этот обработчик выполнится ТОЛЬКО ПОСЛЕ ТОГО, как ВСЕ задачи,
    # отправленные через dispatch_parallel, будут завершены.

    # aggregation_results это словарь {task_id: result_dict}
    summary = [res.get("data") for res in aggregation_results.values()]
    steps["summary"] = summary
    actions.go_to("processing_complete")
```

### 4. Внедрение зависимостей (DataStore)

Предоставление обработчикам доступа к внешним ресурсам (например, кэшу или клиенту БД).

```python
from redis.asyncio import Redis

# 1. Инициализация и регистрация вашего DataStore
redis_client = Redis(decode_responses=True)
bp = Blueprint("blueprint_with_datastore", data_stores={"cache": redis_client})


# 2. Использование его в обработчике через внедрение зависимостей
@bp.step
async def get_from_cache(data_stores):
    # Доступ к redis_client по имени "cache"
    user_data = await data_stores.cache.get("user:123")
    print(f"User from cache: {user_data}")
```

### 5. Нативный Планировщик (Native Scheduler)

Holarchy включает в себя встроенный распределенный планировщик. Он позволяет запускать блупринты периодически (интервально, ежедневно, еженедельно, ежемесячно) без внешних инструментов типа cron.

- **Конфигурация:** Определяется в `schedules.toml`.
- **Часовые пояса:** Поддерживает глобальную настройку часового пояса (например, `TZ="Europe/Moscow"`).
- **Поддержка протухания:** Поддерживает параметры `dispatch_timeout` и `result_timeout`.
- **Распределенная блокировка:** Задачи гарантированно запускаются только один раз за интервал благодаря распределенным блокировкам (Redis/Memory).

```toml
# Пример schedules.toml
[nightly_backup]
blueprint = "backup_flow"
daily_at = "02:00"
dispatch_timeout = 60 # Отмена, если ни один воркер не взял задачу за 1 минуту
```

### 6. Вебхуки (Webhook Notifications)

Оркестратор может отправлять асинхронные уведомления во внешнюю систему при завершении, сбое или карантине задачи.

### 7. Работа с большими данными (S3 Payload Offloading)

Оркестратор предоставляет встроенную поддержку для работы с большими файлами через S3-совместимые хранилища, используя высокопроизводительную библиотеку `obstore` (Rust).

- **Безопасность памяти (Streaming)**: Потоковая передача данных для загрузки и скачивания.
- **Управляемый режим**: Автоматическая очистка S3 объектов и локальных временных файлов.
- **Внедрение зависимостей**: Используйте аргумент `task_files` в ваших хендлерах.

```python
@bp.step
async def process_data(task_files, actions):
    # Потоковое скачивание большого файла
    local_path = await task_files.download("large_dataset.csv")

    # ... обработка данных ...

    # Загрузка результата
    await task_files.write_json("results.json", {"status": "done"})

    actions.go_to("finished")
```

## API Группы и Версионирование

Все внешние эндпоинты API строго версионированы и имеют префикс `/api/v1/`.

- **События:**
  - `job_finished`: Задание достигло финального успеха.
  - `job_failed`: Задание завершилось ошибкой.
  - `job_quarantined`: Задание отправлено в карантин после повторных сбоев.

**Пример запроса:**

```http
POST /api/v1/jobs/my_flow
{
    "input": {
        "video_url": "..."
    },
    "webhook_url": "https://my-app.com/webhooks/holarchy",
    "dispatch_timeout": 30,
    "result_timeout": 120
}

```

**Пример вебхука:**

```json
{
  "event": "job_finished",
  "job_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "finished",
  "result": {
    "output_path": "/videos/result.mp4"
  },
  "error": null
}
```

## Конфигурация для продакшена

Поведение оркестратора можно настроить через переменные окружения. Также систему отличает **строгая валидация** конфигурационных файлов (`clients.toml`, `workers.toml`) при запуске.

### Файлы конфигурации

- **`clients.toml`**: Определяет клиентов API, их токены, планы и квоты.
- **`workers.toml`**: Определяет индивидуальные токены для воркеров. Поддержка **шаблонов fnmatch** (например, `cpu-worker-*`) для динамического масштабирования.
- **`schedules.toml`**: Определяет периодические задачи для нативного планировщика.

Для получения подробных спецификаций и примеров, пожалуйста, обратитесь к [**Гайду по конфигурации**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/configuration.md).

### Отказоустойчивость

- **TRANSIENT_ERROR**: Временная ошибка. Автоматические ретраи.
- **PERMANENT_ERROR**: Постоянная ошибка. Немедленный карантин.
- **INVALID_INPUT_ERROR**: Ошибка во входных данных. Сбой всего задания.

### Гарантии стабильности

- **Exponential Backoff:** Основные циклы (`JobExecutor`, `Watcher`) автоматически замедляются при сбоях инфраструктуры.
- **Защита от захвата задач:** Только назначенный воркер может отправить результат.
- **Защита от циклов:** `MAX_TRANSITIONS_PER_JOB` (по умолчанию 100) завершает зацикленные блупринты.

### Конкурентность и Производительность

- **`EXECUTOR_MAX_CONCURRENT_JOBS`**: Лимит одновременных обработчиков (по умолчанию: `1000`).
- **`WATCHER_LIMIT`**: Количество проверяемых таймаутов за цикл (по умолчанию: `500`).
- **`DISPATCHER_MAX_CANDIDATES`**: Лимит проверки соответствия воркеров (по умолчанию: `50`).

### Наблюдаемость

- **Структурированное JSON логирование**: Неблокирующая очередь `QueueHandler`.
- **Глубокая наблюдаемость**: Трассировка и метрики на базе OpenTelemetry (через OTLP).

### Слой хранилища

- **Redis (StorageBackend)**: Хранение состояний (`msgpack`) и очередей (Streams).
- **PostgreSQL/SQLite (HistoryStorage)**: Архив истории с оптимизированными индексами.

### Безопасность и защита данных

- **Безопасность Zero Trust**: Взаимная аутентификация (mTLS) и обязательная подпись сообщений **HMAC SHA256** для защиты от подмены данных в Redis и подмены воркеров.
- **Гранулярные политики скиллов (`policy`)**: Ограничение разрешённых скиллов джоба через `policy: {"allowed_skills": ["skill_a", "skill_b"]}`.
- **Защита глубин холархии (`MAX_HOLARCHY_DEPTH`)**: Настраиваемый лимит (по умолчанию 10) для предотвращения бесконечной рекурсии вложенных блупринтов.
- **Инфраструктура Middleware (`MiddlewareChain`)**: Перехват запросов/ответов хендлеров, исходящих задач и входящих событий воркеров.
- **D-DNA Криптоаудит (`holarchy.cli.audit`)**: Проверка целостности журнала истории джобов через криптографическую цепочку хэшей.
- **Защита от Replay-атак**: Строгая валидация временных меток (`timestamp`) с окном 60 секунд.
- **Identity Chain Integrity**: Математическая верификация цепочек идентичности в холархиях (подпись покрывает весь путь сигнала).
- **Envelope Encryption**: Если задан `REDIS_ENCRYPTION_KEY`, токены воркеров шифруются в Redis (AES-GCM).
- **Режимы аутентификации**: Поддержка `WORKER_AUTH_MODE` (`mixed`, `mtls-only`, `token-only`).
- **Строгая изоляция клиентов**: Задачи жестко привязаны к `client_token`. Клиент может получать доступ, управлять или скачивать файлы только для тех задач, которые он создал.
- **Политика детализации API**: По умолчанию API возвращает минимум полей для безопасности. Полная детализация включается через `DETAILED_API_RESPONSES="true"`.
- **Гибкий префикс API**: Клиентское API можно переместить или скрыть через `CLIENT_API_PREFIX`.

#### Пример использования политик скиллов (`policy`):

```http
POST /api/v1/jobs/my_flow
{
    "input": {"input_val": 42},
    "policy": {
        "allowed_skills": ["data_extractor", "pdf_generator"]
    },
    "max_transitions": 50
}
```

#### Пример использования Middleware (`MiddlewareChain`):

```python
from holarchy.middleware import BaseMiddleware


class AuditLogMiddleware(BaseMiddleware):
    async def process_outbound_task(self, context, task_payload):
        task_payload["audit_tag"] = "monitored"
        return task_payload


engine.middleware_chain.add(AuditLogMiddleware())
```

#### Пример запуска D-DNA Криптоаудита (`holarchy.cli.audit`):

```python
from holarchy.cli.audit import verify_d_dna_integrity

is_valid, error = verify_d_dna_integrity(job_history_events, audit_salt="my_secret_salt")
if not is_valid:
    print(f"Обнаружена подмена данных истории: {error}")
```

#### Детерминированный Replay CLI (`holarchy replay evaluate`):

Офлайн-оценка исторических чеков выполнения (`ExecutionReceipt`) против обновленной логики блупринта для контроля дрейфа решений перед выкаткой в прод:

```bash
# Оценка исторических решений
holarchy replay evaluate --app my_module:bp --cases .holarchy/replay/cases.jsonl

# Строгий режим для CI (код возврата 1 при любом обнаруженном дрейфе)
holarchy replay evaluate --app my_module:bp --cases .holarchy/replay/cases.jsonl --strict
```

### Лимитирование запросов

Гранулярный Redis-лимитер (Heartbeats: 120/мин, Polling: 60/мин, Общий: 100/мин).

> **Примечание:** Воркеры получают стандартный заголовок **`Retry-After`** при блокировке для «умного» ожидания.

## Руководство участника

### Настройка окружения

```bash
pip install -e ../rxon
pip install -e ".[all,test]"
```

### Запуск тестов

```bash
pytest tests/
```

### Интерактивная документация API

Доступна по адресу `/_public/docs`. Динамическая генерация на основе блупринтов.

## Подробная документация

- [**Архитектурный гайд**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/architecture.md)
- [**Справочник API**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/api_reference.md)
- [**Гайд по конфигурации**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/configuration.md)
- [**Система наблюдения (Observability)**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/observability.md)
- [**Протокол трассировки**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/observability_protocol.md)
- [**Руководство по развертыванию**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/deployment.md)
- [**Cookbook**](https://github.com/madgagarin/holarchy/blob/main/docs/ru/cookbook/README.md)
