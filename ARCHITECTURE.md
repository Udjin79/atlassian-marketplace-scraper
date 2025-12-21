# Архитектура проекта Atlassian Marketplace Scraper

## Обзор

Atlassian Marketplace Scraper — это Python-приложение для сбора данных о приложениях из Atlassian Marketplace, включая метаданные приложений, информацию о версиях и загрузку бинарных файлов (JAR/OBR). Проект состоит из трех основных компонентов: скраперы, менеджер загрузок и веб-интерфейс.

## Архитектурная диаграмма

```
┌─────────────────────────────────────────────────────────────┐
│                    Пользовательский слой                      │
├─────────────────────────────────────────────────────────────┤
│  CLI скрипты:                                                │
│  - run_scraper.py (сбор приложений)                          │
│  - run_version_scraper.py (сбор версий)                     │
│  - run_downloader.py (загрузка бинарников)                   │
│  - run_description_downloader.py (скачивание описаний)       │
│  - app.py (веб-интерфейс Flask)                              │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Бизнес-логика                              │
├─────────────────────────────────────────────────────────────┤
│  scraper/                                                     │
│  ├── AppScraper          → Сбор приложений                   │
│  ├── VersionScraper      → Сбор версий (параллельно)         │
│  ├── DownloadManager     → Загрузка бинарников (параллельно) │
│  ├── DescriptionDownloader → Скачивание описаний (Playwright) │
│  ├── MarketplaceAPI      → API клиент v2                     │
│  ├── MarketplaceAPIv3    → API клиент v3                     │
│  └── Filters             → Фильтрация по дате/хостингу       │
│                                                               │
│  utils/                                                       │
│  ├── TaskManager         → Управление фоновыми задачами      │
│  ├── RateLimiter         → Контроль частоты запросов          │
│  ├── Checkpoint          → Сохранение прогресса               │
│  ├── Logger              → Логирование с ротацией            │
│  └── Credentials         → Управление учетными данными        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Слой данных                                │
├─────────────────────────────────────────────────────────────┤
│  models/                                                     │
│  ├── App              → Модель приложения                     │
│  ├── Version          → Модель версии                        │
│  └── DownloadStatus   → Статус загрузки                      │
│                                                               │
│  scraper/metadata_store.py                                    │
│  ├── MetadataStoreJSON    → Хранение в JSON (по умолчанию)   │
│  └── MetadataStoreSQLite  → Хранение в SQLite (опционально)  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Утилиты                                    │
├─────────────────────────────────────────────────────────────┤
│  utils/                                                       │
│  ├── RateLimiter       → Ограничение частоты запросов        │
│  ├── Checkpoint        → Сохранение прогресса                │
│  └── Logger            → Логирование                          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Внешние API                                │
├─────────────────────────────────────────────────────────────┤
│  Atlassian Marketplace API:                                   │
│  - REST API v2 (marketplace.atlassian.com/rest/2)            │
│  - REST API v3 (api.atlassian.com/marketplace/rest/3)        │
└─────────────────────────────────────────────────────────────┘
```

## Компоненты системы

### 1. Слой скрапинга (Scraper Layer)

#### 1.1. AppScraper (`scraper/app_scraper.py`)
**Назначение:** Сбор метаданных приложений из Marketplace

**Основные функции:**
- `scrape_all_products()` — сбор приложений для всех продуктов (Jira, Confluence, Bitbucket, Bamboo, Crowd)
- `scrape_product_apps()` — сбор приложений для конкретного продукта
- `scrape_single_app()` — сбор одного приложения по ключу

**Особенности:**
- Использует пагинацию API (batch_size = 50)
- Система чекпоинтов каждые 100 приложений
- Поддержка возобновления после прерывания
- Фильтрация только Server/Data Center приложений

**Зависимости:**
- `MarketplaceAPI` — для запросов к API
- `MetadataStore` — для сохранения данных
- `Checkpoint` — для сохранения прогресса

#### 1.2. VersionScraper (`scraper/version_scraper.py`)
**Назначение:** Сбор информации о версиях приложений

**Основные функции:**
- `scrape_all_app_versions()` — параллельный сбор версий для всех приложений
- `scrape_app_versions()` — сбор версий для конкретного приложения

