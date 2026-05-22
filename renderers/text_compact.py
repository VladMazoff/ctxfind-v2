
"""
ctxfind-v2: Compact Text Renderer

Стратегия:
- Человекочитаемый вывод
- Обрезка по лимитам
- Маркеры v1: << def, >> use, >< mod
- Формат: >> def process_user(...)  # [file:line]
"""

from typing import List, Dict, Any, Optional
from core.models import ParseResult, RenderHint, CodeNode, Span
from core.registry import register_renderer
from renderers.base import BaseRendererImpl


class TextCompactRenderer(BaseRendererImpl):
    """
    Компактный текстовый рендерер.

    Пример вывода:
    >> def process_user(data: Dict) -> User:  # [services/user_service.py:45]
       # uses: User (models.py:12)
       # complexity: 12 | has tests: ✓
       # [body hidden: use --mode full to expand]
    """

    name = "text-compact"
    output_formats = ["compact", "text"]

    def _render_node(
        self,
        node: CodeNode,
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> str:
        """Отрендерить один узел в компактном формате"""
        lines = []

        # Маркер роли из v1
        role = node.meta.get("v1_role", ">> use")
        role_marker = role if role else ">>"

        # Первая строка: роль + сигнатура/имя + позиция
        first_line = node.context_code.splitlines()[0] if node.context_code else node.name
        first_line = first_line.strip()

        # Если первая строка не содержит имя узла — добавляем его
        if node.name not in first_line:
            first_line = f"{node.name}: {first_line}"

        # Обрезаем слишком длинную первую строку
        max_sig_len = 80
        if len(first_line) > max_sig_len:
            first_line = first_line[:max_sig_len] + " ..."

        header = f"{role_marker} {first_line}  # [{node.file_path}:{node.span.start_line + 1}]"
        lines.append(header)

        # Мета-информация
        meta_parts = []

        # Язык и kind
        meta_parts.append(f"{node.language}/{node.kind}")

        # Сложность
        complexity = node.meta.get("complexity")
        if complexity is not None:
            meta_parts.append(f"complexity:{complexity}")

        # Экспорт
        if node.meta.get("is_exported"):
            meta_parts.append("exported")

        # Тесты
        if node.meta.get("has_tests"):
            meta_parts.append("tests:✓")

        # Скоринг
        score = node.meta.get("v1_node_score")
        if score is not None:
            meta_parts.append(f"score:{score:.2f}")

        if meta_parts:
            lines.append(f"   # {' | '.join(meta_parts)}")

        # Связи (references)
        if node.references and hint.show_imports:
            refs = node.references[:3]  # максимум 3
            ref_strs = []
            for ref in refs:
                loc = f"{ref.target_file or ref.source_file}"
                ref_strs.append(f"{ref.target_name} ({loc})")
            if ref_strs:
                lines.append(f"   # uses: {', '.join(ref_strs)}")

        # Показать тело, если запрошено
        if hint.show_body and node.context_code:
            body_lines = node.context_code.splitlines()
            # Пропускаем первую строку (уже показана как сигнатура)
            if len(body_lines) > 1:
                body = "\n".join(body_lines[1:])
                # Обрезаем по лимитам
                body = self._truncate_code(body, hint.max_lines or 20, hint.truncate_strategy)
                lines.append(body)
        else:
            # Показываем hint, что тело скрыто
            if node.kind in ("function", "method", "class"):
                lines.append("   # [body hidden: use --mode full to expand]")

        # Пустая строка-разделитель
        lines.append("")

        return "\n".join(lines)

    def _format_output(
        self,
        rendered_nodes: List[str],
        result: ParseResult,
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> str:
        """Финальное форматирование вывода"""
        if not rendered_nodes:
            return ""

        parts = []

        # Заголовок файла (если несколько узлов из одного файла)
        if len(rendered_nodes) > 1:
            parts.append(f"# {result.file_path}")
            parts.append("")

        parts.extend(rendered_nodes)

        # Итоговая статистика
        total = len(result.matches)
        if total > 0:
            relevance = result.heuristics.get("v1_relevance", 0.0)
            parts.append(f"# ── {total} match(es) | relevance: {relevance:.2f} ──")

        return "\n".join(parts)


# Регистрация
register_renderer("text-compact", TextCompactRenderer)
