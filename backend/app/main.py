from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text

from .api import (
    admin,
    annotations,
    auth,
    cases,
    dashboard,
    datasets,
    evaluations,
    exports,
    meta,
    protocols,
    studio,
    tasks,
    users,
)
from .config import INSECURE_JWT_SECRETS, get_settings
from .db import SessionLocal, ensure_dirs, init_db
from .deps import enforce_token_scope
from .domain.protocol_presets import PRESET_SCAN_PROTOCOLS
from .models import ScanProtocol, User
from .security import hash_password
from .services import storage
from .services.auth_service import purge_expired_device_codes
from .services.import_jobs import recover_interrupted_jobs

logger = logging.getLogger("medpowers.studio")
settings = get_settings()


def validate_settings() -> None:
    if settings.environment != "production":
        if settings.jwt_secret in INSECURE_JWT_SECRETS:
            logger.warning("当前使用默认 JWT secret，仅适合开发环境；部署前请修改")
        return
    if settings.jwt_secret in INSECURE_JWT_SECRETS or len(settings.jwt_secret) < 32:
        raise RuntimeError(
            "生产环境必须设置至少 32 字节的 MEDPOWERS_JWT_SECRET，"
            "且不能使用示例默认值"
        )
    if settings.bootstrap_admin_password == "admin123":
        logger.warning("生产环境仍在使用默认管理员密码 admin123，请立即修改")


def bootstrap_admin() -> None:
    with SessionLocal() as db:
        count = int(db.scalar(select(func.count()).select_from(User)) or 0)
        if count:
            return
        admin = User(
            username=settings.bootstrap_admin_username,
            display_name=settings.bootstrap_admin_display_name,
            password_hash=hash_password(settings.bootstrap_admin_password),
            role="admin",
        )
        db.add(admin)
        db.commit()
        logger.warning(
            "已创建初始管理员账号 %s，请尽快登录后修改密码",
            settings.bootstrap_admin_username,
        )
        if settings.bootstrap_admin_password == "admin123":
            logger.warning("初始管理员密码为默认值 admin123，生产环境务必通过环境变量覆盖")


def bootstrap_protocols() -> None:
    """补种预置扫描流程字典，保持“每个数据集绑定流程”的规则。

    按 code 幂等：只创建缺失的预置流程，不覆盖管理员对已有流程的修改
    （改名、停用、调整适用模态等）。预置清单见 app/domain/protocol_presets.py。
    """

    with SessionLocal() as db:
        existing = set(db.scalars(select(ScanProtocol.code)).all())
        missing = [preset for preset in PRESET_SCAN_PROTOCOLS if preset.code not in existing]
        if not missing:
            return
        for preset in missing:
            db.add(
                ScanProtocol(
                    code=preset.code,
                    name=preset.name,
                    description=preset.description,
                    modality_scope=list(preset.modality_scope),
                    sort_order=preset.sort_order,
                    is_active=True,
                )
            )
        db.commit()
        logger.info(
            "已补种 %d 个预置扫描流程：%s",
            len(missing),
            "、".join(preset.name for preset in missing),
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_settings()
    init_db()
    ensure_dirs()
    bootstrap_admin()
    bootstrap_protocols()
    recover_interrupted_jobs()
    with SessionLocal() as db:
        purge_expired_device_codes(db)
    logger.info(
        "MedPowers Studio 已启动（environment=%s，public_base_url=%s）",
        settings.environment,
        settings.public_base_url or "由请求 Host 推导",
    )
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "医疗影像数据管理、标注、训练数据导出与评估一体化平台。\n\n"
            "网页端使用 JWT；训练仓库/插件使用 `Authorization: Bearer <API token>`，"
            "令牌按 `studio:read` / `studio:data` / `studio:experiment` / "
            "`studio:evaluate` / `studio:review-request` scope 限制权限。"
        ),
        lifespan=lifespan,
    )
    if settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        if request.url.path.startswith(f"{settings.api_prefix}/auth"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        if settings.enable_hsts and request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    prefix = settings.api_prefix
    api_router = APIRouter(prefix=prefix, dependencies=[Depends(enforce_token_scope)])
    api_router.include_router(auth.router)
    api_router.include_router(users.router)
    api_router.include_router(protocols.router)
    api_router.include_router(datasets.router)
    api_router.include_router(cases.router)
    api_router.include_router(tasks.router)
    api_router.include_router(annotations.task_router)
    api_router.include_router(annotations.annotation_router)
    api_router.include_router(exports.router)
    api_router.include_router(evaluations.router)
    api_router.include_router(dashboard.router)
    api_router.include_router(meta.router)
    api_router.include_router(studio.router)
    api_router.include_router(admin.router)
    app.include_router(api_router)

    @app.get(f"{prefix}/health", tags=["系统"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    @app.get(f"{prefix}/health/ready", tags=["系统"])
    def health_ready() -> dict[str, object]:
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
            probe = storage.tmp_dir("healthcheck") / "probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            usage = storage.disk_usage()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"服务未就绪：{exc}") from exc
        return {"status": "ready", "service": settings.app_name, "storage": usage}

    frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if frontend_dist.exists():

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            candidate = (frontend_dist / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(frontend_dist):
                return FileResponse(candidate)
            return FileResponse(frontend_dist / "index.html")

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