**Особенности:**
- Параллельная обработка (ThreadPoolExecutor, по умолчанию 10 воркеров)
- Использует API v3 для получения appSoftwareIds
- Фильтрация по дате (последние 365 дней)
- Фильтрация по типу хостинга (только Server/Data Center)

**Зависимости:**
- `MarketplaceAPI` (v2) — для базовых запросов
- `MarketplaceAPIv3` — для получения версий
- `MetadataStore` — для сохранения
- `Filters` — для фильтрации данных

#### 1.3. DescriptionDownloader (`scraper/description_downloader.py`)
**Назначение:** Скачивание описаний плагинов со страниц Marketplace

**Основные функции:**
- `download_description()` — скачивание описания для одного приложения
- `download_all_descriptions()` — скачивание описаний для всех приложений
- `save_marketplace_page_with_playwright()` — сохранение страницы через Playwright (headless браузер)
- `save_marketplace_plugin_page()` — сохранение страницы с удалением скриптов (fallback)
- `save_marketplace_plugin_page_static()` — генерация статического HTML из API данных

**Особенности:**
- **Playwright метод (рекомендуется):** Использует headless Chromium для выполнения JavaScript и захвата полностью отрендеренной страницы
  - Формат MHTML: один файл со всеми ресурсами (CSS, изображения, шрифты)
  - Формат HTML: HTML + папка с ресурсами
  - Автоматическая авторизация через Basic Auth
  - Ожидание завершения загрузки JavaScript
- **Метод удаления скриптов (fallback):** Удаляет все `<script>` теги для предотвращения SPA роутинга
  - Скачивает CSS и изображения локально
  - Переписывает ссылки на локальные файлы
  - Работает оффлайн, но может не содержать контент, загружаемый через JavaScript
- **Статический API метод (fallback):** Генерирует HTML из данных REST API
  - Не требует JavaScript
  - Работает оффлайн
  - Может не содержать весь визуальный контент со страницы

**Зависимости:**
- `Playwright` — для headless браузера (опционально, но рекомендуется)
- `BeautifulSoup4` — для парсинга HTML
- `requests` — для HTTP запросов
- `MarketplaceAPI` — для получения данных через API

**Требования:**
- Playwright браузер: `playwright install chromium`
- Интернет-соединение для доступа к Marketplace

**Формат сохранения:**
- MHTML файлы: `{DESCRIPTIONS_DIR}/{addon_key}/full_page/index.mhtml`
- HTML файлы: `{DESCRIPTIONS_DIR}/{addon_key}/full_page/index.html`
- Медиа-файлы: `{DESCRIPTIONS_DIR}/{addon_key}/media/`

#### 1.4. DownloadManager (`scraper/download_manager.py`)
**Назначение:** Загрузка бинарных файлов (JAR/OBR)

**Основные функции:**
- `download_all_versions()` — загрузка всех версий
- `download_specific_version()` — загрузка конкретной версии
- `_download_single_version()` — внутренняя функция загрузки

**Особенности:**
- Параллельные загрузки (по умолчанию 3 потока)
- Автоматические повторы при ошибках (до 3 попыток)
- Проверка существующих файлов (пропуск уже загруженных)
- Проверка размера файла после загрузки
- Организация файлов: `data/binaries/{product}/{app_key}/{version_id}/`

**Зависимости:**
- `MarketplaceAPI` — для получения URL загрузки
- `MetadataStore` — для обновления статуса загрузки

### 2. API клиенты

#### 2.1. MarketplaceAPI (`scraper/marketplace_api.py`)
**Назначение:** Клиент для REST API v2

**Основные методы:**
- `search_apps()` — поиск приложений с фильтрами
- `get_app_details()` — детали приложения
- `get_app_versions()` — список версий (с пагинацией)
- `get_all_app_versions()` — все версии (автоматическая пагинация)
- `get_download_url()` — URL для загрузки
- `download_binary()` — загрузка файла

**Особенности:**
- Базовая HTTP-аутентификация (username + API token)
- Rate limiting с адаптивными задержками
- Автоматические повторы при ошибках (429, 5xx)
- Exponential backoff при повторах

#### 2.2. MarketplaceAPIv3 (`scraper/marketplace_api_v3.py`)
**Назначение:** Клиент для REST API v3 (используется для версий)

**Основные методы:**
- `get_app_software_ids()` — получение appSoftwareIds для приложения
- `get_all_app_versions_v3()` — получение всех версий через v3 API
- `format_compatibility_string()` — форматирование строки совместимости

