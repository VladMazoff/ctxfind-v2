"""
ctxfind-v2: Configuration

Стратегия:
- Дефолты в коде
- Переопределение через ~/.ctxfind/config.json
- Валидация на старте
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from pathlib import Path

@dataclass
class HeuristicWeights:
    """Настраиваемые веса для скоринга (дефолты из v1)"""
    position_weight: float = 0.3  # Чем ближе query к началу узла, тем лучше
    length_penalty: float = 0.2  # Слишком длинные узлы менее релевантны
    role_bonus: float = 0.4  # Определения важнее использований
    complexity_bonus: float = 0.1  # Сложные узлы чаще ищут
    export_bonus: float = 0.2  # Экспортируемые символы приоритетнее

    def __post_init__(self):
        for attr_name, value in self.__dict__.items():
            if not isinstance(value, (int, float)):
                raise ValueError(f"{attr_name} must be numeric, got {type(value)}")
            if value < 0:
                raise ValueError(f"{attr_name} must be non-negative, got {value}")

@dataclass
class Config:
    """Глобальная конфигурация ctxfind-v2"""

    # Поиск
    default_mode: str = "auto"  # fast | deep | auto
    max_file_size_mb: float = 5.0
    exclude_dirs: List[str] = field(default_factory=lambda: [
        ".git", "__pycache__", "node_modules", ".venv", "venv", "build", "dist"
    ])

    # Рендеринг
    default_format: str = "compact"  # compact | full | json | llm
    default_max_lines: int = 50
    default_max_tokens: Optional[int] = None

    # Эвристики
    heuristic_weights: HeuristicWeights = field(default_factory=HeuristicWeights)

    # Fallback
    fallback_parser: str = "regex-fallback"

    # Пути
    config_dir: Path = field(default_factory=lambda: Path.home() / ".ctxfind")

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Config":
        """Загрузить конфиг из файла или создать дефолтный"""
        config = cls()

        if path is None:
            path = config.config_dir / "config.json"

        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                config = cls._from_dict(data)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"Invalid config file {path}: {e}")

        return config

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Создать Config из dict (с валидацией)"""
        weights_data = data.pop("heuristic_weights", {})
        weights = HeuristicWeights(**weights_data)

        # Фильтруем только известные поля
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}

        return cls(heuristic_weights=weights, **filtered)

    def save(self, path: Optional[Path] = None):
        """Сохранить конфиг в файл"""
        if path is None:
            path = self.config_dir / "config.json"

        self.config_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "default_mode": self.default_mode,
            "max_file_size_mb": self.max_file_size_mb,
            "exclude_dirs": self.exclude_dirs,
            "default_format": self.default_format,
            "default_max_lines": self.default_max_lines,
            "default_max_tokens": self.default_max_tokens,
            "heuristic_weights": {
                "position_weight": self.heuristic_weights.position_weight,
                "length_penalty": self.heuristic_weights.length_penalty,
                "role_bonus": self.heuristic_weights.role_bonus,
                "complexity_bonus": self.heuristic_weights.complexity_bonus,
                "export_bonus": self.heuristic_weights.export_bonus,
            },
            "fallback_parser": self.fallback_parser,
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

# Глобальный инстанс (лениво инициализируется)
_config: Optional[Config] = None

def get_config() -> Config:
    """Получить глобальный конфиг (ленивая загрузка)"""
    global _config
    if _config is None:
        _config = Config.load()
    return _config

def set_config(config: Config):
    """Установить глобальный конфиг (для тестов)"""
    global _config
    _config = config
