"""Instagram account discovery backed by the existing Facebook Login connection."""
from __future__ import annotations

from typing import Any

from app.services import instagram_r2_storage
from app.services import facebook_auth


def accounts() -> list[dict[str, str]]:
    result = []
    for page in facebook_auth.pages():
        instagram_user_id = str(page.get("instagram_user_id") or "").strip()
        if not instagram_user_id:
            continue
        result.append({
            "instagram_user_id": instagram_user_id,
            "instagram_username": str(page.get("instagram_username") or "Instagram account"),
            "page_id": str(page["id"]),
            "page_name": str(page["name"]),
        })
    return result


def selected_account(instagram_user_id: str) -> dict[str, Any] | None:
    return next((item for item in accounts() if item["instagram_user_id"] == instagram_user_id), None)


def status() -> dict[str, Any]:
    meta = facebook_auth.status()
    linked = accounts()
    if not meta["configured"]:
        message = "Meta app credentials are not configured."
    elif linked:
        message = "Connected to linked Instagram professional accounts."
    elif meta["connected"]:
        message = "Reconnect Meta to grant Instagram publishing access, and confirm the professional account is linked to a Facebook Page."
    else:
        message = "Connect the Facebook account that manages the Page linked to your Instagram professional account."
    return {
        "configured": meta["configured"],
        "connected": bool(linked),
        "authorization_pending": meta["authorization_pending"],
        "authorization_error": meta["authorization_error"],
        "accounts": linked,
        "r2_storage_configured": instagram_r2_storage.configured(),
        "message": message,
    }