**Особенности:**
- Используется для более детальной информации о версиях
- Поддержка разных типов хостинга (server, datacenter, cloud)

### 3. Слой данных

#### 3.1. Модели данных (`models/`)

**App (`models/app.py`):**
```python
@dataclass
class App:
    addon_key: str
    name: str
    vendor: str
    description: str
    products: List[str]
    hosting: List[str]
    categories: List[str]
    # ... другие поля
```

**Version (`models/version.py`):**
```python
@dataclass
class Version:
    addon_key: str
    version_id: str
    version_name: str
    release_date: str
    hosting_type: str
    download_url: Optional[str]
    downloaded: bool
    # ... другие поля
```

#### 3.2. Хранилище метаданных (`scraper/metadata_store.py`)

**MetadataStoreJSON:**
- Хранение приложений: `data/metadata/apps.json`
- Хранение версий: `data/metadata/versions/{app_key}_versions.json`
- Простая структура, легко читать/редактировать

**MetadataStoreSQLite:**
- Единая база данных: `data/metadata/marketplace.db`
- Более эффективные запросы
- Поддержка транзакций

**Выбор хранилища:** Контролируется через `USE_SQLITE` в настройках

**Основные методы:**
- `save_app()` / `save_apps_batch()` — сохранение приложений
- `get_all_apps()` — получение всех приложений (с фильтрами и пагинацией)
- `get_app_by_key()` — получение приложения по ключу
- `save_versions()` — сохранение версий
- `get_app_versions()` — получение версий приложения
- `update_version_download_status()` — обновление статуса загрузки

### 4. Веб-интерфейс (`web/`)

#### 4.1. Flask приложение (`app.py`)
**Назначение:** Веб-сервер для просмотра собранных данных

**Структура:**
- `web/routes.py` — маршруты Flask
- `web/templates/` — HTML шаблоны (Jinja2)
- `web/static/` — CSS и JavaScript

**Маршруты:**
- `GET /` — главная страница (дашборд со статистикой)
- `GET /apps` — список приложений (с фильтрами и пагинацией)
- `GET /apps/<addon_key>` — детали приложения
- `GET /download/<product>/<addon_key>/<version_id>` — загрузка бинарника
- `GET /api/apps` — JSON API для приложений
- `GET /api/apps/<addon_key>` — JSON API для деталей
- `GET /api/stats` — статистика
- `GET /api/products` — список продуктов

### 5. Утилиты (`utils/`)

#### 5.1. RateLimiter (`utils/rate_limiter.py`)
**Назначение:** Контроль частоты запросов к API

**Механизм:**
- Базовая задержка между запросами (по умолчанию 0.5 сек)
- Адаптивные задержки на основе HTTP статусов:
  - 429 (Too Many Requests) → увеличение задержки
  - 5xx (Server Error) → увеличение задержки
  - 200 (OK) → нормальная задержка

#### 5.2. Checkpoint (`utils/checkpoint.py`)
**Назначение:** Сохранение прогресса для возобновления работы

**Механизм:**
- Сохранение состояния в pickle файл
- Периодическое сохранение (каждые 100 приложений)
- Восстановление состояния при запуске с `--resume`

**Структура состояния:**
```python
{
    'product_index': 0,
    'current_product': 'jira',
    'app_offset': 0,
    'apps_processed': 150,
    'apps_collected': [...]
}
```

#### 5.3. Logger (`utils/logger.py`)
**Назначение:** Централизованное логирование

**Особенности:**
- Разные логгеры для разных модулей (scraper, download, web)
- Запись в файлы: `logs/scraper.log`, `logs/download.log`, `logs/description_downloader.log`
- Уровни логирования: DEBUG, INFO, WARNING, ERROR
- Ротация логов: максимальный размер 5 MB, до 5 резервных копий
- Безопасная ротация на Windows (обработка PermissionError)

#### 5.4. TaskManager (`utils/task_manager.py`)
**Назначение:** Управление фоновыми задачами через веб-интерфейс

**Основные функции:**
- Запуск задач в фоновых потоках через `subprocess.Popen`
- Хранение статуса задач в JSON файле (`task_status.json`)
- Отслеживание прогресса выполнения
- Управление процессами для возможности отмены

