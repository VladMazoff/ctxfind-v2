"""
ctxfind-v2: Tree-Sitter Parser (via tree_sitter_languages)

Стратегия:
- Единая обёртка над tree_sitter_languages.get_parser() для всех языков
- Язык подгружается динамически по расширению/конфигу
- AST traversal делегирован стратегии (поиск по имени/типу/паттерну)
- Контекст = полный текст семантического родителя (функция/класс/модуль)
- НИКАКОЙ обрезки контекста здесь. Renderer решит.

Зависимости:
    pip install tree-sitter==0.20.4 tree-sitter-languages==1.10.2

Рабочий пример (test_ts.py):
    from tree_sitter_languages import get_parser
    python_parser = get_parser("python")
    tree = python_parser.parse(b"def foo(): pass")
"""

from typing import Dict, Any, List, Optional, Callable
from pathlib import Path
import logging
import warnings
import re

from core.models import CodeNode, Span, ParseResult, QueryMode
from core.interfaces import BaseParser
from core.registry import register_parser
from parsers.lang_configs import get_language_config, LanguageConfig

log = logging.getLogger(__name__)

# ─── Ленивая загрузка tree_sitter_languages ─────────────────────────────
TREE_SITTER_AVAILABLE = False
_get_parser = None

try:
    from tree_sitter_languages import get_parser
    TREE_SITTER_AVAILABLE = True
    _get_parser = get_parser
    log.debug("tree_sitter_languages loaded successfully")
except ImportError:
    warnings.warn(
        "tree-sitter-languages not installed. Deep mode unavailable. "
        "Install with: pip install tree-sitter==0.20.4 tree-sitter-languages==1.10.2",
        ImportWarning
    )


