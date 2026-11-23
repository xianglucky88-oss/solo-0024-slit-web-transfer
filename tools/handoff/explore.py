"""探索脚本：把三个有效复核输入跑过 Workbench，打印全部产出，供资料包设计核对。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from slitweb.archive import Archive  # noqa: E402
from slitweb.server import CONFIG  # noqa: E402
from slitweb.service import Workbench  # noqa: E402

NAMES = ["sample", "review-sample", "review-alternate"]


def main():
    wb = Workbench(Archive(":memory:"), CONFIG)
    for name in NAMES:
        source = json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf8"))
        packet = wb.analyze(source)
        print("=" * 90)
        print("INPUT", name, "subject=", packet["subject"], "digest=", packet["digest"][:16])
        print("-" * 90)
        for key, value in packet["outputs"].items():
            print(f"## {key}")
            print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
