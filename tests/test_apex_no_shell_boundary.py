from pathlib import Path
import ast

def test_apex_has_no_shell_or_subprocess_execution_surface():
    root = Path(__file__).parents[1] / "apex"
    forbidden_imports = {"subprocess", "cmd", "pexpect"}
    forbidden_calls = {"system", "popen", "check_output", "Popen", "call"}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden_imports for alias in node.names), path
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden_imports, path
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "os":
                    assert node.func.attr not in {"system", "popen"}, path
