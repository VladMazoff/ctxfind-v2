"""
ctxfind-v2: Plugin Registry

Стратегия:
- Никакого magic, auto-discovery, entry_points
- Явная регистрация в __init__.py каждого модуля
- Простой dict-based lookup, без зависимостей
"""

from typing import Dict, Type, List, Optional, Any
from .interfaces import BaseParser, BaseEnricher, BaseRenderer


class _RegistryBase:
    """Базовый класс для всех реестров (не наследовать, использовать композицию)"""

    def __init__(self):
        self._items: Dict[str, Type] = {}

    def register(self, name: str, cls: Type):
        """Зарегистрировать реализацию по имени"""
        if name in self._items:
            raise ValueError(f"Duplicate registration: '{name}' already registered as {self._items[name].__name__}")

        # Валидация: cls должен реализовывать нужный Protocol
        # Примечание: runtime_checkable Protocol проверяет только наличие методов
        # Для строгой проверки можно добавить inspect.getmembers
        self._items[name] = cls

    def get(self, name: str) -> Optional[Type]:
        """Получить класс по имени"""
        return self._items.get(name)

    def list(self) -> List[str]:
        """Список зарегистрированных имён"""
        return list(self._items.keys())

    def all(self) -> Dict[str, Type]:
        """Все зарегистрированные элементы"""
        return dict(self._items)

    def select_best(
        self, 
        file_path: str, 
        content: str, 
        mode: str = "auto"
    ) -> List[Type]:
        """
        Выбрать лучшие реализации для файла.

        Логика:
        1. Отфильтровать по supports()
        2. Отсортировать по priority (desc)
        3. Вернуть отсортированный список (оркестратор решит, какой использовать)

        Примечание: mode не учитывается здесь — это ответственность оркестратора.
        """
        candidates = []
        for name, cls in self._items.items():
            try:
                # Проверяем supports — дёшево, без инициализации
                if hasattr(cls, 'supports') and callable(cls.supports):
                    # Для static/class method — вызываем напрямую
                    if cls.supports(file_path, content):
                        candidates.append(cls)
            except Exception:
                # supports() упал — пропускаем парсер
                continue

        # Сортировка по priority (desc) — чем выше, тем раньше пробуем
        candidates.sort(key=lambda c: getattr(c, 'priority', 0), reverse=True)
        return candidates

    def clear(self):
        """Очистить реестр (для тестов)"""
        self._items.clear()


# Глобальные реестры (инициализируются при импорте модулей)
parsers: _RegistryBase = _RegistryBase()
enrichers: _RegistryBase = _RegistryBase()
renderers: _RegistryBase = _RegistryBase()


# Helper для регистрации (использовать в __init__.py модулей)
def register_parser(name: str, cls: Type[BaseParser]):
    parsers.register(name, cls)

def register_enricher(name: str, cls: Type[BaseEnricher]):
    enrichers.register(name, cls)

def register_renderer(name: str, cls: Type[BaseRenderer]):
    renderers.register(name, cls)
