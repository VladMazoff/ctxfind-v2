"""
ctxfind-v2: JSON Renderer

Стратегия:
- Не пишем свою сериализацию
- dataclasses.asdict() + json.dumps(..., default=str)
- Обработка datetime/Path через default=str
"""

import json
import dataclasses
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from core.models import ParseResult, RenderHint, CodeNode
from core.registry import register_renderer
from renderers.base import BaseRendererImpl

class JSONRenderer(BaseRendererImpl):
    """
    JSON рендерер для машиночитаемого вывода и LLM-автоматизации.
    """

    name = "json"
    output_formats = ["json"]

    def _render_node(
        self,
        node: CodeNode,
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> str:
        """Отрендерить один узел как JSON-строку"""
        # Используем to_llm_dict() для чистого JSON
        data = node.to_llm_dict()

        # Добавляем render hints если нужно
        if options and options.get("include_hints"):
            data["render_hint"] = hint.to_dict()

        return json.dumps(data, indent=2, default=str, ensure_ascii=False)

    def _format_output(
        self,
        rendered_nodes: List[str],
        result: ParseResult,
        hint: RenderHint,
        options: Optional[Dict[str, Any]]
    ) -> str:
        """Финальное форматирование: массив JSON-объектов"""
        if not rendered_nodes:
            return json.dumps({"matches": [], "file": result.file_path}, indent=2)

        # Собираем структуру: файл + мета + массив matches
        output = {
            "file": result.file_path,
            "parser": result.parser_name,
            "query": result.query,
            "heuristics": dict(result.heuristics),
            "warnings": result.warnings,
            "matches": [],
        }

        # Парсим каждый rendered_node обратно в dict (чтобы собрать массив)
        for node_str in rendered_nodes:
            try:
                node_data = json.loads(node_str)
                output["matches"].append(node_data)
            except json.JSONDecodeError:
                continue

        return json.dumps(output, indent=2, default=str, ensure_ascii=False)

    def render_batch(
        self,
        results: List[ParseResult],
        hints: List[RenderHint],
        options: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Эффективный рендеринг нескольких результатов.
        Возвращает один JSON с массивом файлов.
        """
        output = {
            "query": results[0].query if results else "",
            "total_files": len(results),
            "total_matches": sum(len(r.matches) for r in results),
            "files": [],
        }

        for result in results:
            file_data = {
                "file": result.file_path,
                "parser": result.parser_name,
                "heuristics": dict(result.heuristics),
                "warnings": result.warnings,
                "matches": [m.to_llm_dict() for m in result.matches],
            }
            output["files"].append(file_data)

        return [json.dumps(output, indent=2, default=str, ensure_ascii=False)]

# Регистрация
register_renderer("json", JSONRenderer)
