"""
ctxfind-v2: Integration Tests

Тестируем полный пайплайн: CLI → Orchestrator → Parser → Enricher → Renderer
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from core.models import QueryMode, ParseResult
from core.registry import parsers as registry_parsers, enrichers as registry_enrichers, renderers as registry_renderers
from orchestrator import SearchOrchestrator, prepare_render_hints
from config import Config, set_config

# Регистрируем все модули (импорт запускает регистрацию)
import parsers
import enrichers
import renderers


def test_registry_populated():
    """Проверить, что все модули зарегистрированы"""
    print("\n📝 Registry check:")
    print(f"   Parsers: {registry_parsers.list()}")
    print(f"   Enrichers: {registry_enrichers.list()}")
    print(f"   Renderers: {registry_renderers.list()}")

    assert "regex-fallback" in registry_parsers.list(), "RegexFallbackParser not registered"
    assert "tree-sitter" in registry_parsers.list(), "TreeSitterParser not registered"
    assert "v1-heuristics" in registry_enrichers.list(), "HeuristicScorer not registered"
    assert "text-compact" in registry_renderers.list(), "TextCompactRenderer not registered"
    print("   ✅ All modules registered")


def test_fallback_parser_python():
    """Тест RegexFallbackParser на Python файле"""
    print("\n🔍 Fallback parser test (Python):")

    from parsers.regex_fallback import RegexFallbackParser

    parser = RegexFallbackParser()
    test_file = Path(__file__).parent.parent / "test_project" / "user_service.py"
    content = test_file.read_text()

    result = parser.parse(
        file_path=str(test_file),
        content=content,
        query="User",
        mode=QueryMode.FAST
    )

    print(f"   Matches: {len(result.matches)}")
    print(f"   Warnings: {result.warnings}")

    assert len(result.matches) > 0, "No matches found"

    for node in result.matches:
        print(f"   - {node.kind}: {node.name} @ {node.file_path}:{node.span.start_line + 1}")
        print(f"     role: {node.meta.get('v1_role')}, confidence: {node.meta.get('confidence')}")

    print("   ✅ Fallback parser works")
    return result


def test_fallback_parser_js():
    """Тест RegexFallbackParser на JS файле"""
    print("\n🔍 Fallback parser test (JavaScript):")

    from parsers.regex_fallback import RegexFallbackParser

    parser = RegexFallbackParser()
    test_file = Path(__file__).parent.parent / "test_project" / "user_manager.js"
    content = test_file.read_text()

    result = parser.parse(
        file_path=str(test_file),
        content=content,
        query="User",
        mode=QueryMode.FAST
    )

    print(f"   Matches: {len(result.matches)}")

    for node in result.matches:
        print(f"   - {node.kind}: {node.name} @ {node.file_path}:{node.span.start_line + 1}")

    assert len(result.matches) > 0, "No matches found in JS"
    print("   ✅ Fallback parser works for JS")
    return result


def test_enricher_scoring():
    """Тест HeuristicScorer"""
    print("\n📊 Enricher scoring test:")

    from enrichers.heuristic_scorer import HeuristicScorer

    # Берём результат из предыдущего теста
    from parsers.regex_fallback import RegexFallbackParser
    parser = RegexFallbackParser()
    test_file = Path(__file__).parent.parent / "test_project" / "user_service.py"
    content = test_file.read_text()
    result = parser.parse(str(test_file), content, "User", QueryMode.FAST)

    scorer = HeuristicScorer()
    enriched = scorer.enrich(result)

    print(f"   Relevance: {enriched.heuristics.get('v1_relevance', 0):.3f}")
    print(f"   Matches after scoring: {len(enriched.matches)}")

    for node in enriched.matches:
        score = node.meta.get("v1_node_score", 0)
        print(f"   - {node.name} ({node.kind}): score={score:.3f}")

    assert "v1_relevance" in enriched.heuristics
    print("   ✅ Scoring works")
    return enriched


def test_renderer_compact():
    """Тест TextCompactRenderer"""
    print("\n🎨 Renderer compact test:")

    from renderers.text_compact import TextCompactRenderer
    from core.models import RenderHint, CodeNode, Span

    renderer = TextCompactRenderer()

    # Берём обогащённый результат
    from parsers.regex_fallback import RegexFallbackParser
    from enrichers.heuristic_scorer import HeuristicScorer

    parser = RegexFallbackParser()
    test_file = Path(__file__).parent.parent / "test_project" / "user_service.py"
    content = test_file.read_text()
    result = parser.parse(str(test_file), content, "User", QueryMode.FAST)
    result = HeuristicScorer().enrich(result)

    # Создаём hint для первого match
    if result.matches:
        hint = RenderHint(
            node=result.matches[0],
            max_lines=10,
            output_format="compact"
        )

        output = renderer.render(result, hint)
        print("   Output:")
        for line in output.split("\n"):
            print(f"   | {line}")

        assert "User" in output
        print("   ✅ Compact renderer works")
    else:
        print("   ⚠️ No matches to render")


def test_orchestrator_end_to_end():
    """Тест полного пайплайна через оркестратор"""
    print("\n🚀 Orchestrator end-to-end test:")

    test_dir = Path(__file__).parent.parent / "test_project"

    orchestrator = SearchOrchestrator(
        mode=QueryMode.FAST,
        filters={"lang": "python"},
        options={"format": "compact", "max_lines": 15}
    )

    results = orchestrator.run(query="User", root_path=test_dir)

    print(f"   Results: {len(results)}")

    for result in results:
        print(f"   📄 {result.file_path}")
        print(f"      Matches: {len(result.matches)}")
        print(f"      Relevance: {result.heuristics.get('v1_relevance', 0):.3f}")
        for node in result.matches:
            print(f"      - {node.kind}: {node.name} (score: {node.meta.get('v1_node_score', 0):.3f})")

    assert len(results) > 0, "No results from orchestrator"
    print("   ✅ Orchestrator pipeline works")
    return results


def test_cli_simulation():
    """Симуляция CLI вызова"""
    print("\n🖥️  CLI simulation test:")

    from cli import main
    import io
    from contextlib import redirect_stdout

    test_dir = Path(__file__).parent.parent / "test_project"

    # Захватываем stdout
    captured = io.StringIO()

    try:
        with redirect_stdout(captured):
            exit_code = main([
                "User",
                str(test_dir),
                "--mode", "fast",
                "--format", "compact",
                "--lang", "python",
                "--max-lines", "10",
            ])
    except SystemExit as e:
        exit_code = e.code

    output = captured.getvalue()
    print(f"   Exit code: {exit_code}")
    print("   Output:")
    for line in output.split("\n")[:15]:
        if line.strip():
            print(f"   | {line}")

    assert exit_code == 0, f"CLI failed with exit code {exit_code}"
    assert "User" in output, "No User in output"
    print("   ✅ CLI simulation works")




def test_cross_name_linker():
    """Тест CrossNameLinker"""
    print("\n🔗 Cross-name linker test:")

    from parsers.regex_fallback import RegexFallbackParser
    from enrichers.heuristic_scorer import HeuristicScorer
    from enrichers.cross_name_linker import CrossNameLinker

    # Создаём два файла с пересекающимися именами
    py_content = """def validate(data): return True
