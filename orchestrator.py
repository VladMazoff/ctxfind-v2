"""
ctxfind-v2: Search Orchestrator

Архитектурные принципы:
1. Fallback-цепочка: парсеры пробуются по приоритету. При ошибке → следующий.
2. Fault-tolerance: сбой одного файла/энричера не останавливает поиск.
3. Lazy I/O: файлы читаются только когда выбран парсер.
4. Явное логирование: все исключения ловятся, логируются, превращаются в warnings.
"""

import logging
import os
import stat
from pathlib import Path
from typing import List, Dict, Any, Optional, Type

from core.models import ParseResult, QueryMode, CodeNode, RenderHint
from core.registry import parsers, enrichers
from core.interfaces import BaseParser, BaseEnricher
from config import get_config

log = logging.getLogger(__name__)


class SearchOrchestrator:
    """
    Координатор пайплайна: discovery → parse → enrich → aggregate.
    Не содержит бизнес-логики поиска, только оркестрацию и обработку ошибок.
    """

    def __init__(
        self,
        mode: QueryMode,
        filters: Optional[Dict[str, Any]] = None,
        options: Optional[Dict[str, Any]] = None
    ):
        self.mode = mode
        self.filters = filters or {}
        self.options = options or {}
        self._fallback_parser_name = self.options.get(
            "fallback_parser", 
            get_config().fallback_parser
        )
        self.link_names = self.options.get("link", None)  # None | "simple"

        # Логирование режима при первом запуске
        try:
            from parsers.tree_sitter_parser import TREE_SITTER_AVAILABLE
            ast_status = "ready" if TREE_SITTER_AVAILABLE else "optional (install ctxfind[ast])"
        except ImportError:
            ast_status = "optional (install ctxfind[ast])"

        log.info(f"ctxfind v2 alpha — fast mode ready, ast mode: {ast_status}")

    def run(self, query: str, root_path: Path) -> List[ParseResult]:
        """
        Точка входа: запускает поиск по директории/файлу.
        Возвращает отсортированные ParseResult (по relevance desc).
        """
        import time
        t_start = time.time()

        # 1. Обнаружение файлов (лениво, с фильтрами)
        t0 = time.time()
        target_files = self._discover_files(root_path)
        t_discovery = time.time() - t0
        log.debug(f"Discovery: {len(target_files)} files in {t_discovery:.3f}s")
        if not target_files:
            log.warning("No files matched filters in %s", root_path)
            return []

        results: List[ParseResult] = []

        # 2. Последовательная обработка файлов
        t0 = time.time()
        for file_path in target_files:
            try:
                result = self._process_file(query, file_path)
                results.append(result)
            except Exception as e:
                # Файл полностью недоступен → пропускаем с логом
                log.debug(f"Skipped {file_path} due to unrecoverable error: {e}", exc_info=True)
                # Можно добавить пустой результат с warning, если нужно сохранить trace
                results.append(ParseResult(
                    query=query,
                    file_path=str(file_path),
                    parser_name="none",
                    warnings=[f"File processing failed: {str(e)}"]
                ))

        # 3. Кросс-языковой линкер (опционально)
        if self.link_names == "simple":
            try:
                from enrichers.cross_name_linker import CrossNameLinker
                linker = CrossNameLinker(options=self.options)
                results = linker.enrich(results, options=self.options)
            except Exception as e:
                log.warning(f"Cross-name linker failed: {e}")
                # Добавляем warning к каждому результату
                for r in results:
                    r.warnings.append(f"Linker error: {str(e)}")

        # 4. Глобальная сортировка по релевантности
        results.sort(
            key=lambda r: r.heuristics.get("v1_relevance", 0.0),
            reverse=True
        )

        t_total = time.time() - t_start
        t_parse = time.time() - t0
        log.debug(f"Parse+enrich: {t_parse:.3f}s for {len(target_files)} files")
        log.debug(f"Total: {t_total:.3f}s, {len(results)} results, {sum(len(r.matches) for r in results)} matches")

        return results

    # ─── Discovery ─────────────────────────────────────────────────────────

    def _discover_files(self, root_path: Path) -> List[Path]:
        """
        Обход FS с учётом .gitignore, фильтров по языку/размеру.

        TODO:
        - Использовать pathspec для .gitignore
        - Пропускать binary/symlinks
        - Применять self.filters (lang, max_size, exclude_dirs)
        - Возвращать отсортированный список (для стабильности вывода)
        """
        config = get_config()
        exclude_dirs = set(config.exclude_dirs)
        if self.filters.get("exclude_dirs"):
            exclude_dirs.update(self.filters["exclude_dirs"])

        max_size = self.filters.get("max_size_mb", config.max_file_size_mb) * 1024 * 1024
        lang_filter = self.filters.get("lang")

        # Расширения по языку
        lang_extensions = {
            "python": [".py", ".pyi"],
            "javascript": [".js", ".jsx", ".mjs"],
            "typescript": [".ts", ".tsx"],
            "css": [".css", ".scss", ".sass", ".less"],
            "html": [".html", ".htm", ".vue", ".svelte"],
        }

        target_exts = None
        if lang_filter:
            target_exts = set(lang_extensions.get(lang_filter, []))

        target_files = []

        if root_path.is_file():
            target_files = [root_path]
        elif root_path.is_dir():
            for path in root_path.rglob("*"):
                if not path.is_file():
                    continue

                # Пропускаем директории из exclude
                if any(part in exclude_dirs for part in path.parts):
                    continue

                # Пропускаем symlinks
                if path.is_symlink():
                    continue

                # Пропускаем бинарные файлы (по null bytes)
                try:
                    if self._is_binary(path):
                        continue
                except OSError:
                    continue

                # Фильтр по размеру
                try:
                    if path.stat().st_size > max_size:
                        continue
                except OSError:
                    continue

                # Фильтр по расширению
                if target_exts is not None:
                    if path.suffix.lower() not in target_exts:
                        continue

                target_files.append(path)

        # Стабильная сортировка
        target_files.sort(key=lambda p: str(p))
        return target_files

    def _is_binary(self, path: Path, sample_size: int = 8192) -> bool:
        """Проверка на бинарность файла (по null bytes)"""
        try:
            with open(path, "rb") as f:
                chunk = f.read(sample_size)
                return b"\x00" in chunk
        except Exception:
            return True  # Если не читается — считаем бинарным

    # ─── File Processing ───────────────────────────────────────────────────

    def _process_file(self, query: str, file_path: Path) -> ParseResult:
        """
        Полный цикл для одного файла: read → parse(fallback) → enrich.
        """
        # 1. Чтение контента (lazy, с обработкой encoding)
        try:
            content = self._safe_read(file_path)
        except Exception as e:
            return ParseResult(
                query=query,
                file_path=str(file_path),
                parser_name="none",
                warnings=[f"Read error: {str(e)}"]
            )

        # 2. Парсинг с fallback-цепочкой
        result = self._parse_with_fallback(str(file_path), content, query)

        # 3. Обогащение (изолированно)
        result = self._apply_enrichers(result)

        return result

    def _safe_read(self, file_path: Path) -> str:
        """Чтение файла с обработкой encoding/decode errors"""
        # Стратегия: utf-8 first, fallback latin-1, errors='replace'
        encodings = ["utf-8", "latin-1", "cp1252"]

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding, errors="replace") as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
            except Exception:
                raise

        # Если всё упало — читаем как latin-1 (он никогда не падает)
        with open(file_path, "r", encoding="latin-1", errors="replace") as f:
            return f.read()

    # ─── Fallback Chain ────────────────────────────────────────────────────

    def _parse_with_fallback(self, file_path: str, content: str, query: str) -> ParseResult:
        """
        Fallback-цепочка парсеров.
        """
        candidates = self._get_candidate_parsers(file_path, content)

        log.debug(f"Parser candidates for {file_path}: {[c.__name__ for c in candidates]}")

        if not candidates:
            log.warning(f"No parser candidates for {file_path}, using fallback")
            return self._run_fallback_parser(file_path, content, query, "no_suitable_parser")

        last_error = None
        for parser_cls in candidates:
            parser_name = getattr(parser_cls, 'name', parser_cls.__name__)
            try:
                parser = parser_cls()
                result = parser.parse(
                    file_path, content, query, 
                    mode=self.mode, options=self.options
                )

                log.debug(f"Parser '{parser_name}' returned {len(result.matches)} matches, warnings: {result.warnings}")

                # Если парсер вернул матчи или warnings без фатальных ошибок → успех
                if result.matches or not any("fatal" in w.lower() for w in result.warnings):
                    result.parser_name = getattr(parser, "name", parser_cls.__name__)
                    log.info(f"Using parser '{parser_name}' for {file_path} ({len(result.matches)} matches)")
                    return result
                else:
                    log.debug(f"Parser '{parser_name}' returned no matches, trying next")

            except Exception as e:
                last_error = e
                log.warning(f"Parser '{parser_name}' failed on {file_path}: {e}")
                continue

        # Все кандидаты упали → fallback
        log.warning(f"All parsers failed for {file_path}, using fallback. Last error: {last_error}")
        return self._run_fallback_parser(
            file_path, content, query, 
            f"fallback_after_error: {last_error}"
        )

    def _get_candidate_parsers(self, file_path: str, content: str) -> List[Type]:
        """Фильтрация и сортировка парсеров по priority + supports()"""
        all_parsers = parsers.select_best(file_path, content)

        # Для mode=FAST предпочитаем парсеры с quick_match
        if self.mode == QueryMode.FAST:
            # Сортируем: сначала те, у кого есть quick_match
            has_quick = []
            no_quick = []
            for p in all_parsers:
                if hasattr(p, "quick_match"):
                    has_quick.append(p)
                else:
                    no_quick.append(p)
            all_parsers = has_quick + no_quick

        return all_parsers

    def _run_fallback_parser(self, file_path: str, content: str, query: str, reason: str) -> ParseResult:
        """Принудительный запуск fallback-парсера (regex/simple)"""
        fallback_cls = parsers.get(self._fallback_parser_name)

        if fallback_cls is None:
            # Fallback не найден — возвращаем пустой результат
            return ParseResult(
                query=query,
                file_path=file_path,
                parser_name="none",
                warnings=[f"No fallback parser available. Reason: {reason}"]
            )

        try:
            fallback = fallback_cls()
            result = fallback.parse(file_path, content, query, mode=self.mode, options=self.options)
            result.parser_name = getattr(fallback, "name", "fallback")
            result.warnings.append(f"Used fallback parser. Reason: {reason}")
            return result
        except Exception as e:
            return ParseResult(
                query=query,
                file_path=file_path,
                parser_name="none",
                warnings=[f"Fallback parser failed: {str(e)}. Original reason: {reason}"]
            )

    # ─── Enricher Pipeline ─────────────────────────────────────────────────

    def _apply_enrichers(self, result: ParseResult) -> ParseResult:
        """
        Последовательный запуск энричеров с изоляцией ошибок.
        Сбой одного энричера НЕ прерывает цепочку.
        """
        active_enrichers = self._get_active_enrichers()

        for enricher_cls in active_enrichers:
            try:
                enricher = enricher_cls()
                result = enricher.enrich(result, options=self.options)
            except Exception as e:
                log.warning(f"Enricher {enricher_cls.__name__} failed, skipping: {e}")
                result.warnings.append(f"Enricher error ({enricher_cls.__name__}): {str(e)}")
                # Продолжаем с текущим result
                continue

        return result

    def _get_active_enrichers(self) -> List[Type]:
        """Получить список включённых энричеров, отсортированных по runs_after"""
        skip = set(self.options.get("skip_enrichers", []))

        # Собираем все включённые по умолчанию
        candidates = []
        for name, cls in enrichers.all().items():
            if name in skip:
                continue
            enabled = getattr(cls, "enabled_by_default", True)
            if enabled:
                candidates.append(cls)

        # Простая топологическая сортировка по runs_after
        # Алгоритм: собираем граф зависимостей, топсорт
        name_to_cls = {getattr(c, "name", c.__name__): c for c in candidates}

        # Построение графа
        graph = {c: set() for c in candidates}
        for cls in candidates:
            runs_after = getattr(cls, "runs_after", [])
            for dep_name in runs_after:
                dep_cls = name_to_cls.get(dep_name)
                if dep_cls and dep_cls in graph:
                    graph[cls].add(dep_cls)

        # Топологическая сортировка (простой DFS)
        visited = set()
        temp_mark = set()
        order = []

        def visit(node):
            if node in temp_mark:
                raise ValueError(f"Cyclic dependency in enrichers: {getattr(node, 'name', node.__name__)}")
            if node in visited:
                return
            temp_mark.add(node)
            for dep in graph[node]:
                visit(dep)
            temp_mark.remove(node)
            visited.add(node)
            order.append(node)

        for node in list(graph.keys()):
            if node not in visited:
                visit(node)

        return order


