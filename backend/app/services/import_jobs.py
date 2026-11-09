"""后台导入任务：单进程线程池执行，避免 5TB 级导入占用 HTTP 请求。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..models import Dataset, ImportJob
from .import_service import import_from_path

logger = logging.getLogger("medpowers.studio.import")

_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(1, int(get_settings().import_job_workers)),
    thread_name_prefix="mps-import",
)


def submit(job_id: str) -> None:
    _EXECUTOR.submit(_run, job_id)


def _run(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(ImportJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "running"
        job.started_at = datetime.now(UTC)
        db.commit()

        try:
            dataset = db.get(Dataset, job.dataset_id)
            if dataset is None:
                raise ValueError("数据集不存在")
            report = import_from_path(
                db,
                dataset,
                job.source_path,
                recursive=job.recursive,
                acknowledge_source_discarded=True,
            )
            job = db.get(ImportJob, job_id)
            if job is None:
                return
            job.imported = report.imported
            job.skipped = report.skipped
            job.converted = report.converted
            job.stored_bytes = report.stored_bytes
            job.report = report.model_dump()
            job.status = "succeeded"
            job.finished_at = datetime.now(UTC)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("导入任务 %s 失败", job_id)
            db.rollback()
            job = db.get(ImportJob, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = datetime.now(UTC)
            db.commit()


def recover_interrupted_jobs() -> None:
    """服务重启后，把中断的 running 任务标记为失败，避免前端永久等待。"""

    with SessionLocal() as db:
        jobs = db.scalars(select(ImportJob).where(ImportJob.status == "running")).all()
        for job in jobs:
            job.status = "failed"
            job.error = "服务重启导致导入中断，请重新提交"
            job.finished_at = datetime.now(UTC)
        if jobs:
            db.commit()
