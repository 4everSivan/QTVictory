"""T03-1 / T04-1：领域内核纯度——不依赖 fastapi / sqlite / httpx / store（02 §2.3）。

静态分析（AST）内核模块的全部 import：仅允许 stdlib 与 app.domain.*。
"""

import ast
from pathlib import Path

DOMAIN_DIR = Path(__file__).resolve().parents[2] / "app" / "domain"
FORBIDDEN_TOPS = {"fastapi", "httpx", "uvicorn", "pydantic", "sqlite3", "app"}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module)
    return roots


def _violations(roots: set[str]) -> set[str]:
    bad: set[str] = set()
    for r in roots:
        top = r.split(".")[0]
        if top in FORBIDDEN_TOPS:
            if top != "app" or not (r == "app.domain" or r.startswith("app.domain.")):
                bad.add(r)
    return bad


def test_domain_modules_are_pure():
    assert DOMAIN_DIR.exists() and any(DOMAIN_DIR.glob("*.py"))
    offenders: dict[str, set[str]] = {}
    for path in sorted(DOMAIN_DIR.glob("*.py")):
        bad = _violations(_imported_roots(path))
        if bad:
            offenders[path.name] = bad
    assert offenders == {}, f"domain 内核引入了框架/存储依赖: {offenders}"
