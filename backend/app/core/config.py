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

    settings = Settings(
        app_env=app_env,
        database_url=database_url,
        secret_key=secret_key,
        field_encryption_key=field_encryption_key,
        admin_username=admin_username,
        admin_password=admin_password,
    )

    if settings.is_prod:
        missing: list[str] = []
        if not settings.secret_key:
            missing.append("SECRET_KEY")
        if not settings.field_encryption_key:
            missing.append("FIELD_ENCRYPTION_KEY")
        if not settings.admin_password:
            missing.append("ADMIN_PASSWORD")
        if missing:
            raise ValueError(f"Missing required env vars for prod: {', '.join(missing)}")

    return settings