**Методы:**
- `start_scrape_apps(resume=False)` — запуск сбора приложений
- `start_scrape_versions()` — запуск сбора версий
- `start_download_binaries(product=None)` — запуск загрузки бинарников
- `start_download_descriptions(addon_key=None, download_media=True)` — запуск скачивания описаний
- `start_full_pipeline(...)` — последовательный запуск всех задач
- `cancel_task(task_id)` — отмена выполняющейся задачи
- `clear_completed_tasks()` — удаление завершенных задач
- `get_task_log_file(task_id)` — получение пути к лог-файлу задачи
- `get_task_status(task_id)` — получение статуса задачи
- `get_all_tasks()` — получение всех задач

**Особенности:**
- Thread-safe операции через `threading.Lock`
- Сохранение объектов процессов для корректной отмены
- Автоматическое обновление статуса (running, completed, failed, cancelled)
- Отслеживание текущего действия задачи через парсинг stdout
- Маппинг скриптов на лог-файлы для мониторинга

**Структура задачи:**
```python
{
    'task_id': 'scrape_apps_20241221_120000',
    'script': 'run_scraper.py',
    'status': 'running',  # running, completed, failed, cancelled
    'started_at': '2024-12-21T12:00:00',
    'finished_at': None,
    'progress': 45,
    'current_action': 'Processing app 150/300',
    'message': 'Running...',
    'return_code': None,
    'pid': 12345,
    'error': None
}
```

#### 5.5. Credentials Manager (`utils/credentials.py`)
**Назначение:** Безопасное хранение учетных данных API

**Особенности:**
- Хранение в `.credentials.json` (не в `.env`)
- Исключение из git через `.gitignore`
- Методы: `get_credentials()`, `save_credentials(username, api_token)`

### 6. Конфигурация (`config/`)

#### 6.1. Settings (`config/settings.py`)
**Назначение:** Централизованные настройки из переменных окружения

**Основные параметры:**
- `MARKETPLACE_USERNAME` — имя пользователя для API
- `MARKETPLACE_API_TOKEN` — токен API
- `SCRAPER_BATCH_SIZE` — размер батча для запросов (50)
- `SCRAPER_REQUEST_DELAY` — задержка между запросами (0.5 сек)
- `VERSION_AGE_LIMIT_DAYS` — фильтр по возрасту версий (365 дней)
- `MAX_CONCURRENT_DOWNLOADS` — параллельные загрузки (3)
- `MAX_VERSION_SCRAPER_WORKERS` — воркеры для версий (10)
- `USE_SQLITE` — использовать SQLite вместо JSON

#### 6.2. Products (`config/products.py`)
**Назначение:** Определение продуктов Atlassian

**Продукты:**
- jira
- confluence
- bitbucket
- bamboo
- crowd

## Потоки данных

### Поток 1: Сбор приложений
```
run_scraper.py
    ↓
AppScraper.scrape_all_products()
    ↓
MarketplaceAPI.search_apps() [для каждого продукта]
    ↓
App.from_api_response() [преобразование данных]
    ↓
MetadataStore.save_apps_batch() [сохранение]
    ↓
Checkpoint.save_checkpoint() [периодически]
```

### Поток 2: Сбор версий
```
run_version_scraper.py
    ↓
VersionScraper.scrape_all_app_versions()
    ↓
[ThreadPoolExecutor: параллельная обработка]
    ↓
VersionScraper.scrape_app_versions()
    ├─→ MarketplaceAPIv3.get_app_software_ids()
    ├─→ MarketplaceAPIv3.get_all_app_versions_v3()
    ├─→ Filters.filter_by_date()
    └─→ Filters.filter_by_hosting()
    ↓
Version.from_v3_api_response()
    ↓
MetadataStore.save_versions()
```

### Поток 3: Загрузка бинарников
```
run_downloader.py
    ↓
DownloadManager.download_all_versions()
    ↓
[ThreadPoolExecutor: параллельные загрузки]
    ↓
DownloadManager._download_single_version()
    ├─→ MarketplaceAPI.get_download_url()
    ├─→ requests.get() [загрузка файла]
    └─→ MetadataStore.update_version_download_status()
```

### Поток 4: Веб-интерфейс
```
app.py (Flask)
    ↓
web/routes.py [обработка HTTP запросов]
    ↓
MetadataStore.get_all_apps() / get_app_versions()
    ↓
render_template() [отображение HTML]
```

