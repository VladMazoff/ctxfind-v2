"""
ctxfind-v2: Core Data Models

Стратегия:
- Все данные иммутабельны (frozen dataclasses)
- Контекст хранится ПОЛНОСТЬЮ, обрезка — только в Renderer
- Минимум зависимостей: stdlib + typing
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
import hashlib


class QueryMode(Enum):
    """Режимы поиска — влияют на выбор парсера и глубину"""
    FAST = "fast"        # только regex fallback, минимум парсинга
    DEEP = "deep"        # полный AST-парсинг + линкер
    AUTO = "auto"        # эвристика: маленький проект → deep, большой → fast


@dataclass(frozen=True)
class Span:
    """Позиция в исходном коде (0-based lines, 0-based cols)"""
    start_line: int
    start_col: int
    end_line: int
    end_col: int

    def __post_init__(self):
        if self.start_line < 0 or self.start_col < 0 or self.end_line < 0 or self.end_col < 0:
            raise ValueError(f"Span coordinates must be non-negative, got {self}")
        if (self.start_line, self.start_col) > (self.end_line, self.end_col):
            raise ValueError(
                f"Span start must be <= end, got start=({self.start_line},{self.start_col}) "
                f"end=({self.end_line},{self.end_col})"
            )

    def length(self) -> int:
        """Примерная длина в символах (для эвристик)"""
        if self.start_line == self.end_line:
            return self.end_col - self.start_col
        # Для многострочных — эвристика
        return (self.end_line - self.start_line) * 80 + (self.end_col - self.start_col)

    def to_dict(self) -> Dict[str, int]:
        return {
            "start_line": self.start_line,
            "start_col": self.start_col,
            "end_line": self.end_line,
            "end_col": self.end_col,
        }

    @classmethod
    def from_lsp(cls, start: Dict[str, int], end: Dict[str, int]) -> "Span":
        """Создать Span из LSP Position/Range формата"""
        return cls(
            start_line=start.get("line", 0),
            start_col=start.get("character", 0),
            end_line=end.get("line", 0),
            end_col=end.get("character", 0),
        )


@dataclass(frozen=True)
class Ref:
    """Ссылка на другой узел (для графа зависимостей)"""
    target_name: str
    target_kind: str  # "function", "class", "import", "css_class", etc.
    source_file: str
    target_file: Optional[str] = None  # None = same file
    ref_type: str = "use"  # "use" | "define" | "import" | "override"

    def __post_init__(self):
        if self.ref_type not in ("use", "define", "import", "override"):
            raise ValueError(f"Invalid ref_type: {self.ref_type}")

    def __hash__(self):
        return hash((self.target_name, self.target_kind, self.source_file, 
                     self.target_file or "", self.ref_type))

    def __eq__(self, other):
        if not isinstance(other, Ref):
            return NotImplemented
        return (self.target_name == other.target_name and 
                self.target_kind == other.target_kind and
                self.source_file == other.source_file and
                self.target_file == other.target_file and
                self.ref_type == other.ref_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_name": self.target_name,
            "target_kind": self.target_kind,
            "source_file": self.source_file,
            "target_file": self.target_file,
            "ref_type": self.ref_type,
        }


@dataclass(frozen=True)
class CodeNode:
    """
    Абстрактный элемент кода — единая валюта между парсерами.

    Стратегия:
    - Парсер заполняет только то, что знает точно
    - Неизвестные поля → meta dict
    - Renderer решает, что показывать
    """
    # Идентификация
    id: str  # unique: f"{file}:{span.start_line}:{kind}:{name}"
    name: str
    kind: str  # таксономия: "function", "class", "method", "import", "css_selector", etc.
    language: str  # "python", "javascript", "css", "html"

    # Позиция
    file_path: str
    span: Span

    # Контекст: ВЕСЬ фрагмент, который парсер считает релевантным
    # ВАЖНО: не обрезан! Renderer решит, сколько показать
    context_code: str  # исходный код фрагмента
    context_ast: Optional[Dict[str, Any]] = None  # сырой AST, если парсер отдал

    # Связи (заполняет парсер или linker-enricher)
    references: List[Ref] = field(default_factory=list)  # что этот узел использует
    referenced_by: List[Ref] = field(default_factory=list)  # кто использует этот узел

    # Метаданные для скоринга и фильтрации
    meta: Dict[str, Any] = field(default_factory=dict)
    # Примеры мета:
    # - "is_exported": bool
    # - "complexity": int
    # - "has_docstring": bool
    # - "v1_role": str  # "<< def", ">> use" из v1

    def __post_init__(self):
        # Валидация id
        if not self.id:
            raise ValueError("CodeNode.id cannot be empty")
        # Валидация kind — не пустой
        if not self.kind:
            raise ValueError("CodeNode.kind cannot be empty")
        # Валидация language — не пустой
        if not self.language:
            raise ValueError("CodeNode.language cannot be empty")
        # Предупреждение о пустом context_code — ловит баги парсеров
        if not self.context_code or not self.context_code.strip():
            import logging
            logging.getLogger(__name__).warning(
                f"CodeNode '{self.name}' ({self.kind}) has empty context_code — "
                f"parser bug? file={self.file_path}:{self.span.start_line}"
            )

    def to_llm_dict(self) -> Dict[str, Any]:
        """Экспорт в формат, удобный для LLM-промптов"""
        result = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "language": self.language,
            "file_path": self.file_path,
            "span": self.span.to_dict(),
            "context_code": self.context_code,
            "references": [r.to_dict() for r in self.references],
            "referenced_by": [r.to_dict() for r in self.referenced_by],
            "meta": dict(self.meta),  # копия
        }
        if self.context_ast is not None:
            # AST может быть тяжёлым — включаем только если явно нужно
            result["has_ast"] = True
        return result

    def with_meta(self, **kwargs) -> "CodeNode":
        """Создать копию с обновлёнными meta (immutable update)"""
        new_meta = dict(self.meta)
        new_meta.update(kwargs)
        # frozen dataclass — создаём новый экземпляр
        return CodeNode(
            id=self.id,
            name=self.name,
            kind=self.kind,
            language=self.language,
            file_path=self.file_path,
            span=self.span,
            context_code=self.context_code,
            context_ast=self.context_ast,
            references=list(self.references),
            referenced_by=list(self.referenced_by),
            meta=new_meta,
        )


@dataclass
class ParseResult:
    """
    Результат работы парсера.

    Стратегия:
    - Один запрос → один файл → один ParseResult
    - matches могут быть пустыми (файл просканен, но не нашёл)
    - Полный контекст файла загружается лениво (если нужно)
    """
    query: str
    file_path: str
    parser_name: str  # какой парсер обработал

    matches: List[CodeNode] = field(default_factory=list)

    # Эвристики для ранжирования (заполняет парсер или enricher)
    heuristics: Dict[str, float] = field(default_factory=dict)
    # Примеры: "relevance", "specificity", "v1_score"

    # Ошибки парсинга (не фатальные)
    warnings: List[str] = field(default_factory=list)

    # Ленивый доступ к полному контексту файла
    _full_content: Optional[str] = field(default=None, repr=False)
    _loader: Optional[Any] = field(default=None, repr=False)

    def get_full_content(self, loader: Optional[Any] = None) -> Optional[str]:
        """
        Загружает полный контент файла, если не загружен.
        :param loader: функция file_path -> str
        :return: полный исходный код файла
        """
        if self._full_content is not None:
            return self._full_content
        if loader is not None:
            self._full_content = loader(self.file_path)
            return self._full_content
        if self._loader is not None:
            self._full_content = self._loader(self.file_path)
            return self._full_content
        return None

    def set_loader(self, loader: Any):
        """Установить loader для ленивой загрузки"""
        self._loader = loader

    def merge(self, other: "ParseResult") -> "ParseResult":
        """Объединить два результата (например, от разных парсеров)"""
        # Объединяем matches, убираем дубликаты по id
        seen = {m.id for m in self.matches}
        merged_matches = list(self.matches)
        for m in other.matches:
            if m.id not in seen:
                merged_matches.append(m)
                seen.add(m.id)

        # Объединяем эвристики — берём max
        merged_heuristics = dict(self.heuristics)
        for key, val in other.heuristics.items():
            merged_heuristics[key] = max(merged_heuristics.get(key, 0.0), val)

        # Объединяем warnings
        merged_warnings = list(self.warnings)
        for w in other.warnings:
            if w not in merged_warnings:
                merged_warnings.append(w)

        return ParseResult(
            query=self.query,
            file_path=self.file_path,
            parser_name=f"{self.parser_name}+{other.parser_name}",
            matches=merged_matches,
            heuristics=merged_heuristics,
            warnings=merged_warnings,
        )

    def filter_by_kind(self, kind: str) -> "ParseResult":
        """Пост-фильтрация по kind"""
        filtered = [m for m in self.matches if m.kind == kind]
        return ParseResult(
            query=self.query,
            file_path=self.file_path,
            parser_name=self.parser_name,
            matches=filtered,
            heuristics=dict(self.heuristics),
            warnings=list(self.warnings),
        )

    def filter_by_language(self, language: str) -> "ParseResult":
        """Пост-фильтрация по language"""
        filtered = [m for m in self.matches if m.language == language]
        return ParseResult(
            query=self.query,
            file_path=self.file_path,
            parser_name=self.parser_name,
            matches=filtered,
            heuristics=dict(self.heuristics),
            warnings=list(self.warnings),
        )


@dataclass
class RenderHint:
    """
    Инструкция для рендерера: ЧТО показать и КАК.

    Стратегия:
    - Парсер/энричер выставляет "намерения" (что важно)
    - Рендерер применяет ограничения (сколько влезет)
    - Один ParseResult → много RenderHint → много форматов вывода
    """
    node: CodeNode

    # Семантические флаги (что важно показать)
    show_signature: bool = True
    show_body: bool = False
    show_imports: bool = True
    show_related_names: List[str] = field(default_factory=list)  # показать узлы с этими именами

    # Ограничения (задаются пользователем или профилем)
    max_tokens: Optional[int] = None
    max_lines: Optional[int] = None
    max_depth: Optional[int] = None  # для вложенных структур

    # Стратегия обрезки, если контекст не влезает
    truncate_strategy: str = "smart"  # "smart" | "head" | "tail" | "ellipsis-middle"

    # Формат вывода
    output_format: str = "text"  # "text" | "json" | "llm_prompt" | "markdown"

    # Дополнительные подсказки для LLM-режима
    llm_role: Optional[str] = None  # "system" | "user" | "assistant"
    llm_include_meta: bool = True

    def __post_init__(self):
        valid_strategies = ("smart", "head", "tail", "ellipsis-middle")
        if self.truncate_strategy not in valid_strategies:
            raise ValueError(f"Invalid truncate_strategy: {self.truncate_strategy}. "
                           f"Must be one of {valid_strategies}")
        valid_formats = ("text", "compact", "json", "llm_prompt", "markdown")
        if self.output_format not in valid_formats:
            raise ValueError(f"Invalid output_format: {self.output_format}. "
                           f"Must be one of {valid_formats}")

    def apply_limits(self, text: str) -> str:
        """Предварительная обрезка текста по лимитам"""
        lines = text.splitlines()

        if self.max_lines is not None and len(lines) > self.max_lines:
            if self.truncate_strategy == "head":
                lines = lines[:self.max_lines]
                lines.append("[...]")
            elif self.truncate_strategy == "tail":
                lines = ["[...]"] + lines[-self.max_lines:]
            elif self.truncate_strategy == "ellipsis-middle":
                half = self.max_lines // 2
                lines = lines[:half] + ["[...]"] + lines[-half:]
            elif self.truncate_strategy == "smart":
                lines = self._smart_truncate(lines, self.max_lines)

        result = "\n".join(lines)

        # Токены — грубая оценка после обрезки по строкам
        if self.max_tokens is not None:
            estimated = len(result) // 4  # грубо ~4 chars per token
            if estimated > self.max_tokens:
                # Обрезаем символами, если токены всё ещё превышены
                max_chars = self.max_tokens * 4
                if self.truncate_strategy == "tail":
                    result = "[...]" + result[-max_chars:]
                else:
                    result = result[:max_chars] + "[...]"

        return result

    def _smart_truncate(self, lines: List[str], max_lines: int) -> List[str]:
        """
        Умная обрезка: стараемся обрезать на границах блоков (пустые строки, отступы).
        """
        if len(lines) <= max_lines:
            return lines

        # Стратегия: показываем начало (сигнатуру/заголовок) + конец (return/закрытие)
        # Обрезаем середину
        header_lines = max_lines // 3  # ~33% сверху
        footer_lines = max_lines - header_lines - 1  # остальное снизу

        # Пытаемся найти хорошую границу для header
        header = lines[:header_lines]
        # Ищем ближайшую пустую строку после header_lines для расширения заголовка
        for i in range(header_lines, min(header_lines + 5, len(lines))):
            if lines[i].strip() == "":
                header = lines[:i]
                break

        footer = lines[-footer_lines:] if footer_lines > 0 else []
        # Ищем ближайшую пустую строку перед footer
        footer_start = len(lines) - footer_lines
        for i in range(footer_start, max(footer_start - 5, len(header)), -1):
            if i < len(lines) and lines[i].strip() == "":
                footer = lines[i+1:]
                break

        result = header + ["    [...]"] + footer
        return result[:max_lines]  # на всякий случай

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node.id,
            "show_signature": self.show_signature,
            "show_body": self.show_body,
            "show_imports": self.show_imports,
            "show_related_names": self.show_related_names,
            "max_tokens": self.max_tokens,
            "max_lines": self.max_lines,
            "max_depth": self.max_depth,
            "truncate_strategy": self.truncate_strategy,
            "output_format": self.output_format,
            "llm_role": self.llm_role,
            "llm_include_meta": self.llm_include_meta,
        }
