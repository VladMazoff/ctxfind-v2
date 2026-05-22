"""
ctxfind-v2: Parser Base Helpers

Стратегия:
- Не обязательный базовый класс (предпочитаем композицию)
- Только утилиты, которые реально переиспользуются
- Никакой бизнес-логики
"""

from typing import List, Dict, Any, Optional
import re
import hashlib
from core.models import CodeNode, Span, ParseResult, Ref


class ParserUtils:
    """Статические утилиты для парсеров"""

    @staticmethod
    def make_node_id(file_path: str, span: Span, kind: str, name: str) -> str:
        """Сгенерировать уникальный ID для узла"""
        # Используем хеш, если путь слишком длинный или содержит спецсимволы
        raw = f"{file_path}:{span.start_line}:{kind}:{name}"
        # Для читаемости — обрезаем путь, если он очень длинный
        if len(raw) > 200:
            # Хешируем путь, оставляем имя файла
            path_hash = hashlib.md5(file_path.encode()).hexdigest()[:8]
            basename = file_path.split("/")[-1].split("\\")[-1]
            raw = f"{basename}:{path_hash}:{span.start_line}:{kind}:{name}"
        return raw

    @staticmethod
    def extract_context_around(
        content: str,
        span: Span,
        context_lines_before: int = 0,
        context_lines_after: int = 0
    ) -> str:
        """
        Вырезать фрагмент кода вокруг позиции.
        Используется только в fallback-парсерах!
        Полноценные парсеры должны отдавать семантический контекст.
        """
        lines = content.splitlines()
        start = max(0, span.start_line - context_lines_before)
        end = min(len(lines), span.end_line + context_lines_after + 1)
        return "\n".join(lines[start:end])

    @staticmethod
    def regex_matches(
        content: str,
        pattern: str,
        query: str,
        flags: int = re.MULTILINE
    ) -> List[Dict[str, Any]]:
        """
        Найти вхождения query по regex-паттерну.
        Возвращает: {match: str, span: Span, group_dict: dict}
        """
        # Подставляем query в паттерн
        formatted_pattern = pattern.replace("{query}", re.escape(query))
        compiled = re.compile(formatted_pattern, flags)

        results = []
        for m in compiled.finditer(content):
            # Вычисляем line/col из позиции в строке
            start_pos = m.start()
            end_pos = m.end()

            # Подсчёт строк и колонок
            lines_before = content[:start_pos].count("\n")
            last_newline = content[:start_pos].rfind("\n")
            start_col = start_pos - last_newline - 1 if last_newline >= 0 else start_pos

            lines_after = content[:end_pos].count("\n")
            last_newline_end = content[:end_pos].rfind("\n")
            end_col = end_pos - last_newline_end - 1 if last_newline_end >= 0 else end_pos

            span = Span(
                start_line=lines_before,
                start_col=start_col,
                end_line=lines_after,
                end_col=end_col
            )

            results.append({
                "match": m.group(),
                "span": span,
                "group_dict": m.groupdict(),
            })

        return results

    @staticmethod
    def guess_kind_by_name(name: str, context: str) -> str:
        """
        Эвристика: угадать kind узла по имени и контексту.
        Используется в fallback-парсерах для заполнения meta.
        """
        # PascalCase → скорее всего class
        if name and name[0].isupper() and name.isidentifier():
            # Проверяем контекст на наличие "class"
            if re.search(rf"class\s+{re.escape(name)}\b", context):
                return "class"
            return "class"  # PascalCase по умолчанию — class

        # snake_case с глаголом → function
        if re.search(rf"def\s+{re.escape(name)}\b", context):
            return "function"

        # import
        if re.search(rf"(?:from|import)\s+\S*\b{re.escape(name)}\b", context):
            return "import"

        # CSS class
        if re.search(rf"\.{re.escape(name)}\b", context):
            return "css_class"

        # Переменная по умолчанию
        return "variable"


class FallbackParserMixin:
    """
    Миксин для быстрого regex-based поиска.

    Используется в regex_fallback.py для совместимости с v1.
    Не использовать в полноценных AST-парсерах!
    """

    def quick_search_template(
        self,
        content: str,
        query: str,
        patterns: Dict[str, str],  # kind -> regex pattern с {query}
        file_path: str = "",
        language: str = "unknown"
    ) -> List[CodeNode]:
        """
        Шаблон для быстрого поиска по регуляркам.

        Пример patterns:
        {
            "function": r"def\s+{query}\s*\(",
            "class": r"class\s+{query}(\s*[:\(])",
            "import": r"(?:from|import)\s+\S*\b{query}\b"
        }
        """
        results = []

        for kind, pattern in patterns.items():
            matches = ParserUtils.regex_matches(content, pattern, query)

            for match_info in matches:
                span = match_info["span"]
                snippet = ParserUtils.extract_context_around(
                    content, span, context_lines_before=2, context_lines_after=5
                )

                node = CodeNode(
                    id=ParserUtils.make_node_id(file_path, span, kind, query),
                    name=query,
                    kind=kind,
                    language=language,
                    file_path=file_path,
                    span=span,
                    context_code=snippet,
                    meta={
                        "match_type": "regex_fallback",
                        "pattern": pattern,
                        "confidence": 0.5,
                    }
                )
                results.append(node)

        return results
