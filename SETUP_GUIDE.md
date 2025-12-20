# Руководство по установке и настройке

## Быстрая установка (Windows)

1. Откройте PowerShell в директории проекта
2. Запустите скрипт установки:
   ```powershell
   .\install.ps1
   ```

Скрипт автоматически:
- Проверит наличие Python
- Создаст виртуальное окружение
- Установит все зависимости
- Создаст файл `.env` с настройками

## Настройка путей хранения

Проект настроен для распределения данных по нескольким дискам:

### Текущая конфигурация:

- **Метаданные и база данных**: `I:\marketplace\`
- **Бинарные файлы по продуктам**:
  - **Jira** → `H:\marketplace-binaries\jira\`
  - **Confluence** → `K:\marketplace-binaries\confluence\`
  - **Bitbucket** → `V:\marketplace-binaries\bitbucket\`
  - **Bamboo** → `W:\marketplace-binaries\bamboo\`
  - **Crowd** → `F:\marketplace-binaries\crowd\`
- **Логи**: `I:\marketplace\logs\`

### Изменение путей

Отредактируйте файл `.env` и измените соответствующие переменные:

```env
# Метаданные
METADATA_DIR=I:\marketplace\metadata
DATABASE_PATH=I:\marketplace\marketplace.db

# Бинарные файлы для каждого продукта
BINARIES_DIR_JIRA=H:\marketplace-binaries\jira
BINARIES_DIR_CONFLUENCE=K:\marketplace-binaries\confluence
BINARIES_DIR_BITBUCKET=V:\marketplace-binaries\bitbucket
BINARIES_DIR_BAMBOO=W:\marketplace-binaries\bamboo
BINARIES_DIR_CROWD=F:\marketplace-binaries\crowd

# Логи
LOGS_DIR=I:\marketplace\logs
```

## SECRET_KEY для Flask

SECRET_KEY используется Flask для защиты сессий и cookies. 

### Автоматическая генерация

Скрипт `install.ps1` автоматически генерирует SECRET_KEY при создании `.env` файла.

### Ручная генерация

Если нужно сгенерировать новый SECRET_KEY:

**В PowerShell:**
```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

**В командной строке:**
```cmd
python -c "import secrets; print(secrets.token_hex(32))"
```

**В Python:**
```python
import secrets
print(secrets.token_hex(32))
```

Скопируйте сгенерированную строку и вставьте в `.env`:
```env
SECRET_KEY=ваша_сгенерированная_строка
```

### Важно

- **НЕ** используйте один и тот же SECRET_KEY в production и development
- **НЕ** публикуйте SECRET_KEY в публичных репозиториях
- Используйте случайную строку длиной не менее 32 символов

## Использование SQLite

В настройках установлено `USE_SQLITE=True`, что означает:
- Данные хранятся в базе данных SQLite вместо JSON файлов
- Более быстрые запросы для больших объемов данных
- База данных находится по пути: `I:\marketplace\marketplace.db`

## Проверка установки

После установки проверьте:

1. **Виртуальное окружение активировано:**
   ```powershell
   venv\Scripts\Activate.ps1
   ```

2. **Зависимости установлены:**
   ```powershell
   pip list
   ```

3. **Файл .env существует и настроен:**
   ```powershell
   Get-Content .env
   ```

4. **Директории созданы:**
   Проверьте, что все указанные пути существуют или будут созданы автоматически при первом запуске.

## Первый запуск

1. Активируйте виртуальное окружение:
   ```powershell
   venv\Scripts\Activate.ps1
   ```

2. Запустите сбор приложений:
   ```powershell
   python run_scraper.py
   ```

3. После завершения запустите сбор версий:
   ```powershell
   python run_version_scraper.py
   ```

4. (Опционально) Загрузите бинарные файлы:
   ```powershell
   python run_downloader.py
   ```

5. Запустите веб-интерфейс:
   ```powershell
   python app.py
   ```

Откройте браузер: http://localhost:5000

## Решение проблем

### Ошибка: "Execution of scripts is disabled"

Если PowerShell блокирует выполнение скрипта:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Ошибка: "Python не найден"

Установите Python 3.8+ с [python.org](https://www.python.org/downloads/)
Убедитесь, что Python добавлен в PATH.

### Ошибка: "Permission denied" при создании директорий

Убедитесь, что у вас есть права на запись в указанные диски (H:, I:, K:, V:, W:, F:).

### Диски не существуют

Если какие-то диски недоступны, измените пути в `.env` на доступные диски.

