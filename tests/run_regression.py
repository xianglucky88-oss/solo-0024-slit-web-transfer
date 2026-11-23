#!/usr/bin/env python3
"""可重复跑的绕向翻转回归入口。

用法（在仓库根目录）：

    python3 tests/run_regression.py

在临时 SQLite 成果库与临时回环端口上跑完整套件：
端到端 HTTP（evaluate/seal/compare/export）、实物不变量与断言强度金丝雀。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT / "tests"), pattern="test_*.py",
                            top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
