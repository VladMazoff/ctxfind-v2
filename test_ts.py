# this is WORKING example parser for Python 3.8 !!!
# tree-sitter==0.20.4
# tree-sitter-languages==1.10.2
from tree_sitter_languages import get_parser

# 1. ПАРСИНГ PYTHON
python_code = b"""
def calculate_sum(a, b):
    result = a + b
    return result

print(calculate_sum(5, 3))
"""

python_parser = get_parser("python")
python_tree = python_parser.parse(python_code)

print("=" * 50)
print("PYTHON AST:")
print(python_tree.root_node.sexp())
print(f"Корневой узел: {python_tree.root_node.type}")


# 2. ПАРСИНГ JAVASCRIPT
js_code = b"""
function multiply(x, y) {
    const result = x * y;
    console.log(result);
    return result;
}

multiply(4, 7);
"""

js_parser = get_parser("javascript")
js_tree = js_parser.parse(js_code)

print("\n" + "=" * 50)
print("JAVASCRIPT AST:")
print(js_tree.root_node.sexp())
print(f"Корневой узел: {js_tree.root_node.type}")


# 3. ПАРСИНГ HTML
html_code = b"""
<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
</head>
<body>
    <h1>Hello World</h1>
    <p>This is a test</p>
    <script>
        console.log("embedded JS");
    </script>
</body>
</html>
"""

html_parser = get_parser("html")
html_tree = html_parser.parse(html_code)

print("\n" + "=" * 50)
print("HTML AST:")
print(html_tree.root_node.sexp())
print(f"Корневой узел: {html_tree.root_node.type}")