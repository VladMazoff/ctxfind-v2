"""
ctxfind-v2: Renderer Base Class

Стратегия:
- Общая логика обрезки/форматирования вынесена сюда
- Конкретные рендереры наследуют и переопределяют только детали
- Никакого UI-кода в парсерах или ядре
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from core.models import ParseResult, RenderHint, CodeNode


class BaseRendererImpl(ABC):
    """
    Базовая реализация для рендереров.

    Наследуйте и реализуйте:
    - _render_node() — как отрендерить один узел
    - _format_output() — финальное форматирование (text/json/markdown)
    """

    name: str = "base"
    output_formats: List[str] = []

    def can_render(self, format: str) -> bool:
        return format in self.output_formats

    def render(
        self,
        result: ParseResult,
        hint: RenderHint,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """Шаблонный метод: общая логика + хуки для переопределения"""
        options = options or {}

        # 1. Предобработка: отфильтровать узлы, если нужно
        nodes = self._filter_nodes(result.matches, hint, options)

        # 2. Рендеринг каждого узла
        rendered_nodes = [
            self._render_node(node, hint, options)
            for node in nodes
        ]

        # 3. Применение лимитов (ОБРЕЗКА ЗДЕСЬ, не раньше!)
        limited = self._apply_limits(rendered_nodes, hint)

        # 4. Форматирование вывода
        return self._format_output(limited, result, hint, options)

    @abstractmethod
    def _render_node(
        self,
        node: CodeNode,
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> str:
        """Отрендерить один узел (без применения лимитов)"""
        ...

    def _filter_nodes(
        self,
        nodes: List[CodeNode],
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> List[CodeNode]:
        """Фильтрация узлов перед рендерингом (по kind, meta, etc.)"""
        # Default: вернуть все, переопределить если нужна логика
        return nodes

    def _apply_limits(
        self,
        rendered: List[str],
        hint: RenderHint
    ) -> List[str]:
        """
        Применить лимиты (max_lines, max_tokens) и стратегию обрезки.

        Стратегия:
        - Если влезает всё → вернуть как есть
        - Если нет → обрезать по hint.truncate_strategy
        - Добавить маркер обрезки: "[...]" или "[body hidden]"
        """
        if not rendered:
            return rendered

        # Сначала применяем лимиты к каждому узлу через hint
        limited = []
        for text in rendered:
            if hint.max_lines is not None or hint.max_tokens is not None:
                limited_text = hint.apply_limits(text)
                limited.append(limited_text)
            else:
                limited.append(text)

        # Потом проверяем общий лимит (если hint.max_lines задан глобально)
        # Это уже сделано в apply_limits для каждого узла
        return limited

    @abstractmethod
    def _format_output(
        self,
        rendered_nodes: List[str],
        result: ParseResult,
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> str:
        """Финальное форматирование: добавить заголовки, мета, оформить как text/json/etc."""
        ...

    # Utility: общие хелперы для рендеринга
    @staticmethod
    def _truncate_code(code: str, max_lines: int, strategy: str) -> str:
        """Обрезать код по стратегии (статический метод для переиспользования)"""
        lines = code.splitlines()
        if len(lines) <= max_lines:
            return code

        if strategy == "head":
            return "\n".join(lines[:max_lines]) + "\n[...]"
        elif strategy == "tail":
            return "[...]\n" + "\n".join(lines[-max_lines:])
        elif strategy == "ellipsis-middle":
            half = max_lines // 2
            return "\n".join(lines[:half]) + "\n    [...]\n" + "\n".join(lines[-half:])
        elif strategy == "smart":
            # Делегируем умную обрезку
            hint = RenderHint(
                node=CodeNode(
                    id="temp", name="temp", kind="temp", language="temp",
                    file_path="", span=Span(0, 0, 0, 0), context_code=""
                ),
                max_lines=max_lines,
                truncate_strategy="smart"
            )
            return hint.apply_limits(code)
        else:
            return "\n".join(lines[:max_lines]) + "\n[...]"

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Грубая оценка токенов (для LLM-режима)"""
        # Примерно 4 символа на токен для кода
        # TODO: заменить на tiktoken если нужен точный подсчёт
        return max(1, len(text) // 4)


# Импорт Span нужен для _truncate_code
from core.models import Span
