"""把存量数据集的扫描流程改绑到预置标准流程。

默认 dry-run，只输出「数据集 → 建议预置流程」映射，不写入。
确认映射后加 --apply 执行改绑（只改数据集的 scan_protocol_id 元数据，
不动病例影像与标注）。预置流程缺失时会先按启动逻辑补种（只增不改）。

    cd backend
    uv run python scripts/apply_preset_protocols.py                     # dry-run
    uv run python scripts/apply_preset_protocols.py --apply             # 执行改绑
    uv run python scripts/apply_preset_protocols.py --dataset idc --apply  # 只处理编码含 idc 的数据集

匹配规则（见 app/domain/protocol_presets.py::suggest_preset_code）：
按数据集名称中的部位关键词（头部/胸部/腹部/盆腔…，靠前规则优先）+
数据集模态，建议该部位最通用的预置流程；无命中或模态不兼容则保持原流程。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, init_db  # noqa: E402
from app.domain.protocol_presets import suggest_preset_code  # noqa: E402
from app.main import bootstrap_protocols  # noqa: E402
from app.models import Dataset, ScanProtocol  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="存量数据集扫描流程改绑到预置标准流程")
    parser.add_argument("--apply", action="store_true", help="实际改绑（缺省只做 dry-run）")
    parser.add_argument(
        "--dataset",
        default="",
        help="只处理 code/id 包含该子串的数据集（如 --dataset idc）",
    )
    args = parser.parse_args()

    init_db()
    bootstrap_protocols()  # 确保预置流程已存在（幂等，只增不改）

    changed = 0
    skipped = 0
    with SessionLocal() as db:
        protocols = {
            p.code: p for p in db.scalars(select(ScanProtocol)).all()
        }
        query = db.scalars(select(Dataset).order_by(Dataset.code)).all()
        for dataset in query:
            if args.dataset and args.dataset not in dataset.code and args.dataset != dataset.id:
                continue
            suggestion = suggest_preset_code(dataset.name, dataset.modality)
            current = dataset.scan_protocol.code if dataset.scan_protocol else "（无）"
            if not suggestion or suggestion not in protocols:
                print(f"[跳过] {dataset.code}（{dataset.modality}）{dataset.name}"
                      f"：无匹配的预置流程，保持 {current}")
                skipped += 1
                continue
            target = protocols[suggestion]
            if dataset.scan_protocol_id == target.id:
                print(f"[不变] {dataset.code}（{dataset.modality}）已绑定 {target.name}")
                continue
            print(f"[改绑] {dataset.code}（{dataset.modality}）{dataset.name}"
                  f"：{current} -> {target.name}（{target.code}）")
            if args.apply:
                dataset.scan_protocol_id = target.id
            changed += 1

        if args.apply and changed:
            db.commit()

    mode = "已改绑" if args.apply else "dry-run 预计改绑"
    print(f"\n{mode} {changed} 个数据集，跳过 {skipped} 个。"
          if changed or skipped else "没有需要处理的数据集。")
    if changed and not args.apply:
        print("确认映射无误后加 --apply 执行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
