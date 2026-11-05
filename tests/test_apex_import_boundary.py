from pathlib import Path
import ast

def test_apex_package_does_not_import_aie():
    root = Path(__file__).parents[1] / "apex"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("aie") for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("aie"), path