class TreeSitterParser:
    """
    Реализация BaseParser через tree_sitter_languages.get_parser().

    Архитектурные решения:
    1. Парсер = объект от get_parser(), кэшируется на уровне класса
    2. Парсинг = однократный, дерево кэшируется на время обработки файла
    3. Поиск = Visitor pattern: обход дерева + сбор совпадений
    4. Контекст = берётся текст node.parent (или root, если нет родителя)
    """

    name = "tree-sitter"
    priority = 90  # Высокий: точный AST-анализ
    supported_extensions: Dict[str, str] = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".css": "css",
        ".html": "html",
    }

    # Кэш парсеров на уровне класса: language_name -> Parser
    _parser_cache: Dict[str, Any] = {}

    def __init__(self, language_name: Optional[str] = None):
        self.language_name = language_name
        self.parser: Optional[Any] = None
        self.config: Optional[LanguageConfig] = None

    def _init_parser(self, language_name: str) -> bool:
        """Инициализировать Parser через get_parser (с кэшированием).

        Returns:
            bool: True если успешно, False при ошибке загрузки
        """
        if language_name in self._parser_cache:
            self.parser = self._parser_cache[language_name]
            return True

        if not TREE_SITTER_AVAILABLE:
            log.warning("tree_sitter_languages not installed")
            return False

        try:
            self.parser = _get_parser(language_name)
            self._parser_cache[language_name] = self.parser
            log.debug(f"Loaded parser for language: {language_name}")
            return True
        except Exception as e:
            log.warning(f"Failed to load parser for language '{language_name}': {e}")
            return False

    @staticmethod
    def supports(file_path: str, content_snippet: str) -> bool:
        """Быстрая проверка по расширению. Дёшево, без парсинга."""
        if not TREE_SITTER_AVAILABLE:
            return False
        ext = Path(file_path).suffix.lower()
        return ext in TreeSitterParser.supported_extensions

    def parse(
        self,
        file_path: str,
        content: str,
        query: str,
        mode: QueryMode = QueryMode.AUTO,
        options: Optional[Dict[str, Any]] = None
    ) -> ParseResult:
        """Основной контракт парсера."""
        result = ParseResult(
            query=query,
            file_path=file_path,
            parser_name=self.name
        )

        if not TREE_SITTER_AVAILABLE:
            result.warnings.append(
                "AST parser unavailable: install with 'pip install tree-sitter==0.20.4 tree-sitter-languages==1.10.2'"
            )
            return result

        try:
            ext = Path(file_path).suffix.lower()
            language_name = self.supported_extensions.get(ext)
            if not language_name:
                result.warnings.append(f"Unsupported extension: {ext}")
                return result

            self.language_name = language_name
            self.config = get_language_config(language_name)

            if not self._init_parser(language_name):
                result.warnings.append(
                    f"Failed to initialize parser for {language_name}. "
                    f"Is tree-sitter-languages installed?"
                )
                return result

            # 1. Построить AST
            tree = self._parse_tree(content)
            if not tree:
                result.warnings.append("Tree-sitter failed to parse AST")
                return result

            # 2. Найти совпадения
            matches_ts = self._find_nodes(tree.root_node, query, mode)

            # 3. Преобразовать в CodeNode
            seen = set()
            for ts_node in matches_ts:
                node = self._ts_node_to_code_node(
                    ts_node=ts_node,
                    file_path=file_path,
                    content=content
                )
                # Дедупликация по id
                if node.id not in seen:
                    seen.add(node.id)
                    result.matches.append(node)

            # 4. Заполнить эвристики парсера
            result.heuristics["parser_confidence"] = 0.95 if matches_ts else 0.0
            result.heuristics["ast_nodes_found"] = float(len(matches_ts))

        except Exception as e:
            result.warnings.append(f"Tree-sitter parsing error: {str(e)}")
            log.debug(f"Parse error in {file_path}: {e}", exc_info=True)

        return result

    def quick_match(self, content: str, query: str) -> List[Dict[str, Any]]:
        """Fallback для режима FAST: простой текстовый поиск с позициями."""
        results = []
        idx = 0
        while True:
            idx = content.find(query, idx)
            if idx == -1:
                break

            lines_before = content[:idx].count("\n")
            last_newline = content[:idx].rfind("\n")
            col = idx - last_newline - 1 if last_newline >= 0 else idx

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

    def _parse_tree(self, content: str):
        """Построить AST из строки. Вернуть tree или None при ошибке."""
        if self.parser is None:
            return None
        try:
            return self.parser.parse(content.encode("utf-8"))
        except Exception as e:
            log.debug(f"AST parse error: {e}")
            return None

    def _find_nodes(self, root_node: Any, query_str: str, mode: QueryMode) -> List[Any]:
        """Обойти AST и найти узлы, соответствующие query."""
        matches = []

        def visit(node: Any):
            # Пропускаем комментарии и строки
            if node.type in ("comment", "string", "string_literal", "template_string"):
                return

            # Проверяем, что тип узла интересен
            if self.config and node.type in self.config.kind_map:
                name = self._extract_name(node)

                # Совпадение по имени или по содержимому
                if name == query_str:
                    matches.append(node)
                else:
                    node_text = node.text.decode("utf-8") if isinstance(node.text, bytes) else node.text
                    if self._is_valid_match(node_text, query_str, node.type):
                        matches.append(node)

            # Рекурсивно обходим детей
            for child in node.children:
                visit(child)

        visit(root_node)
        return matches

    def _is_valid_match(self, node_text: str, query: str, node_type: str) -> bool:
        """Проверить, что совпадение валидно (не подстрока другого имени)"""
        pattern = rf"\b{re.escape(query)}\b"
        return bool(re.search(pattern, node_text))

    def _ts_node_to_code_node(self, ts_node: Any, file_path: str, content: str) -> CodeNode:
        """Преобразовать tree-sitter Node в унифицированный CodeNode."""
        kind = self._map_kind(ts_node)
        name = self._extract_name(ts_node) or "unknown"

        span = Span(
            start_line=ts_node.start_point[0],
            start_col=ts_node.start_point[1],
            end_line=ts_node.end_point[0],
            end_col=ts_node.end_point[1]
        )

        # ИСПРАВЛЕНИЕ: контекст = текст самого узла + несколько строк родителя для контекста
        context_text = self._extract_semantic_context(ts_node, content)

        meta = {
            "ts_type": ts_node.type,
            "is_exported": self._is_exported(ts_node, content),
            "has_docstring": self._has_docstring(ts_node),
            "v1_role": self._guess_role_from_ast(ts_node),
        }

        return CodeNode(
            id=f"{file_path}:{span.start_line}:{kind}:{name}",
            name=name,
            kind=kind,
            language=self.language_name or "unknown",
            file_path=file_path,
            span=span,
            context_code=context_text,
            context_ast={
                "type": ts_node.type,
                "start_byte": ts_node.start_byte,
                "end_byte": ts_node.end_byte,
                "child_count": len(ts_node.children),
            },
            meta=meta
        )

    def _extract_semantic_context(self, node: Any, full_content: str) -> str:
        """
        Вернуть полный текст кода, который логически содержит node.

        ИСПРАВЛЕНИЕ: берём текст самого узла + до 3 строк родителя для контекста,
        но не весь родительский scope (чтобы не показывать класс целиком).
        """
        # Текст самого узла
        node_text = full_content[node.start_byte:node.end_byte]

        # Добавляем до 3 строк контекста сверху (родитель/соседи)
        lines_before = full_content[:node.start_byte].split("\n")
        context_before = ""
        if len(lines_before) >= 2:
            # Берём до 2 строк перед узлом
            context_before = "\n".join(lines_before[-2:])

        if context_before:
            return context_before + "\n" + node_text
        return node_text

    def _map_kind(self, node: Any) -> str:
        """
        Маппинг tree-sitter типов → унифицированные kind.

        ИСПРАВЛЕНИЕ: различаем method vs function по parent.type.
        """
        ts_type = node.type
        if self.config:
            base_kind = self.config.kind_map.get(ts_type, "unknown")
        else:
            base_kind = "unknown"

        # Различаем method vs function
        if base_kind == "function" and node.parent:
            parent_type = node.parent.type
            if parent_type in ("class_definition", "class_declaration", "class_body", "object"):
                return "method"

        return base_kind

    def _extract_name(self, node: Any) -> Optional[str]:
        """
        Извлечь имя из AST-узла.

        ИСПРАВЛЕНИЕ: более robust логика для разных языков.
        """
        # Сначала пробуем конфигурацию
        if self.config and self.config.name_strategy:
            result = self.config.name_strategy(node)
            if result:
                return result

        # Общая логика: ищем identifier или property_identifier
        for child in node.children:
            if child.type in ("identifier", "property_identifier", "type_identifier"):
                text = child.text
                decoded = text.decode("utf-8") if isinstance(text, bytes) else text
                if decoded:
                    return decoded

        # Для Python: если нет identifier, пробуем найти внутри decorated_definition
        if node.type == "decorated_definition" and node.children:
            # Рекурсивно ищем внутри
            for child in node.children:
                if child.type in ("function_definition", "class_definition"):
                    return self._extract_name(child)

        return None

    def _is_exported(self, node: Any, content: str) -> bool:
        """Проверить, экспортируется ли узел"""
        if self.config is None or not self.config.export_keywords:
            return False

        node_text = content[node.start_byte:node.end_byte]
        for keyword in self.config.export_keywords:
            if keyword in node_text:
                return True

        if self.language_name == "python":
            if "__all__" in content:
                name = self._extract_name(node)
                if name:
                    if f'"{name}"' in content or f"'{name}'" in content:
                        return True

        return False

    def _has_docstring(self, node: Any) -> bool:
        """Проверить наличие docstring у узла"""
        if not node.children:
            return False

        for child in node.children:
            if child.type in ("string", "expression_statement", "comment"):
                text = child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
                stripped = text.strip()
                if stripped.startswith(("\"\"\"", "\'\'\'", "/**", "/*")):
                    return True

        return False

    def _guess_role_from_ast(self, node: Any) -> str:
        """Угадать роль из AST: << def / >> use / >< mod"""
        return "<< def"


# Регистрация
register_parser("tree-sitter", TreeSitterParser)
