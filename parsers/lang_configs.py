"""
ctxfind-v2: Language Configurations for Tree-Sitter Parser

Стратегия:
- @dataclass(frozen=True) с 4 полями: kind_map, name_strategy, scope_types, export_keywords
- Типизация + иммутабельность = меньше багов при добавлении языков
- Конфиги отдельно от логики обхода AST
"""

from dataclasses import dataclass, field
from typing import Dict, List, Callable, Optional, Any
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tree_sitter import Node

@dataclass(frozen=True)
class LanguageConfig:
    """
    Конфигурация языка для TreeSitterParser.

    Поля:
    - kind_map: маппинг tree-sitter type → унифицированный kind
    - name_strategy: как извлекать имя из AST-узла
    - scope_types: типы узлов, определяющие семантический scope
    - export_keywords: ключевые слова, указывающие на экспорт
    """

    # Маппинг: tree-sitter node.type → унифицированный kind
    kind_map: Dict[str, str] = field(default_factory=dict)

    # Функция извлечения имени из AST-узла
    # Принимает Node, возвращает str или None
    name_strategy: Optional[Callable[[Any], Optional[str]]] = None

    # Типы узлов, которые определяют семантический scope (для контекста)
    scope_types: List[str] = field(default_factory=list)

    # Ключевые слова экспорта (для определения is_exported)
    export_keywords: List[str] = field(default_factory=list)

    # Дополнительные паттерны для эвристик
    docstring_types: List[str] = field(default_factory=lambda: ["string", "comment"])

# ─── Python Config ──────────────────────────────────────────────────────

def _python_extract_name(node: Any) -> Optional[str]:
    """Извлечь имя из Python AST-узла"""
    # Для function_definition: имя — первый child с type="identifier"
    # Для class_declaration: аналогично
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8") if isinstance(child.text, bytes) else child.text
    return None

PYTHON_CONFIG = LanguageConfig(
    kind_map={
        "function_definition": "function",
        "class_definition": "class",
        "method_definition": "method",
        "import_statement": "import",
        "import_from_statement": "import",
        "assignment": "variable",
        "decorated_definition": "function",  # @decorator + def
    },
    name_strategy=_python_extract_name,
    scope_types=[
        "function_definition",
        "class_definition",
        "method_definition",
        "module",
    ],
    export_keywords=["__all__"],
    docstring_types=["string", "expression_statement"],  # expression_statement для docstring
)

# ─── JavaScript Config ──────────────────────────────────────────────────

def _js_extract_name(node: Any) -> Optional[str]:
    """Извлечь имя из JS AST-узла"""
    # function_declaration → identifier
    # class_declaration → identifier
    # variable_declarator → identifier (первый child)
    # method_definition → property_identifier
    for child in node.children:
        if child.type in ("identifier", "property_identifier"):
            text = child.text
            return text.decode("utf-8") if isinstance(text, bytes) else text
    return None

JAVASCRIPT_CONFIG = LanguageConfig(
    kind_map={
        "function_declaration": "function",
        "function_expression": "function",
        "arrow_function": "function",
        "class_declaration": "class",
        "class_expression": "class",
        "method_definition": "method",
        "variable_declarator": "variable",
        "import_statement": "import",
        "export_statement": "export",
    },
    name_strategy=_js_extract_name,
    scope_types=[
        "function_declaration",
        "function_expression",
        "arrow_function",
        "class_declaration",
        "class_expression",
        "method_definition",
        "program",
    ],
    export_keywords=["export", "module.exports", "exports."],
    docstring_types=["comment"],
)

# ─── TypeScript Config ──────────────────────────────────────────────────

TYPESCRIPT_CONFIG = LanguageConfig(
    kind_map={
        "function_declaration": "function",
        "function_expression": "function",
        "arrow_function": "function",
        "class_declaration": "class",
        "class_expression": "class",
        "method_definition": "method",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "variable_declarator": "variable",
        "import_statement": "import",
        "export_statement": "export",
    },
    name_strategy=_js_extract_name,
    scope_types=[
        "function_declaration",
        "function_expression",
        "arrow_function",
        "class_declaration",
        "class_expression",
        "method_definition",
        "interface_declaration",
        "type_alias_declaration",
        "program",
    ],
    export_keywords=["export", "export default", "module.exports"],
    docstring_types=["comment"],
)

# ─── CSS Config ─────────────────────────────────────────────────────────

def _css_extract_name(node: Any) -> Optional[str]:
    """Извлечь имя из CSS AST-узла"""
    # class_selector → type_selector или class_name
    for child in node.children:
        text = child.text
        if text:
            decoded = text.decode("utf-8") if isinstance(text, bytes) else text
            decoded = decoded.strip()
            if decoded and not decoded.startswith("{"):
                return decoded.lstrip(".#")
    return None

CSS_CONFIG = LanguageConfig(
    kind_map={
        "class_selector": "css_class",
        "id_selector": "css_id",
        "tag_selector": "css_tag",
        "attribute_selector": "css_attr",
        "declaration": "css_property",
        "rule_set": "css_rule",
    },
    name_strategy=_css_extract_name,
    scope_types=["rule_set", "stylesheet"],
    export_keywords=[],
    docstring_types=["comment"],
)

# ─── Реестр конфигов ────────────────────────────────────────────────────

LANGUAGE_CONFIGS: Dict[str, LanguageConfig] = {
    "python": PYTHON_CONFIG,
    "javascript": JAVASCRIPT_CONFIG,
    "typescript": TYPESCRIPT_CONFIG,
    "css": CSS_CONFIG,
}

def get_language_config(language_name: str) -> LanguageConfig:
    """Получить конфигурацию языка по имени"""
    if language_name not in LANGUAGE_CONFIGS:
        raise ValueError(f"Unknown language: {language_name}. "
                         f"Available: {list(LANGUAGE_CONFIGS.keys())}")
    return LANGUAGE_CONFIGS[language_name]

def register_language_config(name: str, config: LanguageConfig):
    """Зарегистрировать новую конфигурацию языка"""
    LANGUAGE_CONFIGS[name] = config
