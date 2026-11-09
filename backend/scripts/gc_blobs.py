"""清理没有被任何 CaseAsset 引用的孤立 Blob。默认 dry-run。"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Blob, CaseAsset, as_utc  # noqa: E402
from app.services import storage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--older-than-days", type=int, default=0)
    args = parser.parse_args()
    init_db()

    cutoff = datetime.now(UTC) - timedelta(days=max(0, args.older_than_days))
    with SessionLocal() as db:
        referenced = set(db.scalars(select(CaseAsset.blob_id)).all())
        blobs = db.scalars(select(Blob)).all()
        orphans = [blob for blob in blobs if blob.id not in referenced]
        if args.older_than_days:
            orphans = [blob for blob in orphans if (as_utc(blob.created_at) or cutoff) <= cutoff]

        total = sum(blob.size_bytes for blob in orphans)
        print(f"孤立 Blob：{len(orphans)} 个，{total / 1024**3:.2f} GB")
        if not args.apply:
            print("dry-run，未删除；确认后加 --apply")
            return 0

        for blob in orphans:
            path = storage.resolve_key(blob.storage_key)
            path.unlink(missing_ok=True)
            db.delete(blob)
        db.commit()
        print(f"已删除 {len(orphans)} 个 Blob")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
