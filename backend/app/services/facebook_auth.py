"""Local Facebook OAuth and DPAPI-protected Page-token storage."""
from __future__ import annotations

import ctypes
import json
import os
import secrets
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from ctypes import POINTER, Structure, byref, c_byte, c_void_p, cast, create_string_buffer
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.storage import managed_directory

CALLBACK_BIND_HOST = "127.0.0.1"
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 8765
CALLBACK_PATH = "/api/social/facebook/callback"
FACEBOOK_PERMISSIONS = ("pages_show_list", "pages_read_engagement", "pages_manage_posts", "business_management")
INSTAGRAM_PERMISSIONS = ("instagram_basic", "instagram_content_publish")


def authorization_permissions(*, include_instagram: bool = False) -> tuple[str, ...]:
    """Request only the scopes needed by the platform being connected."""
    return FACEBOOK_PERMISSIONS + (INSTAGRAM_PERMISSIONS if include_instagram else ())
_lock = threading.Lock()
_pending: dict[str, Any] = {"state": None, "server": None, "thread": None, "error": None}


class FacebookAuthError(RuntimeError):
    pass


class _DataBlob(Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", POINTER(c_byte))]


def _blob(data: bytes):
    buffer = create_string_buffer(data)
    return _DataBlob(len(data), cast(buffer, POINTER(c_byte))), buffer


def _protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise FacebookAuthError("Secure Facebook credential storage is available only on Windows.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [POINTER(_DataBlob), wintypes.LPCWSTR, POINTER(_DataBlob), c_void_p, c_void_p, wintypes.DWORD, POINTER(_DataBlob)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [POINTER(_DataBlob), POINTER(wintypes.LPWSTR), POINTER(_DataBlob), c_void_p, c_void_p, wintypes.DWORD, POINTER(_DataBlob)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [c_void_p]
    kernel32.LocalFree.restype = c_void_p
    source, keepalive = _blob(data)
    output, description = _DataBlob(), ctypes.c_wchar_p()
    if decrypt:
        ok = crypt32.CryptUnprotectData(byref(source), byref(description), None, None, None, 0x1, byref(output))
    else:
        ok = crypt32.CryptProtectData(byref(source), "CLIPRA Facebook Page tokens", None, None, None, 0x1, byref(output))
    if not ok:
        raise FacebookAuthError("Windows could not protect or read the saved Facebook connection.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(c_void_p(cast(output.pbData, c_void_p).value))
        del keepalive


def _token_path() -> Path:
    return managed_directory("private/facebook") / "page-tokens.dpapi"


def _client() -> dict[str, str]:
    try:
        path = settings.facebook_app_secrets_file
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            raise FacebookAuthError("Facebook app credentials are not configured. Save backend/secrets/facebook-app.json and restart CLIPRA.")
        value = json.loads(path.read_text(encoding="utf-8"))
        app_id, app_secret = str(value.get("app_id") or "").strip(), str(value.get("app_secret") or "").strip()
        if not app_id.isdigit() or len(app_secret) < 8:
            raise FacebookAuthError("facebook-app.json must contain a valid app_id and app_secret.")
        return {"app_id": app_id, "app_secret": app_secret}
    except (OSError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise FacebookAuthError("Facebook app credentials could not be read. Check backend/secrets/facebook-app.json.") from exc


def _callback_ssl_context() -> ssl.SSLContext:
    if not settings.facebook_tls_cert_file.is_file() or not settings.facebook_tls_key_file.is_file():
        raise FacebookAuthError(
            "The trusted local HTTPS certificate is not configured. Run the mkcert setup commands in docs/stage8-facebook-publishing.md, then connect again."
        )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    try:
        context.load_cert_chain(str(settings.facebook_tls_cert_file), str(settings.facebook_tls_key_file))
    except (OSError, ssl.SSLError) as exc:
        raise FacebookAuthError("The local HTTPS certificate could not be loaded. Recreate it using the documented mkcert commands.") from exc
    return context


def configured() -> bool:
    try:
        _client()
        return True
    except FacebookAuthError:
        return False


def _graph_url(path: str) -> str:
    return f"https://graph.facebook.com/{settings.facebook_graph_api_version}/{path.lstrip('/')}"


def _json_request(url: str, data: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data is not None else None,
                                    headers={"User-Agent": "CLIPRA.AI/1.0"}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read(1024 * 1024))
        if not isinstance(result, dict):
            raise FacebookAuthError("Meta returned an unexpected response.")
        return result
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", errors="replace")
        try:
            message = json.loads(body).get("error", {}).get("message", "")
        except (json.JSONDecodeError, AttributeError):
            message = ""
        raise FacebookAuthError(f"Meta authorization failed (HTTP {exc.code}). {message or 'Review the app permissions and account.'}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise FacebookAuthError("Could not connect to Meta. Check your internet connection and try again.") from exc


def _save_pages(pages: list[dict[str, str]]) -> None:
    path = _token_path()
    encrypted = _protect(json.dumps(pages, separators=(",", ":")).encode())
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        stream.write(encrypted)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _clear_auth_error() -> None:
    _pending["error"] = None


def _granted_permission_statuses(user_token: str) -> dict[str, str]:
    """Return only permission names/statuses for diagnostics; never retain tokens."""
    url = _graph_url("me/permissions") + "?" + urllib.parse.urlencode({"access_token": user_token})
    try:
        data = _json_request(url).get("data")
    except FacebookAuthError:
        return {}
    if not isinstance(data, list):
        return {}
    return {
        str(item["permission"]): str(item["status"])
        for item in data
        if isinstance(item, dict) and item.get("permission") and item.get("status")
    }


def _business_owned_pages(user_token: str) -> list[dict[str, Any]]:
    """Find Pages owned by businesses when /me/accounts omits portfolio assets."""
    businesses_url = _graph_url("me/businesses") + "?" + urllib.parse.urlencode({
        "fields": "id,name", "limit": "100", "access_token": user_token,
    })
    try:
        businesses = _json_request(businesses_url).get("data")
    except FacebookAuthError:
        return []
    if not isinstance(businesses, list):
        return []

    pages: dict[str, dict[str, Any]] = {}
    for business in businesses:
        if not isinstance(business, dict) or not business.get("id"):
            continue
        pages_url = _graph_url(f"{business['id']}/owned_pages") + "?" + urllib.parse.urlencode({
            "fields": "id,name,access_token,tasks", "limit": "100", "access_token": user_token,
        })
        try:
            owned = _json_request(pages_url).get("data")
        except FacebookAuthError:
            continue
        if not isinstance(owned, list):
            continue
        for page in owned:
            if isinstance(page, dict) and page.get("id"):
                pages[str(page["id"])] = page
    return list(pages.values())


def pages() -> list[dict[str, str]]:
    path = _token_path()
    if not path.exists():
        return []
    try:
        value = json.loads(_protect(path.read_bytes(), decrypt=True))
        return [item for item in value if isinstance(item, dict) and item.get("id") and item.get("name") and item.get("access_token")]
    except (OSError, json.JSONDecodeError, FacebookAuthError, TypeError):
        return []


def selected_page(page_id: str) -> dict[str, str] | None:
    return next((page for page in pages() if secrets.compare_digest(str(page.get("id", "")), page_id)), None)


def status() -> dict[str, Any]:
    saved = pages()
    pending = bool(_pending.get("state"))
    return {"configured": configured(), "connected": bool(saved), "authorization_pending": pending,
            "pages": [{"id": item["id"], "name": item["name"],
                       "instagram_user_id": item.get("instagram_user_id"),
                       "instagram_username": item.get("instagram_username")} for item in saved],
            "authorization_error": _pending.get("error"),
            "message": "Connected to Facebook Pages." if saved else ("Facebook app credentials are not configured." if not configured() else "Connect Facebook to choose a Page.")}


def disconnect() -> None:
    with _lock:
        path = _token_path()
        path.unlink(missing_ok=True)


def _complete(code: str, redirect_uri: str, *, include_instagram: bool = False) -> None:
    client = _client()
    token_result = _json_request(_graph_url("oauth/access_token") + "?" + urllib.parse.urlencode({
        "client_id": client["app_id"], "client_secret": client["app_secret"], "redirect_uri": redirect_uri, "code": code,
    }))
    user_token = str(token_result.get("access_token") or "")
    if not user_token:
        raise FacebookAuthError("Meta did not return an authorization token.")
    long_result = _json_request(_graph_url("oauth/access_token") + "?" + urllib.parse.urlencode({
        "grant_type": "fb_exchange_token", "client_id": client["app_id"], "client_secret": client["app_secret"], "fb_exchange_token": user_token,
    }))
    user_token = str(long_result.get("access_token") or user_token)
    url = _graph_url("me/accounts") + "?" + urllib.parse.urlencode({"fields": "id,name,access_token,tasks", "limit": "100", "access_token": user_token})
    result = _json_request(url)
    data = result.get("data")
    if not isinstance(data, list):
        raise FacebookAuthError("Meta did not return the Pages managed by this account. Confirm Page access and permissions.")
    # Business-owned Pages can be absent from /me/accounts even when the user
    # has full access, so supplement that list through the Business API.
    candidates: dict[str, dict[str, Any]] = {
        str(page["id"]): page for page in data
        if isinstance(page, dict) and page.get("id")
    }
    for page in _business_owned_pages(user_token):
        candidates.setdefault(str(page["id"]), page)

    normalized = []
    for page in candidates.values():
        if not page.get("id"):
            continue
        page_token = str(page.get("access_token") or "")
        if not page_token:
            # Some business asset responses omit the token field; fetch it
            # directly using the same user token before treating the Page as unusable.
            try:
                details = _json_request(_graph_url(str(page["id"])) + "?" + urllib.parse.urlencode({
                    "fields": "id,name,access_token,tasks", "access_token": user_token,
                }))
                page_token = str(details.get("access_token") or "")
                page = {**page, **details}
            except FacebookAuthError:
                continue
        if not page_token:
            continue
        entry = {"id": str(page["id"]), "name": str(page.get("name") or "Facebook Page"), "access_token": page_token}
        # Keep Facebook authorization usable if the linked Instagram account or
        # its publishing permissions are not available on a particular Page.
        try:
            details = _json_request(_graph_url(entry["id"]) + "?" + urllib.parse.urlencode({
                "fields": "instagram_business_account{id,username}", "access_token": entry["access_token"],
            }))
            instagram = details.get("instagram_business_account")
            if isinstance(instagram, dict) and instagram.get("id"):
                entry["instagram_user_id"] = str(instagram["id"])
                entry["instagram_username"] = str(instagram.get("username") or "Instagram account")
        except FacebookAuthError:
            pass
        normalized.append(entry)
    if not normalized:
        grants = _granted_permission_statuses(user_token)
        requested = authorization_permissions(include_instagram=include_instagram)
        grant_summary = ", ".join(f"{name}: {grants.get(name, 'not granted')}" for name in requested)
        suffix = f" Meta permission status: {grant_summary}." if grant_summary else " Meta did not provide permission diagnostics."
        raise FacebookAuthError(
            "No manageable Facebook Pages were returned. Confirm this is the Facebook account with Page access, "
            "and allow CLIPRA to access the Page during Meta authorization." + suffix
        )
    _save_pages(normalized)


def begin_connect(*, include_instagram: bool = False) -> str:
    client = _client()
    with _lock:
        if _pending.get("state"):
            raise FacebookAuthError("A Facebook authorization is already in progress.")
        state = secrets.token_urlsafe(32)
        redirect_uri = f"https://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"
        tls_context = _callback_ssl_context()

        class CallbackServer(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlsplit(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if parsed.path != CALLBACK_PATH or not secrets.compare_digest((params.get("state") or [""])[0], state):
                    self.send_error(400, "Invalid Facebook authorization response.")
                    return
                error = (params.get("error") or [""])[0]
                code = (params.get("code") or [""])[0]
                try:
                    if error or not code:
                        raise FacebookAuthError("Facebook authorization was cancelled or denied.")
                    _complete(code, redirect_uri, include_instagram=include_instagram)
                    message = "Facebook is connected. Return to CLIPRA.AI. You may close this tab."
                    response = b"<!doctype html><meta charset=utf-8><title>CLIPRA</title><p>Facebook is connected. Return to CLIPRA.AI; you may close this tab.</p>"
                except FacebookAuthError as exc:
                    message = str(exc)
                    response = b"<!doctype html><meta charset=utf-8><title>CLIPRA</title><p>Facebook could not be connected. Return to CLIPRA.AI for details.</p>"
                _pending["error"] = None if "connected" in message.lower() else message
                _pending["state"] = None
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(response)
                threading.Thread(target=self.server.shutdown, daemon=True).start()

            def log_message(self, *_args):
                return

        try:
            server = CallbackServer((CALLBACK_BIND_HOST, CALLBACK_PORT), Handler)
        except OSError as exc:
            raise FacebookAuthError(f"Facebook callback port {CALLBACK_PORT} is unavailable. Close the other app using it and retry.") from exc
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        server.socket = tls_context.wrap_socket(server.socket, server_side=True)
        _pending.update(state=state, server=server, thread=thread, error=None)
        thread.start()
    query = urllib.parse.urlencode({
        "client_id": client["app_id"], "redirect_uri": redirect_uri, "state": state,
        "scope": ",".join(authorization_permissions(include_instagram=include_instagram)),
        "response_type": "code", "auth_type": "rerequest",
    })
    auth_url = f"https://www.facebook.com/{settings.facebook_graph_api_version}/dialog/oauth?{query}"
    if not webbrowser.open(auth_url):
        server.shutdown()
        _pending.update(state=None, server=None, thread=None)
        raise FacebookAuthError("Could not open the browser for Facebook authorization.")
    return "Finish Facebook authorization in your browser, then return to CLIPRA.AI."