# ─── Утилиты для подготовки RenderHint ───────────────────────────────────

def prepare_render_hints(
    results: List[ParseResult],
    user_options: Dict[str, Any]
) -> List[RenderHint]:
    """
    Сгенерировать RenderHint для каждого результата.

    Логика:
    - Взять дефолтные значения из профиля (--format)
    - Переопределить явными аргументами (--max-lines, etc.)
    - Для каждого узла: парсер может добавить подсказки в node.meta["render_hints"]
    """
    config = get_config()

    hints = []
    for result in results:
        for node in result.matches:
            # Базовые значения из конфига
            max_lines = user_options.get("max_lines", config.default_max_lines)
            max_tokens = user_options.get("max_tokens", config.default_max_tokens)
            output_format = user_options.get("format", config.default_format)

            # Переопределение из meta узла (если парсер дал подсказки)
            node_hints = node.meta.get("render_hints", {})

            hint = RenderHint(
                node=node,
                max_lines=max_lines,
                max_tokens=max_tokens,
                output_format=output_format,
                show_signature=node_hints.get("show_signature", True),
                show_body=node_hints.get("show_body", False),
                show_imports=node_hints.get("show_imports", True),
                show_related_names=node_hints.get("show_related", []),
                truncate_strategy=user_options.get("truncate_strategy", "smart"),
                llm_include_meta=user_options.get("llm_include_meta", True),
            )
            hints.append(hint)

    return hints
