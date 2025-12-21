#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки исправлений скачивания описаний плагинов.
Проверяет:
1. Сохранение краткого описания (summary) в JSON
2. Скачивание полной статичной страницы плагина
"""

import sys
import json
from pathlib import Path
from scraper.description_downloader import DescriptionDownloader
from scraper.metadata_store import MetadataStore
from config import settings

def test_summary_saving():
    """Тест сохранения summary в JSON."""
    print("=" * 60)
    print("Тест 1: Сохранение краткого описания (summary) в JSON")
    print("=" * 60)
    
    # Используем пример плагина из запроса пользователя
    addon_key = "com.onresolve.jira.groovy.groovyrunner"
    
    downloader = DescriptionDownloader()
    
    try:
        # Скачиваем описание через API
        json_path, html_path = downloader._download_api_description(
            addon_key=addon_key,
            download_media=False
        )
        
        if json_path and json_path.exists():
            print(f"✓ JSON файл создан: {json_path}")
            
            # Проверяем, что summary есть в JSON
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Проверяем summary в корне payload
            if 'summary' in data:
                summary = data['summary']
                print(f"✓ Summary найден в корне JSON: {len(summary)} символов")
                if summary:
                    print(f"  Первые 100 символов: {summary[:100]}...")
                else:
                    print("  ⚠ Summary пустой")
            else:
                print("  ✗ Summary не найден в корне JSON")
            
            # Проверяем summary в addon
            if 'addon' in data and isinstance(data['addon'], dict):
                addon_summary = data['addon'].get('summary') or data['addon'].get('tagLine')
                if addon_summary:
                    print(f"✓ Summary найден в addon: {len(addon_summary)} символов")
                else:
                    print("  ⚠ Summary не найден в addon")
        else:
            print(f"✗ JSON файл не создан")
            return False
            
    except Exception as e:
        print(f"✗ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

def test_full_page_download():
    """Тест скачивания полной статичной страницы."""
    print("\n" + "=" * 60)
    print("Тест 2: Скачивание полной статичной страницы")
    print("=" * 60)
    
    addon_key = "com.onresolve.jira.groovy.groovyrunner"
    
    downloader = DescriptionDownloader()
    store = MetadataStore()
    
    # Получаем marketplace_url из базы данных
    app = store.get_app_by_key(addon_key)
    marketplace_url = None
    
    if app:
        marketplace_url_raw = app.get('marketplace_url')
        if marketplace_url_raw:
            if isinstance(marketplace_url_raw, dict):
                marketplace_url = marketplace_url_raw.get('href', '')
            elif isinstance(marketplace_url_raw, str):
                marketplace_url = marketplace_url_raw.strip()
    
    if not marketplace_url:
        marketplace_url = f"https://marketplace.atlassian.com/apps/{addon_key}?hosting=datacenter&tab=overview"
        print(f"⚠ Marketplace URL не найден в БД, используем сконструированный: {marketplace_url}")
    else:
        print(f"✓ Marketplace URL найден: {marketplace_url}")
    
    try:
        # Скачиваем полную страницу
        json_path, html_path = downloader.download_description(
            addon_key=addon_key,
            marketplace_url=marketplace_url,
            download_media=True
        )
        
        if html_path and html_path.exists():
            print(f"✓ HTML файл создан: {html_path}")
            print(f"  Размер файла: {html_path.stat().st_size} байт")
            
            # Проверяем содержимое
            with open(html_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if len(content) > 1000:
                    print(f"✓ HTML файл содержит контент ({len(content)} символов)")
                    # Проверяем наличие ключевых элементов
                    if 'html' in content.lower() and 'body' in content.lower():
                        print("✓ HTML файл содержит базовую структуру")
                    else:
                        print("⚠ HTML файл может быть неполным")
                else:
                    print(f"⚠ HTML файл слишком маленький ({len(content)} символов)")
        else:
            print(f"✗ HTML файл не создан")
            return False
            
    except Exception as e:
        print(f"✗ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

def main():
    """Главная функция."""
    print("Тестирование исправлений скачивания описаний плагинов")
    print(f"Descriptions directory: {settings.DESCRIPTIONS_DIR}")
    print()
    
    results = []
    
    # Тест 1: Сохранение summary
    results.append(("Сохранение summary", test_summary_saving()))
    
    # Тест 2: Скачивание полной страницы
    results.append(("Скачивание полной страницы", test_full_page_download()))
    
    # Итоги
    print("\n" + "=" * 60)
    print("Итоги тестирования:")
    print("=" * 60)
    
    for name, result in results:
        status = "✓ ПРОЙДЕН" if result else "✗ ПРОВАЛЕН"
        print(f"{status}: {name}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n✓ Все тесты пройдены успешно!")
        return 0
    else:
        print("\n✗ Некоторые тесты провалены")
        return 1

if __name__ == "__main__":
    sys.exit(main())

