
"""
ctxfind-v2: Heuristic Scorer (v1 Logic Port)

Стратегия:
- Переносит эвристики из v1 без изменения их математики
- Работает ТОЛЬКО с мета-данными, не трогает исходный код/контекст
- Добавляет scoring к ParseResult и role-метки к CodeNode.meta
- Конфигурируемые веса для тонкой настройки без переписывания кода
"""

import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from core.models import ParseResult, CodeNode, Span
from core.interfaces import BaseEnricher
from core.registry import register_enricher
from config import get_config, HeuristicWeights


class HeuristicScorer:
    """
    Реализация BaseEnricher: добавляет эвристики и скоринг.
    """

    name = "v1-heuristics"
    runs_after = []  # Запускать сразу после парсеров
    enabled_by_default = True

    def __init__(self, weights: Optional[HeuristicWeights] = None):
        self.weights = weights or get_config().heuristic_weights
        # Компиляция regex-паттернов для role detection (один раз)
        self._role_patterns = self._compile_role_patterns()

    def enrich(
        self,
        result: ParseResult,
        options: Optional[Dict[str, Any]] = None
    ) -> ParseResult:
        """
        Прогнать все matches через эвристики, обновить meta и heuristics.
        """
        if not result.matches:
            return result

        updated_matches = []
        for node in result.matches:
            # 1. Рассчитать локальные метрики
            metrics = self._calculate_node_metrics(node)
            node = node.with_meta(**metrics)

            # 2. Определить семантическую роль (<< def, >> use, >< mod)
            role = self._detect_role(node)
            node = node.with_meta(v1_role=role)

            # 3. Рассчитать скоринг узла
            node_score = self._score_node(node)
            node = node.with_meta(v1_node_score=node_score)

            updated_matches.append(node)

        result.matches = updated_matches

        # 4. Глобальный скоринг результата
        result.heuristics["v1_relevance"] = self._aggregate_score(result)

        # 5. Сортировка по релевантности
        result.matches.sort(
            key=lambda n: n.meta.get("v1_node_score", 0.0),
            reverse=True
        )

        return result

    # ─── Логика эвристик ──────────────────────────────────────────────────

    def _calculate_node_metrics(self, node: CodeNode) -> Dict[str, Any]:
        """
        Простые метрики из v1:
        - line_count
        - query_relative_position (0.0..1.0)
        - is_top_level
        """
        lines = node.context_code.splitlines()
        line_count = len(lines)

        # Позиция query относительно начала узла
        rel_pos = 0.5
        for i, line in enumerate(lines):
            if node.name in line:
                rel_pos = i / max(line_count, 1)
                break

        return {
            "line_count": line_count,
            "query_relative_position": rel_pos,
            "is_top_level": node.span.start_line < 5,
            "context_density": self._calc_density(node.context_code),
        }

    def _detect_role(self, node: CodeNode) -> str:
        """
        Эвристика ролей из v1:
        - "<< def" : определение
        - ">> use" : использование
        - ">< mod" : модификатор/переопределение
        """
        existing = node.meta.get("v1_role")
        if existing:
            return existing

        context = node.context_code
        name = re.escape(node.name)

        # Паттерны определения
        def_patterns = [
            rf"^\s*(?:def|class|const|let|var|function)\s+{name}\b",
            rf"^\s*\.?{name}\s*\{{",
            rf"^\s*{name}\s*:\s*",
        ]

        for pattern in def_patterns:
            if re.search(pattern, context, re.MULTILINE):
                return "<< def"

        # Паттерны использования
        use_patterns = [
            rf"\b{name}\b\s*\(",
            rf"import\s+\S*\b{name}\b",
            rf"from\s+\S+\s+import\s+.*\b{name}\b",
        ]

        for pattern in use_patterns:
            if re.search(pattern, context, re.MULTILINE):
                return ">> use"

        return "<< def"

    def _score_node(self, node: CodeNode) -> float:
        """
        Формула скоринга одного узла.
        """
        metrics = node.meta
        role = metrics.get("v1_role", ">> use")

        pos_score = max(0.0, 1.0 - metrics.get("query_relative_position", 0.5))
        line_count = metrics.get("line_count", 10)
        len_score = max(0.0, 1.0 - (line_count / 100))
        role_score = self.weights.role_bonus if role == "<< def" else 0.1
        export_score = self.weights.export_bonus if metrics.get("is_exported") else 0.0
        complexity = metrics.get("complexity", 0)
        complexity_score = min(complexity / 50, 1.0) * self.weights.complexity_bonus

        score = (
            pos_score * self.weights.position_weight +
            len_score * self.weights.length_penalty +
            role_score +
            export_score +
            complexity_score
        )

        return min(1.0, max(0.0, score))

    def _aggregate_score(self, result: ParseResult) -> float:
        """
        Глобальная релевантность файла/результата.
        """
        if not result.matches:
            return 0.0
        max_node_score = max(n.meta.get("v1_node_score", 0) for n in result.matches)
        count_bonus = min(len(result.matches) * 0.05, 0.2)
        return min(1.0, max_node_score + count_bonus)

    def _compile_role_patterns(self) -> Dict[str, re.Pattern]:
        """Компиляция regex для role detection"""
        return {
            "def": re.compile(r"^\s*(?:def|class|const|let|var|function)\s+\b{}\b", re.M),
            "use": re.compile(r"\b{}\b\s*\(", re.M),
        }

    @staticmethod
    def _calc_density(code: str) -> float:
        """Отношение meaningful lines к total lines"""
        lines = code.splitlines()
        if not lines:
            return 0.0

        meaningful = 0
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            meaningful += 1

        return meaningful / len(lines)


# Регистрация
register_enricher("v1-heuristics", HeuristicScorer)
