"""让 `python3 -m pytest scripts/tests -q` 能直接 import 被测脚本。

scripts/ 不是包（无 __init__.py），pytest 默认只把测试文件所在目录
scripts/tests 插入 sys.path。这里显式补上 scripts/，测试里即可
`import jev_workflow_check`。
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
