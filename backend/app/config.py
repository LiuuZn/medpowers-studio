from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

INSECURE_JWT_SECRETS = {
    "dev-only-change-me-please-use-32-bytes-or-more",
    "change-me-in-production-use-32-bytes-minimum",
}


class Settings(BaseSettings):
    """平台配置。所有字段都可以通过 MEDPOWERS_ 前缀的环境变量覆盖。"""

    model_config = SettingsConfigDict(env_prefix="MEDPOWERS_", env_file=".env", extra="ignore")

    app_name: str = "MedPowers Studio"
    api_prefix: str = "/api"
    environment: Literal["development", "production"] = "development"

    database_url: str = f"sqlite:///{BASE_DIR / 'medpowers_studio.db'}"
    storage_root: Path = BASE_DIR / "storage"
    max_upload_mb: int = 4096
    # 导入前要求存储卷保留的最小空闲空间，避免 5TB 级导入把磁盘写满。
    storage_min_free_gb: int = 50
    # 默认只保留规范化格式；开启后可在 Blob 中额外保留原始文件（后续扩展）。
    keep_originals: bool = False
    import_job_workers: int = 1

    jwt_secret: str = "dev-only-change-me-please-use-32-bytes-or-more"
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "medpowers-studio"
    jwt_audience: str = "medpowers-studio-api"
    access_token_expire_minutes: int = 12 * 60

    # 对外访问地址，用于设备码授权页面的完整链接；为空时按请求 Host 推导。
    public_base_url: str = ""
    # 可选的主机名白名单（反向代理/域名部署时建议配置）。
    allowed_hosts: list[str] = []
    # 仅在明确由 HTTPS 反向代理提供 TLS 时开启 HSTS。
    enable_hsts: bool = False

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str = "admin123"
    bootstrap_admin_display_name: str = "平台管理员"
    patient_salt: str = "medpowers-studio"

    # API 访问令牌 / 设备码授权
    api_token_default_expire_days: int = 90
    api_token_max_expire_days: int = 365
    device_code_expire_seconds: int = 600
    device_poll_interval_seconds: int = 5
    auth_rate_limit_per_minute: int = 20

    slice_cache_volumes: int = 4


@lru_cache
def get_settings() -> Settings:
    return Settings()
