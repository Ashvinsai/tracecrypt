"""B08: a placeholder secret must not boot outside dev."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.settings import AppEnv, Settings


def test_placeholder_secret_rejected_outside_dev() -> None:
    for env in (AppEnv.test, AppEnv.prod):
        with pytest.raises(ValidationError, match="placeholder"):
            Settings(app_env=env, secret_key="change-me", _env_file=None)


def test_short_secret_rejected_outside_dev() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        Settings(app_env=AppEnv.prod, secret_key="short-but-not-a-placeholder", _env_file=None)


def test_dev_default_is_allowed_only_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CFA_SECRET_KEY", raising=False)
    settings = Settings(app_env=AppEnv.dev, _env_file=None)
    assert settings.secret_key == "dev-secret-not-for-production"


def test_api_key_is_not_repr_printed() -> None:
    """T11: a secret must not leak through a repr in a log line."""
    settings = Settings(app_env=AppEnv.dev, tron_api_key="super-secret-key", _env_file=None)
    assert "super-secret-key" not in repr(settings)
