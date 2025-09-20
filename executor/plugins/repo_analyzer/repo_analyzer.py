
"""
Repo Analyzer plugin
Scans Python files under the executor/ directory and builds a map of
- functions
- classes
- imports
"""

import os
import ast
from pathlib import Path


def analyze_repo(root: str = "executor") -> dict:
    results = {}
    for py in Path(root).rglob("*.py"):
        try:
            with open(py, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(py))
            funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
            classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
            imports = [
                n.module
                for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module
            ]
            results[str(py)] = {
                "functions": funcs,
                "classes": classes,
                "imports": imports,
            }
        except Exception:
            continue
    return results


def run():
    return {"status": "ok", "analysis": analyze_repo()}
