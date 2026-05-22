"""
ctxfind-v2: CLI Entry Point

Стратегия:
- Минимум логики в CLI: только парсинг аргументов и оркестрация
- Вся бизнес-логика — в ядре
- Режимы: fast/deep/auto выбираются здесь, но реализуются в парсерах
"""

import sys
import io
import os

# Добавляем родительскую директорию в путь, чтобы импорты работали при прямом запуске
if __name__ == "__main__" and __package__ is None:
    # Запущено как python cli.py, не как python -m ctxfind-v2.cli
    cli_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(cli_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)
        # Теперь импорты будут работать как абсолютные

import argparse
import logging
from pathlib import Path
from typing import List, Optional

# Импорт всех модулей для автоматической регистрации в реестре
# Эти импорты запускают register_parser/register_enricher/register_renderer
import core
import parsers
import enrichers
import renderers

from core.models import QueryMode, RenderHint
from core.registry import parsers as registry_parsers, enrichers as registry_enrichers, renderers as registry_renderers
from orchestrator import SearchOrchestrator, prepare_render_hints
from config import get_config

def build_parser() -> argparse.ArgumentParser:
    """Настроить CLI-аргументы"""
    config = get_config()

    p = argparse.ArgumentParser(
        prog="ctxfind",
        description="Context-aware code search — v2 (AST edition)"
    )

    # Обязательные
    p.add_argument("query", help="Что ищем (имя символа, паттерн)")
    p.add_argument("path", help="Путь к файлу или директории", type=Path)

    # Режимы
    p.add_argument(
        "--mode",
        choices=["fast", "deep", "auto"],
        default=config.default_mode,
        help="Режим поиска: fast=эвристики, deep=AST, auto=выбор по размеру"
    )

    # Вывод
    p.add_argument(
        "--format",
        choices=["compact", "full", "json", "llm"],
        default=config.default_format,
        help="Формат вывода"
    )
    p.add_argument("--max-lines", type=int, default=config.default_max_lines,
                   help="Лимит строк в выводе")
    p.add_argument("--max-tokens", type=int, default=config.default_max_tokens,
                   help="Лимит токенов (для LLM-режима)")

    # Фильтры
    p.add_argument("--lang", help="Фильтр по языку: python, js, css, ...")
    p.add_argument("--kind", help="Фильтр по типу: function, class, import, ...")

    # Энричеры
    p.add_argument("--no-heuristics", action="store_true",
                   help="Отключить эвристический скорер")
    p.add_argument("--skip-enricher", action="append", default=[],
                   help="Пропустить конкретный энричер (можно несколько)")

    # Линкер
    p.add_argument(
        "--link",
        choices=["simple"],
        help="Включить кросс-языковой линкер: simple=имя→имя"
    )

    # Отладка
    p.add_argument("--version", action="version", version="ctxfind v2.0.0-alpha")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Показать детали парсинга")
    p.add_argument("--debug-parser", action="store_true",
                   help="Debug: показать сырые матчи парсера до обработки")
    p.add_argument("--profile", action="store_true",
                   help="Показать тайминги")

    return p

def main(argv: Optional[List[str]] = None) -> int:
    """Точка входа"""
    try:
        args = build_parser().parse_args(argv)
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130  # Standard exit code for Ctrl+C

    # Настройка логирования
    if args.debug_parser:
        level = logging.DEBUG
        # Дополнительный формат для debug-parser
        fmt = "%(name)s [%(levelname)s]: %(message)s"
    elif args.verbose:
        level = logging.DEBUG
        fmt = "%(name)s: %(message)s"
    else:
        level = logging.WARNING
        fmt = "%(message)s"
    logging.basicConfig(level=level, format=fmt)

    # Валидация аргументов
    if not args.path.exists():
        print(f"Error: Path does not exist: {args.path}", file=sys.stderr)
        return 1

    # Выбор режима
    if args.mode == "deep":
        try:
            from parsers.tree_sitter_parser import TREE_SITTER_AVAILABLE
            if not TREE_SITTER_AVAILABLE:
                print(
                    "Warning: deep mode requires tree-sitter-languages. "
                    "Install with: pip install tree-sitter==0.20.4 tree-sitter-languages==1.10.2",
                    file=sys.stderr
                )
                print("Falling back to fast mode.", file=sys.stderr)
                args.mode = "fast"
            else:
                # Проверяем, что парсер загружается
                try:
                    from tree_sitter_languages import get_parser
                    _ = get_parser("python")
                    print("AST mode: tree-sitter-languages ready", file=sys.stderr)
                except Exception as e:
                    print(
                        f"Warning: tree-sitter-languages installed but parser failed to load: {e}",
                        file=sys.stderr
                    )
                    print("Falling back to fast mode.", file=sys.stderr)
                    args.mode = "fast"
        except ImportError:
            print(
                "Warning: deep mode unavailable. Install with: pip install tree-sitter==0.20.4 tree-sitter-languages==1.10.2",
                file=sys.stderr
            )
            args.mode = "fast"

    mode = QueryMode(args.mode)

    # Фильтры
    filters = {}
    if args.lang:
        filters["lang"] = args.lang
    if args.kind:
        filters["kind"] = args.kind

    # Опции
    options = {
        "format": args.format,
        "max_lines": args.max_lines,
        "max_tokens": args.max_tokens,
    }

    # Энричеры
    skip_enrichers = list(args.skip_enricher)
    if args.no_heuristics:
        skip_enrichers.append("v1-heuristics")
    if skip_enrichers:
        options["skip_enrichers"] = skip_enrichers

    # Линкер
    if args.link:
        options["link"] = args.link

    # Запуск поиска
    orchestrator = SearchOrchestrator(mode=mode, filters=filters, options=options)
    results = orchestrator.run(query=args.query, root_path=args.path)

    if not results:
        print("No matches found.")
        return 0

    # Фильтрация по kind (пост-поиск)
    if args.kind:
        results = [r.filter_by_kind(args.kind) for r in results]
        results = [r for r in results if r.matches]

    if not results:
        print(f"No matches found for kind='{args.kind}'.")
        return 0

    # Выбор рендерера
    renderer_cls = None
    for name, cls in registry_renderers.all().items():
        if hasattr(cls, "output_formats") and args.format in cls.output_formats:
            renderer_cls = cls
            break

    if renderer_cls is None:
        print(f"Error: No renderer found for format '{args.format}'", file=sys.stderr)
        print(f"Available renderers: {registry_renderers.list()}", file=sys.stderr)
        return 1

    renderer = renderer_cls()

    # Подготовка hints
    hints = prepare_render_hints(results, options)

    # Рендеринг
    if hasattr(renderer, "render_batch") and len(hints) > 1:
        outputs = renderer.render_batch(results, hints, options=options)
    else:
        outputs = []
        for result, hint in zip(results, hints):
            output = renderer.render(result, hint, options=options)
            outputs.append(output)

    # Вывод
    for output in outputs:
        if output.strip():
            print(output)

    return 0

# UTF-8 fix for Windows
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

if __name__ == "__main__":
    sys.exit(main())
