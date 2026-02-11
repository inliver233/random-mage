from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    database_url: str
    secret_key: str
    field_encryption_key: str
    admin_username: str
    admin_password: str
    pixiv_oauth_client_id: str
    pixiv_oauth_client_secret: str
    pixiv_oauth_hash_secret: str
    imgproxy_base_url: str
    imgproxy_key: str
    imgproxy_salt: str
    imgproxy_max_dim: int
    imgproxy_default_options: str
    imgproxy_url_chunk_size: int

    @property
    def is_prod(self) -> bool:
        return self.app_env in {"prod", "production"}


def _get(env: Mapping[str, str], key: str, default: str) -> str:
    value = env.get(key, default)
    return value.strip()


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = env or os.environ

    app_env = _get(env, "APP_ENV", "dev").lower()
    database_url = _get(env, "DATABASE_URL", "sqlite+aiosqlite:///./data/app.db")
    secret_key = _get(env, "SECRET_KEY", "dev-secret-key" if app_env != "prod" else "")
    field_encryption_key = _get(env, "FIELD_ENCRYPTION_KEY", "")

    admin_username = _get(env, "ADMIN_USERNAME", "admin")
    admin_password = _get(env, "ADMIN_PASSWORD", "admin" if app_env != "prod" else "")

    pixiv_oauth_client_id = _get(env, "PIXIV_OAUTH_CLIENT_ID", "")
    pixiv_oauth_client_secret = _get(env, "PIXIV_OAUTH_CLIENT_SECRET", "")
    pixiv_oauth_hash_secret = _get(env, "PIXIV_OAUTH_HASH_SECRET", "")

    imgproxy_base_url = _get(env, "IMGPROXY_BASE_URL", "")
    imgproxy_key = _get(env, "IMGPROXY_KEY", "")
    imgproxy_salt = _get(env, "IMGPROXY_SALT", "")
    try:
        imgproxy_max_dim = int(_get(env, "IMGPROXY_MAX_DIM", "2048") or "2048")
    except Exception:
        imgproxy_max_dim = 2048
    imgproxy_max_dim = max(16, min(int(imgproxy_max_dim), 20_000))

    imgproxy_default_options = _get(env, "IMGPROXY_DEFAULT_OPTIONS", "")

    try:
        imgproxy_url_chunk_size = int(_get(env, "IMGPROXY_URL_CHUNK_SIZE", "16") or "16")
    except Exception:
        imgproxy_url_chunk_size = 16
    imgproxy_url_chunk_size = max(0, min(int(imgproxy_url_chunk_size), 128))

    settings = Settings(
        app_env=app_env,
        database_url=database_url,
        secret_key=secret_key,
        field_encryption_key=field_encryption_key,
        admin_username=admin_username,
        admin_password=admin_password,
        pixiv_oauth_client_id=pixiv_oauth_client_id,
        pixiv_oauth_client_secret=pixiv_oauth_client_secret,
        pixiv_oauth_hash_secret=pixiv_oauth_hash_secret,
        imgproxy_base_url=imgproxy_base_url,
        imgproxy_key=imgproxy_key,
        imgproxy_salt=imgproxy_salt,
        imgproxy_max_dim=imgproxy_max_dim,
        imgproxy_default_options=imgproxy_default_options,
        imgproxy_url_chunk_size=imgproxy_url_chunk_size,
    )

    if settings.is_prod:
        missing: list[str] = []
        if not settings.secret_key:
            missing.append("SECRET_KEY")
        if not settings.field_encryption_key:
            missing.append("FIELD_ENCRYPTION_KEY")
        if not settings.admin_password:
            missing.append("ADMIN_PASSWORD")
        if settings.imgproxy_base_url and (not settings.imgproxy_key or not settings.imgproxy_salt):
            missing.append("IMGPROXY_KEY/IMGPROXY_SALT")
        if missing:
            raise ValueError(f"Missing required env vars for prod: {', '.join(missing)}")

    return settings
