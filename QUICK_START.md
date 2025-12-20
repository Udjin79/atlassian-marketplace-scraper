# Быстрый старт

## Установка (Windows)

1. Откройте PowerShell в директории проекта
2. Запустите:
   ```powershell
   .\install.ps1
   ```

Скрипт автоматически установит все необходимое и создаст файл `.env` с настройками.

## Настройка путей

Проект настроен для работы с несколькими дисками:

- **Метаданные**: `I:\marketplace\`
- **Бинарные файлы**:
  - Jira → `H:\marketplace-binaries\jira\`
  - Confluence → `K:\marketplace-binaries\confluence\`
  - Bitbucket → `V:\marketplace-binaries\bitbucket\`
  - Bamboo → `W:\marketplace-binaries\bamboo\`
  - Crowd → `F:\marketplace-binaries\crowd\`
- **Логи**: `I:\marketplace\logs\`

Если нужно изменить пути, отредактируйте файл `.env`.

## Использование

1. **Активируйте виртуальное окружение:**
   ```powershell
   venv\Scripts\Activate.ps1
   ```

2. **Соберите приложения:**
   ```powershell
   python run_scraper.py
   ```

3. **Соберите версии:**
   ```powershell
   python run_version_scraper.py
   ```

4. **Загрузите бинарники (опционально):**
   ```powershell
   python run_downloader.py
   ```

5. **Запустите веб-интерфейс:**
   ```powershell
   python app.py
   ```

Откройте браузер: http://localhost:5000

## SECRET_KEY

SECRET_KEY автоматически генерируется при установке. Если нужно сгенерировать новый:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Скопируйте результат в файл `.env` в переменную `SECRET_KEY`.

## Дополнительная информация

- [USER_GUIDE.md](USER_GUIDE.md) - Полное руководство пользователя
- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура проекта
- [SETUP_GUIDE.md](SETUP_GUIDE.md) - Детальная инструкция по настройке