## Обработка ошибок

### Стратегии обработки ошибок:

1. **API запросы:**
   - Автоматические повторы при 429, 5xx ошибках
   - Exponential backoff
   - Логирование ошибок

2. **Загрузка файлов:**
   - До 3 попыток загрузки
   - Удаление частично загруженных файлов при ошибке
   - Проверка размера файла после загрузки

3. **Прерывание работы:**
   - Checkpoint система для возобновления
   - Обработка KeyboardInterrupt
   - Сохранение прогресса

4. **Веб-интерфейс:**
   - Обработка 404, 500 ошибок
   - Отображение понятных сообщений об ошибках

## Производительность

### Оптимизации:

1. **Параллелизм:**
   - VersionScraper: 10 параллельных воркеров
   - DownloadManager: 3 параллельные загрузки
   - ThreadPoolExecutor для эффективного использования ресурсов

2. **Rate Limiting:**
   - Адаптивные задержки
   - Предотвращение блокировок API

3. **Хранение данных:**
   - Батч-сохранение приложений
   - SQLite для быстрых запросов (опционально)

4. **Память:**
   - Стриминг при загрузке файлов
   - Обработка данных порциями

## Безопасность

1. **Аутентификация:**
   - Хранение credentials в `.credentials.json` (отдельно от `.env`)
   - `.credentials.json` исключен из git через `.gitignore`
   - Возможность управления через веб-интерфейс

2. **Валидация данных:**
   - Проверка существования файлов перед загрузкой
   - Валидация размеров файлов
   - Проверка расширений файлов для логов (предотвращение directory traversal)

3. **Обработка путей:**
   - Использование `os.path.join()` для безопасных путей
   - Проверка существования директорий
   - Использование `os.path.basename()` для предотвращения directory traversal

4. **Управление процессами:**
   - Безопасная отмена задач через SIGTERM
   - Обработка ошибок при завершении процессов
   - Очистка ресурсов при отмене задач

## Расширяемость

### Точки расширения:

1. **Новые источники данных:**
   - Добавление новых API клиентов
   - Поддержка других форматов данных

2. **Новые фильтры:**
   - Расширение `scraper/filters.py`
   - Добавление новых критериев фильтрации

3. **Новые хранилища:**
   - Реализация интерфейса MetadataStore
   - Поддержка PostgreSQL, MongoDB и т.д.

4. **Новые форматы экспорта:**
   - CSV, Excel экспорт
   - API для внешних систем

## Зависимости

### Основные библиотеки:
- `flask` — веб-фреймворк
- `requests` — HTTP клиент
- `pandas` — обработка данных (опционально)
- `tqdm` — прогресс-бары
- `python-decouple` — управление конфигурацией

## Структура директорий

```
atlassian-marketplace-scraper/
├── app.py                      # Flask приложение
├── run_scraper.py              # CLI: сбор приложений
├── run_version_scraper.py      # CLI: сбор версий
├── run_downloader.py           # CLI: загрузка бинарников
├── config/                     # Конфигурация
│   ├── settings.py             # Настройки
│   └── products.py             # Определение продуктов
├── scraper/                    # Логика скрапинга
│   ├── app_scraper.py
│   ├── version_scraper.py
│   ├── download_manager.py
│   ├── marketplace_api.py
│   ├── marketplace_api_v3.py
│   ├── metadata_store.py
│   └── filters.py
├── models/                     # Модели данных
│   ├── app.py
│   ├── version.py
│   └── download.py
├── utils/                      # Утилиты
│   ├── rate_limiter.py
│   ├── checkpoint.py
│   └── logger.py
├── web/                        # Веб-интерфейс
│   ├── routes.py
│   ├── templates/
│   └── static/
├── data/                       # Данные
│   ├── metadata/               # Метаданные (JSON/SQLite)
│   └── binaries/               # Бинарные файлы
└── logs/                       # Логи
```

## Заключение

Проект использует модульную архитектуру с четким разделением ответственности:
- **Слой скрапинга** — сбор данных
- **Слой данных** — хранение и управление данными
- **Веб-слой** — представление данных пользователю
- **Утилиты** — вспомогательные функции

Такая архитектура обеспечивает:
- Легкость тестирования
- Возможность расширения
- Поддержку и развитие
- Переиспользование компонентов

