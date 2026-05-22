"""
ctxfind-v2: Compact Text Renderer — Final Format

Формат вывода:
    {role} {kind} {signature} # [{path}:{line}] | lang:{lang} | rel:{score}

Примеры:
    << def class UserService: # [.\\test_project\\user_service.py:15] | lang:py | rel:0.83
    >< mod method addUser(userData) { ... } # [.\\test_project\\user_manager.js:10] | lang:js | rel:0.80
    >> use function find_user(self, email) -> Optional[User]: # [.\\test_project\\user_service.py:27] | lang:py | rel:0.80
"""

from typing import List, Dict, Any, Optional
import os
from core.models import ParseResult, RenderHint, CodeNode, Span
from core.registry import register_renderer
from renderers.base import BaseRendererImpl

class TextCompactRenderer(BaseRendererImpl):
    """
    Компактный текстовый рендерер — финальный формат.
    """

    name = "text-compact"
    output_formats = ["compact", "text"]

    def _render_node(
        self,
        node: CodeNode,
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> str:
        """Отрендерить один узел в финальном формате."""

        # Роль
        role = node.meta.get("v1_role", ">> use")

        # Kind
        kind = node.kind

        # Сигнатура: сжатый текст узла (первая строка, обрезанная)
        signature = self._compact_signature(node)

        # Путь: упрощённый (только имя файла + 1-2 уровня директории)
        short_path = self._shorten_path(node.file_path)

        # Язык: сокращение
        lang_short = self._lang_short(node.language)

        # Релевантность
        rel = node.meta.get("v1_node_score", 0.0)

        # Собираем строку
        parts = [
            f"{role} {kind} {signature}",
            f"# [{short_path}:{node.span.start_line + 1}]",
            f"| lang:{lang_short}",
            f"| rel:{rel:.2f}",
        ]

        return " ".join(parts)

    def _compact_signature(self, node: CodeNode) -> str:
        """
        Сжать сигнатуру узла до одной строки.

        - Берём текст узла (context_code)
        - Заменяем переносы строк на пробелы
        - Обрезаем до 80 символов
        - Добавляем ... если обрезано
        """
        text = node.context_code.strip()

        # Убираем лишние пробелы и переносы
        text = " ".join(text.split())

        # Обрезаем
        max_len = 80
        if len(text) > max_len:
            # Ищем последний пробел перед лимитом
            cutoff = text.rfind(" ", 0, max_len - 4)
            if cutoff > 20:
                text = text[:cutoff] + " ..."
            else:
                text = text[:max_len - 4] + " ..."

        return text

    def _shorten_path(self, file_path: str) -> str:
        """
        Укоротить путь: оставить только последние 2 компонента.
        """
        # Нормализуем слеши
        normalized = file_path.replace("/", "\\")
        parts = normalized.split("\\")

        # Берём последние 2 части
        if len(parts) >= 2:
            return ".\\" + "\\".join(parts[-2:])
        return normalized

    def _lang_short(self, language: str) -> str:
        """Сокращение языка."""
        mapping = {
            "python": "py",
            "javascript": "js",
            "typescript": "ts",
            "css": "css",
            "html": "html",
            "unknown": "?",
        }
        return mapping.get(language, language[:2])

    def _format_output(
        self,
        rendered_nodes: List[str],
        result: ParseResult,
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> str:
        """Финальное форматирование вывода."""
        if not rendered_nodes:
            return ""

        parts = []
        parts.extend(rendered_nodes)

        # Итоговая статистика
        total = len(result.matches)
        if total > 0:
            relevance = result.heuristics.get("v1_relevance", 0.0)
            parts.append(f"# ── {total} match(es) | relevance: {relevance:.2f} ──")

        return "\n".join(parts)


# Регистрация
register_renderer("text-compact", TextCompactRenderer)
