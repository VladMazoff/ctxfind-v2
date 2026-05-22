# ctxfind-v2

Context-aware code search — AST edition (Alpha)

## Быстрый старт

```bash
# Установка (базовая — fast mode)
pip install -e .

# Поиск символа
ctxfind "User" ./src --format compact

# JSON вывод для LLM/автоматизации
ctxfind "User" ./src --format json

# С кросс-языковым линкером
ctxfind "User" ./src --link simple --format json
```

## Режимы

| Режим | Описание | Требования |
|-------|----------|------------|
| `fast` | Regex-based, быстрый, работает всегда | Нет |
| `deep` | AST-парсинг через tree-sitter | `pip install ctxfind[ast]` |
| `auto` | Автовыбор по размеру проекта | Нет |

## Форматы вывода

| Формат | Назначение |
|--------|-----------|
| `compact` | Человекочитаемый, с обрезкой |
| `json` | Машиночитаемый, для LLM |
| `full` | Полный контекст (debug) |

## Optional: AST support

```bash
# Установка AST-зависимостей
pip install ctxfind[ast]

# Проверка
ctxfind "main" ./src --mode deep --format json
```

**Известные ограничения:**
- Python 3.8 на Windows может требовать MSVC Build Tools для компиляции grammar
- Если установка не удалась — `deep` режим автоматически переключается на `fast`

## Архитектура

```
Query → Discovery → Parser (fallback chain) → Enricher → Renderer → Output
```

- **Parser**: regex-fallback (всегда), tree-sitter (опционально)
- **Enricher**: heuristic_scorer (v1 logic), cross_name_linker (опционально)
- **Renderer**: compact, json

## Примеры

```bash
# Поиск функции
ctxfind "process_user" ./src --kind function

# Только Python
ctxfind "User" ./src --lang python --format json

# С таймингами
ctxfind "User" ./src --verbose

# Версия
ctxfind --version
```

## Лицензия

MIT