class User: pass"""
    html_content = """<html><script>validate(form); var user = new User();</script></html>"""

    parser = RegexFallbackParser()
    py_result = parser.parse("test.py", py_content, "validate", QueryMode.FAST)
    html_result = parser.parse("test.html", html_content, "validate", QueryMode.FAST)

    py_result = HeuristicScorer().enrich(py_result)
    html_result = HeuristicScorer().enrich(html_result)

    results = [py_result, html_result]

    print(f"   Before: Python refs={len(py_result.matches[0].references)}, HTML refs={len(html_result.matches[0].references) if html_result.matches else 0}")

    linker = CrossNameLinker(options={"link_min_confidence": 0.3})
    linked = linker.enrich(results)

    print(f"   After: Python refs={len(linked[0].matches[0].references)}")
    for ref in linked[0].matches[0].references:
        print(f"      → {ref.target_name} in {ref.target_file}")

    assert len(linked[0].matches[0].references) > 0, "No cross-references added"
    print("   ✅ Cross-name linker works")


def run_all_tests():
    """Запустить все тесты"""
    print("=" * 60)
    print("ctxfind-v2 Integration Tests")
    print("=" * 60)

    tests = [
        test_registry_populated,
        test_fallback_parser_python,
        test_fallback_parser_js,
        test_enricher_scoring,
        test_renderer_compact,
        test_cross_name_linker,
        test_orchestrator_end_to_end,
        test_cli_simulation,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n   ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
