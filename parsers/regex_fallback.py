
"""
ctxfind-v2: Regex Fallback Parser

Стратегия:
- Наследник логики v1, для скорости и простых случаев
- Работает для всех текстовых файлов (supports() → True для известных расширений)
- Использует FallbackParserMixin для шаблонного поиска
- Заполняет meta["v1_role"] через guess_from_regex()
"""

import re
from typing import Dict, Any, List, Optional
from pathlib import Path

from core.models import CodeNode, Span, ParseResult, QueryMode
from core.interfaces import BaseParser
from core.registry import register_parser
from parsers.base import ParserUtils, FallbackParserMixin


class RegexFallbackParser(FallbackParserMixin):
    """
    Fallback-парсер на регулярках.

    Покрывает: Python, JavaScript/TypeScript, CSS, HTML.
    Быстрый, не требует зависимостей, работает даже на битом коде.
    """

    name = "regex-fallback"
    priority = 10  # Низкий: пробуем последним (fallback)
    supported_extensions = [
        ".py", ".pyi",
        ".js", ".jsx", ".mjs",
        ".ts", ".tsx",
        ".css", ".scss", ".sass", ".less",
        ".html", ".htm", ".vue", ".svelte",
        ".json", ".yaml", ".yml", ".toml",
    ]

    # Паттерны по языкам: kind → regex с {query}
    _patterns: Dict[str, Dict[str, str]] = {
        "python": {
            "function": r"^\s*def\s+{query}\b",
            "class": r"^\s*class\s+{query}\b",
            "method": r"^\s*def\s+{query}\b",  # отличие от function — в meta
            "import": r"(?:from|import)\s+\S*\b{query}\b",
            "variable": r"\b{query}\b\s*=",
        },
        "javascript": {
            "function": r"(?:function\s+{query}|const\s+{query}\s*=\s*(?:async\s*)?\(|let\s+{query}\s*=\s*(?:async\s*)?\(|var\s+{query}\s*=\s*(?:async\s*)?\()",
            "class": r"class\s+{query}\b",
            "method": r"(?:async\s+)?{query}\s*\([^)]*\)\s*\{",
            "import": r"(?:import|require)\s*\(?[^)]*\b{query}\b",
            "variable": r"(?:const|let|var)\s+{query}\b",
            "arrow_function": r"(?:const|let|var)\s+{query}\s*=\s*(?:async\s*)?\(",
        },
        "typescript": {
            "function": r"(?:function\s+{query}|const\s+{query}\s*=\s*(?:async\s*)?\(|let\s+{query}\s*=\s*(?:async\s*)?\(|var\s+{query}\s*=\s*(?:async\s*)?\()",
            "class": r"class\s+{query}\b",
            "interface": r"interface\s+{query}\b",
            "type": r"type\s+{query}\b",
            "method": r"(?:async\s+)?{query}\s*\([^)]*\)\s*[:\{]",
            "import": r"(?:import|require)\s*\(?[^)]*\b{query}\b",
            "variable": r"(?:const|let|var)\s+{query}\b",
        },
        "css": {
            "css_selector": r"[.#]\b{query}\b",
            "css_property": r"\b{query}\b\s*:",
        },
        "html": {
            "html_tag": r"<{query}\b",
            "html_class": r'class=["\'][^"\']*\b{query}\b',
            "html_id": r'id=["\'][^"\']*\b{query}\b',
        },
    }

    def supports(self, file_path: str, content_snippet: str) -> bool:
        """Поддерживаем все файлы с известными расширениями"""
        ext = Path(file_path).suffix.lower()
        return ext in self.supported_extensions

    def parse(
        self,
        file_path: str,
        content: str,
        query: str,
        mode: QueryMode = QueryMode.AUTO,
        options: Optional[Dict[str, Any]] = None
    ) -> ParseResult:
        """
        Основной метод: regex-поиск query в коде.
        """
        result = ParseResult(
            query=query,
            file_path=file_path,
            parser_name=self.name
        )

        # Определяем язык по расширению
        language = self._detect_language(file_path)
        patterns = self._patterns.get(language, self._patterns.get("python", {}))

        # Ищем по всем паттернам
        all_nodes = []
        for kind, pattern in patterns.items():
            try:
                nodes = self.quick_search_template(
                    content=content,
                    query=query,
                    patterns={kind: pattern},
                    file_path=file_path,
                    language=language
                )
                # Добавляем v1_role для каждого узла
                for node in nodes:
                    role = self._guess_role(node, content)
                    # Создаём новый узел с обновлённым meta (immutable)
                    updated_node = node.with_meta(
                        v1_role=role,
                        match_type="regex_fallback",
                        confidence=0.5,
                    )
                    all_nodes.append(updated_node)
            except re.error:
                # Невалидный regex — пропускаем паттерн
                result.warnings.append(f"Invalid regex pattern for {kind}: {pattern}")
                continue

        # Убираем дубликаты по span
        seen = set()
        unique_nodes = []
        for node in all_nodes:
            key = (node.span.start_line, node.span.start_col, node.kind)
            if key not in seen:
                seen.add(key)
                unique_nodes.append(node)

        result.matches = unique_nodes

        # Базовые эвристики
        if result.matches:
            result.heuristics["parser_confidence"] = 0.5
            result.heuristics["match_count"] = float(len(result.matches))

        return result

    def quick_match(self, content: str, query: str) -> List[Dict[str, Any]]:
        """
        Быстрый поиск для режима FAST.
        Возвращает простые матчи: {line, col, snippet, confidence}
        """
        results = []
        # Простой текстовый поиск
        idx = 0
        while True:
            idx = content.find(query, idx)
            if idx == -1:
                break

            # Подсчёт строки и колонки
            lines_before = content[:idx].count("\n")
            last_newline = content[:idx].rfind("\n")
            col = idx - last_newline - 1 if last_newline >= 0 else idx

            # Контекст вокруг
            start_ctx = max(0, idx - 50)
            end_ctx = min(len(content), idx + len(query) + 50)
            snippet = content[start_ctx:end_ctx]

            results.append({
                "line": lines_before,
                "col": col,
                "snippet": snippet,
                "confidence": 0.3,
            })
            idx += len(query)

        return results

    # ─── Внутренняя логика ────────────────────────────────────────────────

    def _detect_language(self, file_path: str) -> str:
        """Определить язык по расширению"""
        ext = Path(file_path).suffix.lower()
        mapping = {
            ".py": "python", ".pyi": "python",
            ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
            ".ts": "typescript", ".tsx": "typescript",
            ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
            ".html": "html", ".htm": "html", ".vue": "html", ".svelte": "html",
        }
        return mapping.get(ext, "python")

    def _guess_role(self, node: CodeNode, content: str) -> str:
        """
        Угадать семантическую роль из v1:
        - "<< def" : определение
        - ">> use" : использование
        - ">< mod" : модификатор/переопределение
        """
        kind = node.kind

        # Определения
        if kind in ("function", "class", "method", "interface", "type", "variable", "css_selector"):
            return "<< def"

        # Использования
        if kind in ("import",):
            return ">> use"

        # По умолчанию — использование
        return ">> use"


# Регистрация
register_parser("regex-fallback", RegexFallbackParser)
