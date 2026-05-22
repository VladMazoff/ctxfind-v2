"""
ctxfind-v2: Module Interfaces (Protocols)

Стратегия:
- typing.Protocol для структурной типизации (no inheritance hell)
- Минимум методов: только то, что нужно ядру
- Расширение через композицию, не наследование
"""

from typing import Protocol, Dict, Any, List, Optional, runtime_checkable
from .models import ParseResult, CodeNode, RenderHint, QueryMode

@runtime_checkable
class BaseParser(Protocol):
    """
    Контракт для языкового парсера.

    Стратегия:
    - Парсер не знает о рендеринге, CLI, кэшировании
    - Парсер возвращает ПОЛНЫЙ контекст, не обрезает
    - Парсер может падать → ядро переключится на fallback
    """

    name: str  # уникальное имя: "python-ast", "tree-sitter-js", "regex-fallback"
    priority: int  # чем выше, тем раньше пробуем (100 = fallback)
    supported_extensions: List[str]  # [".py", ".pyi"]

    def supports(self, file_path: str, content_snippet: str) -> bool:
        """
        Быстрая проверка: может ли парсер обработать этот файл?
        Вызывается до parse(), должна быть дешёвой.
        """
        ...

    def parse(
        self,
        file_path: str,
        content: str,
        query: str,
        mode: QueryMode = QueryMode.AUTO,
        options: Optional[Dict[str, Any]] = None
    ) -> ParseResult:
        """
        Основной метод: найти query в коде и вернуть структурированный результат.

        Требования:
        - Не модифицировать входные данные
        - Заполнять только те поля CodeNode, которые парсер уверенно определил
        - В случае ошибки парсинга → вернуть ParseResult с warnings, не выбрасывать
        - Для mode=FAST может использовать упрощённую логику
        """
        ...

    # Опционально: быстрая пред-проверка для режима FAST
    def quick_match(self, content: str, query: str) -> List[Dict[str, Any]]:
        """
        Regex-based эвристика для режима FAST.
        Возвращает список простых матчей: {line, col, snippet, confidence}
        Используется, если полный парсинг слишком дорогой.

        ОПЦИОНАЛЬНО: если не реализован, ядро пропустит этот шаг.
        """
        # Optional: если не реализован, ядро пропустит этот шаг
        ...

@runtime_checkable
class BaseEnricher(Protocol):
    """
    Контракт для пост-обработчика результата.

    Стратегия:
    - Энричеры работают последовательно: result → enrich1 → enrich2 → ...
    - Каждый может добавить мета, связи, скоринг
    - Не должен менять исходные данные узлов (только meta, references)
    """

    name: str
    runs_after: List[str]  # имена энричеров, после которых запускать
    enabled_by_default: bool = True

    def enrich(
        self,
        result: ParseResult,
        options: Optional[Dict[str, Any]] = None
    ) -> ParseResult:
        """
        Добавить информацию в результат.

        Примеры:
        - heuristic_scorer: добавить v1-метрики
        - cross_lang_linker: найти связи по именам
        - test_finder: пометить узлы, у которых есть тесты
        """
        ...

@runtime_checkable
class BaseRenderer(Protocol):
    """
    Контракт для рендерера.

    Стратегия:
    - Рендерер — ЕДИНСТВЕННОЕ место, где происходит обрезка контекста
    - Один ParseResult может быть отрендерен много раз в разных форматах
    - Рендерер знает о пользователе, парсер — нет
    """

    name: str
    output_formats: List[str]  # ["text", "json", "llm_prompt"]

    def can_render(self, format: str) -> bool:
        """Поддерживает ли рендерер этот формат вывода?"""
        ...

    def render(
        self,
        result: ParseResult,
        hint: RenderHint,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Преобразовать результат в строку для вывода.

        Требования:
        - Применять лимиты из hint (max_lines, max_tokens, etc.)
        - Использовать truncate_strategy при обрезке
        - Для llm_prompt: добавлять мета-информацию, если hint.llm_include_meta
        - Не модифицировать входные данные
        """
        ...

    # Опционально: массовый рендеринг для нескольких узлов
    def render_batch(
        self,
        results: List[ParseResult],
        hints: List[RenderHint],
        options: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Эффективный рендеринг нескольких результатов.
        Может переиспользовать общие части (импорты, заголовки).

        ОПЦИОНАЛЬНО: если не реализован, ядро вызовет render() по очереди.
        """
        ...
