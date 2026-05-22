"""
ctxfind-v2: Tree-Sitter Parser

Стратегия:
- Единая обёртка над tree-sitter для всех языков
- Язык подгружается динамически по расширению/конфигу
- AST traversal делегирован стратегии (поиск по имени/типу/паттерну)
- Контекст = полный текст семантического родителя (функция/класс/модуль)
- НИКАКОЙ обрезки контекста здесь. Renderer решит.
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

# Ленивая загрузка tree-sitter (чтобы не падать при импорте без зависимостей)
TREE_SITTER_AVAILABLE = False
_Language = None
_Parser = None

try:
    from tree_sitter import Language, Parser, Node
    TREE_SITTER_AVAILABLE = True
    _Language = Language
    _Parser = Parser
except ImportError:
    warnings.warn(
        "tree-sitter not installed. Deep mode unavailable. "
        "Install with: pip install ctxfind[ast]",
        ImportWarning
    )


class TreeSitterParser:
    """
    Реализация BaseParser через tree-sitter.

    Архитектурные решения:
    1. Язык = кэшированный объект Language, переиспользуется между вызовами
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

    # Кэш языков на уровне класса
    _language_cache: Dict[str, Any] = {}

    def __init__(self, language_name: Optional[str] = None):
        self.language_name = language_name
        self.language: Optional[Any] = None
        self.parser: Optional[Any] = None
        self.config: Optional[LanguageConfig] = None

    def _init_language(self, language_name: str) -> bool:
        """Инициализировать Language и Parser (с кэшированием).

        Returns:
            bool: True если успешно, False при ошибке загрузки .so/.dll
        """
        if language_name in self._language_cache:
            self.language = self._language_cache[language_name]
            self.parser = _Parser()
            self.parser.set_language(self.language)
            return True

        if not TREE_SITTER_AVAILABLE:
            log.warning("tree-sitter not installed")
            return False

        # Динамическая загрузка grammar
        try:
            if language_name == "python":
                from tree_sitter_python import language as py_lang
                self.language = _Language(py_lang(), "python")
            elif language_name == "javascript":
                from tree_sitter_javascript import language as js_lang
                self.language = _Language(js_lang(), "javascript")
            elif language_name == "typescript":
                from tree_sitter_typescript import language as ts_lang
                self.language = _Language(ts_lang(), "typescript")
            elif language_name == "css":
                from tree_sitter_css import language as css_lang
                self.language = _Language(css_lang(), "css")
            else:
                log.warning(f"Unsupported language: {language_name}")
                return False

            self._language_cache[language_name] = self.language
            self.parser = _Parser()
            self.parser.set_language(self.language)
            return True

        except (ImportError, OSError, RuntimeError) as e:
            log.warning(f"Failed to load tree-sitter language '{language_name}': {e}")
            return False

    def supports(self, file_path: str, content_snippet: str) -> bool:
        """Быстрая проверка по расширению. Дёшево, без парсинга."""
        if not TREE_SITTER_AVAILABLE:
            return False
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
        """Основной контракт парсера."""
        result = ParseResult(
            query=query,
            file_path=file_path,
            parser_name=self.name
        )

        if not TREE_SITTER_AVAILABLE:
            result.warnings.append(
                "AST parser unavailable: install with 'pip install ctxfind[ast]'"
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
            self._init_language(language_name)

            # 1. Построить AST
            tree = self._parse_tree(content)
            if not tree:
                result.warnings.append("Tree-sitter failed to parse AST")
                return result

            # 2. Найти совпадения
            matches_ts = self._find_nodes(tree.root_node, query, mode)

            # 3. Преобразовать в CodeNode
            for ts_node in matches_ts:
                node = self._ts_node_to_code_node(
                    ts_node=ts_node,
                    file_path=file_path,
                    content=content
                )
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
        kind = self._map_kind(ts_node.type)
        name = self._extract_name(ts_node) or "unknown"

        span = Span(
            start_line=ts_node.start_point[0],
            start_col=ts_node.start_point[1],
            end_line=ts_node.end_point[0],
            end_col=ts_node.end_point[1]
        )

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
        """Вернуть полный текст кода, который логически содержит node."""
        if self.config is None:
            return full_content[node.start_byte:node.end_byte]

        scope_node = node
        current = node

        while current.parent is not None:
            parent = current.parent
            if parent.type in self.config.scope_types:
                scope_node = parent
                break
            current = parent

        if scope_node == node and node.parent is not None:
            scope_node = node.parent

        return full_content[scope_node.start_byte:scope_node.end_byte]

    def _map_kind(self, ts_type: str) -> str:
        """Маппинг tree-sitter типов → унифицированные kind"""
        if self.config:
            return self.config.kind_map.get(ts_type, "unknown")
        return "unknown"

    def _extract_name(self, node: Any) -> Optional[str]:
        """Извлечь имя из AST-узла через конфигурацию"""
        if self.config and self.config.name_strategy:
            return self.config.name_strategy(node)

        for child in node.children:
            if child.type == "identifier":
                text = child.text
                return text.decode("utf-8") if isinstance(text, bytes) else text
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
                if stripped.startswith(('"""', "'''", "/**", "/*")):
                    return True

        return False

    def _guess_role_from_ast(self, node: Any) -> str:
        """Угадать роль из AST: << def / >> use / >< mod"""
        return "<< def"


# Регистрация
register_parser("tree-sitter", TreeSitterParser)
