"""
ctxfind-v2: Context-aware code search — AST edition
"""

__version__ = "2.0.0-alpha"

# Импорт всех подмодулей для регистрации
from . import core
from . import parsers
from . import enrichers
from . import renderers
from . import config
from . import orchestrator
from . import cli

__all__ = ["__version__"]
