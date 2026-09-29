"""Response envelope. Every response declares its data mode and versions (D009)."""

from __future__ import annotations

from typing import Any

from app.core.settings import Settings


def meta(settings: Settings, request_id: str) -> dict[str, Any]:
    return {
        "data_mode": settings.data_mode.value,
        "request_id": request_id,
        "engine_version": settings.engine_version,
        "label_set_version": settings.label_set_version,
        "analysis_cutoff": settings.cutoff.isoformat(),
    }


def ok(data: Any, settings: Settings, request_id: str) -> dict[str, Any]:
    return {"data": data, "meta": meta(settings, request_id)}


def error(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}
