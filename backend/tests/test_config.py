import pytest

from app.core.config import load_settings


def test_load_settings_dev_defaults() -> None:
    s = load_settings({})
    assert s.app_env == "dev"
    assert s.database_url
    assert s.secret_key
    assert s.admin_username == "admin"
    assert s.admin_password == "admin"


def test_load_settings_prod_requires_secrets() -> None:
    with pytest.raises(ValueError):
        load_settings({"APP_ENV": "prod"})

