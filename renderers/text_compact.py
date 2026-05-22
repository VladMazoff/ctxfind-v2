"""
ctxfind-v2: Compact Text Renderer

Стратегия:
- Человекочитаемый вывод
- Обрезка по лимитам
- Маркеры v1: << def, >> use, >< mod
- Формат: >> def process_user(...) # [file:line]
"""

from typing import List, Dict, Any, Optional
from core.models import ParseResult, RenderHint, CodeNode, Span
from core.registry import register_renderer
from renderers.base import BaseRendererImpl

class TextCompactRenderer(BaseRendererImpl):
    """
    Компактный текстовый рендерер.

    Пример вывода:
    >> def process_user(data: Dict) -> User: # [services/user_service.py:45]
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

        # ИСПРАВЛЕНИЕ: берём сигнатуру узла — первые строки, содержащие имя узла
        # А не просто первую строку context_code (которая может быть родителем)
        signature = self._extract_signature(node)

        # Обрезаем слишком длинную сигнатуру
        max_sig_len = 80
        if len(signature) > max_sig_len:
            signature = signature[:max_sig_len] + " ..."

        header = f"{role_marker} {signature} # [{node.file_path}:{node.span.start_line + 1}]"
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
            lines.append(f" # {' | '.join(meta_parts)}")

        # Связи (references)
        if node.references and hint.show_imports:
            refs = node.references[:3]  # максимум 3
            ref_strs = []
            for ref in refs:
                loc = f"{ref.target_file or ref.source_file}"
                ref_strs.append(f"{ref.target_name} ({loc})")
            if ref_strs:
                lines.append(f" # uses: {', '.join(ref_strs)}")

        # Показать тело, если запрошено
        if hint.show_body and node.context_code:
            body_lines = node.context_code.splitlines()
            # Пропускаем строки до сигнатуры (контекст перед узлом)
            sig_lines = signature.splitlines()
            skip = 0
            for i, line in enumerate(body_lines):
                if node.name in line:
                    skip = i + len(sig_lines)
                    break

            if skip < len(body_lines):
                body = "\n".join(body_lines[skip:])
                # Обрезаем по лимитам
                body = self._truncate_code(body, hint.max_lines or 20, hint.truncate_strategy)
                if body.strip():
                    lines.append(body)
        else:
            # Показываем hint, что тело скрыто
            if node.kind in ("function", "method", "class"):
                lines.append(" # [body hidden: use --mode full to expand]")

        # Пустая строка-разделитель
        lines.append("")

        return "\n".join(lines)

    def _extract_signature(self, node: CodeNode) -> str:
        """
        Извлечь сигнатуру узла из context_code.

        ИСПРАВЛЕНИЕ: ищем строки, содержащие имя узла, и берём их как сигнатуру.
        Для метода/функции — это строка с def/class/func.
        """
        ctx_lines = node.context_code.splitlines()
        if not ctx_lines:
            return node.name

        # Ищем первую строку, содержащую имя узла
        for i, line in enumerate(ctx_lines):
            if node.name in line:
                # Берём эту строку и следующие (для многострочных сигнатур)
                sig_lines = [line.strip()]
                # Проверяем следующие строки — если они продолжают сигнатуру (отступ меньше или скобки)
                for j in range(i + 1, min(i + 3, len(ctx_lines))):
                    next_line = ctx_lines[j].strip()
                    # Если следующая строка — продолжение сигнатуры (скобки не закрыты)
                    if next_line and not next_line.startswith("#"):
                        # Проверяем баланс скобок
                        open_count = sum(sig_lines[-1].count(c) for c in "({[")
                        close_count = sum(sig_lines[-1].count(c) for c in ")}]")
                        if open_count > close_count:
                            sig_lines.append(next_line)
                        else:
                            break
                    else:
                        break

                return " ".join(sig_lines)

        # Fallback: первая непустая строка
        for line in ctx_lines:
            stripped = line.strip()
            if stripped:
                return stripped

        return node.name

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
