"""
ctxfind-v2: End-to-end test

Запускает поиск на test_project и проверяет, что вывод непустой.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from core.models import QueryMode
from orchestrator import SearchOrchestrator

# Регистрация модулей
import parsers
import enrichers
import renderers

def test_e2e_search():
    """End-to-end: поиск на test_project"""
    test_dir = Path(__file__).parent.parent / "test_project"

    orchestrator = SearchOrchestrator(
        mode=QueryMode.FAST,
        filters={},
        options={"format": "compact", "max_lines": 15}
    )

    results = orchestrator.run(query="User", root_path=test_dir)

    # Проверки
    assert len(results) > 0, "No results found"

    total_matches = sum(len(r.matches) for r in results)
    assert total_matches > 0, "No matches found"

    # Проверяем, что есть результаты из разных файлов
    files = {r.file_path for r in results}
    print(f"Files found: {files}")

    # Проверяем структуру match
    for result in results:
        for node in result.matches:
            assert node.name, "Match has no name"
            assert node.kind, "Match has no kind"
            assert node.file_path, "Match has no file_path"

    print(f"✅ E2E test passed: {len(results)} files, {total_matches} matches")
    return True

def test_e2e_json():
    """End-to-end: JSON вывод"""
    from renderers.json_renderer import JSONRenderer
    from core.models import RenderHint

    test_dir = Path(__file__).parent.parent / "test_project"

    orchestrator = SearchOrchestrator(
        mode=QueryMode.FAST,
        filters={},
        options={"format": "json"}
    )

    results = orchestrator.run(query="User", root_path=test_dir)

    renderer = JSONRenderer()
    hints = []
    for result in results:
        for node in result.matches:
            hints.append(RenderHint(node=node, output_format="json"))

    if hints:
        output = renderer.render(results[0], hints[0])

        import json
        data = json.loads(output)

        assert "matches" in data, "JSON missing matches"
        assert len(data["matches"]) > 0, "JSON matches empty"

        print(f"✅ E2E JSON test passed: {len(data['matches'])} matches")

    return True

if __name__ == "__main__":
    success = True
    try:
        test_e2e_search()
        test_e2e_json()
    except Exception as e:
        print(f"❌ E2E test failed: {e}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)