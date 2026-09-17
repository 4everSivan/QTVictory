"""纯度探针（test_purity.py 调用）：导入领域内核并输出意外加载的模块。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.domain.engine  # noqa: F401
import app.domain.plan_engine  # noqa: F401
import app.domain.strategies  # noqa: F401

FORBIDDEN_PREFIXES = ("fastapi", "httpx", "uvicorn", "app.store", "sqlite3")
loaded = sorted(m for m in sys.modules if m.split(".")[0] in FORBIDDEN_PREFIXES)
print(json.dumps(loaded))
