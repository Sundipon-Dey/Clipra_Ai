"""Local Desktop OAuth and DPAPI-protected YouTube token storage."""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from ctypes import POINTER, Structure, byref, c_byte, c_void_p, cast, create_string_buffer
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.storage import managed_directory

YOUTUBE_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}


class YouTubeAuthError(RuntimeError):
    pass


class _DataBlob(Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", POINTER(c_byte))]


def _blob(data: bytes):
    buffer = create_string_buffer(data)
    return _DataBlob(len(data), cast(buffer, POINTER(c_byte))), buffer


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise YouTubeAuthError("Secure YouTube token storage is available only on Windows.")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [POINTER(_DataBlob), wintypes.LPCWSTR, POINTER(_DataBlob), c_void_p, c_void_p, wintypes.DWORD, POINTER(_DataBlob)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [POINTER(_DataBlob), POINTER(wintypes.LPWSTR), POINTER(_DataBlob), c_void_p, c_void_p, wintypes.DWORD, POINTER(_DataBlob)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [c_void_p]
    kernel32.LocalFree.restype = c_void_p
    source, keepalive = _blob(data)
    output = _DataBlob()
    description = ctypes.c_wchar_p()
    if decrypt:
        ok = crypt32.CryptUnprotectData(byref(source), byref(description), None, None, None, 0x1, byref(output))
    else:
        ok = crypt32.CryptProtectData(byref(source), "CLIPRA YouTube OAuth", None, None, None, 0x1, byref(output))
    if not ok:
        raise YouTubeAuthError("Windows could not access the protected YouTube login token.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(c_void_p(cast(output.pbData, c_void_p).value))
        del keepalive


def _token_path() -> Path:
    directory = managed_directory("private/youtube")
    return directory / "oauth-token.dpapi"


def _read_installed_client() -> dict[str, str]:
    path = settings.youtube_client_secrets_file
    try:
        if not path.is_file() or path.stat().st_size > 256 * 1024:
            raise YouTubeAuthError("OAuth client JSON is not configured. Place the downloaded Desktop client JSON at backend/secrets/youtube-oauth-client.json or set YOUTUBE_CLIENT_SECRETS_FILE.")
        raw = json.loads(path.read_text(encoding="utf-8"))
        client = raw.get("installed")
        if not isinstance(client, dict) or not client.get("client_id"):
            raise YouTubeAuthError("The OAuth JSON must be a Google Desktop app client file.")
        return {"client_id": str(client["client_id"]), "client_secret": str(client.get("client_secret") or "")}
    except (OSError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise YouTubeAuthError("The YouTube OAuth client JSON could not be read. Check the configured file path and file format.") from exc


def is_configured() -> bool:
    try:
        _read_installed_client()
        return True
    except YouTubeAuthError:
        return False


def load_tokens() -> dict[str, Any] | None:
    path = _token_path()
    if not path.exists():
        return None
    try:
        return json.loads(_dpapi(path.read_bytes(), decrypt=True))
    except (OSError, json.JSONDecodeError, YouTubeAuthError):
        return None


def save_tokens(tokens: dict[str, Any]) -> None:
    path = _token_path()
    encrypted = _dpapi(json.dumps(tokens, separators=(",", ":")).encode("utf-8"), decrypt=False)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        stream.write(encrypted)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def status() -> dict[str, Any]:
    configured = is_configured()
    connected = bool(load_tokens())
    message = "Connected to YouTube." if connected else ("OAuth client JSON is not configured." if not configured else "Connect your YouTube account to continue.")
    with _lock:
        authorization_pending = bool(_pending)
    return {"configured": configured, "connected": connected, "authorization_pending": authorization_pending, "message": message}


def begin_connect() -> str:
    client = _read_installed_client()
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(32)

    class CallbackServer(ThreadingHTTPServer):
        allow_reuse_address = True
        daemon_threads = True

    callback_path = "/"
    server: CallbackServer

    class CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if urllib.parse.urlsplit(self.path).path != callback_path or not secrets.compare_digest((query.get("state") or [""])[0], state):
                self.send_error(400, "Invalid OAuth response. Return to CLIPRA.AI and try connecting again.")
                return
            oauth_error = (query.get("error") or [""])[0]
            if oauth_error:
                message = "YouTube account connection was cancelled." if oauth_error == "access_denied" else "Google could not authorize the YouTube connection. Return to CLIPRA.AI and try again."
                self._respond(400, message)
                _expire_flow(state, server)
                return
            code = (query.get("code") or [""])[0]
            try:
                token = _exchange_code(client, code, verifier, f"http://127.0.0.1:{server.server_port}{callback_path}")
                if not token.get("refresh_token"):
                    raise YouTubeAuthError("Google did not return a refresh token. Disconnect CLIPRA.AI from your Google account permissions, then connect again.")
                save_tokens(token)
                self._respond(200, "YouTube is connected to CLIPRA.AI. You can close this tab and return to the app.")
            except YouTubeAuthError as exc:
                self._respond(400, str(exc))
            finally:
                _expire_flow(state, server)

        def _respond(self, status_code: int, message: str):
            body = ("<!doctype html><meta charset='utf-8'><title>CLIPRA.AI YouTube</title>"
                    "<main style='font:16px system-ui;max-width:620px;margin:12vh auto;padding:24px;color:#e9e9f2;background:#11131b;border-radius:14px'>"
                    f"<h1>{'Connected' if status_code == 200 else 'Connection not completed'}</h1><p>{message}</p></main>").encode()
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    server = CallbackServer(("127.0.0.1", 0), CallbackHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}{callback_path}"
    with _lock:
        _pending[state] = {"server": server, "created_at": time.time()}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    timer = threading.Timer(300, _expire_flow, args=(state, server))
    timer.daemon = True
    timer.start()
    params = {
        "client_id": client["client_id"], "redirect_uri": redirect_uri,
        "response_type": "code", "scope": YOUTUBE_SCOPE, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "select_account consent",
    }
    url = f"{AUTH_ENDPOINT}?{urllib.parse.urlencode(params)}"
    if not webbrowser.open(url):
        _expire_flow(state, server)
        raise YouTubeAuthError("Could not open your default web browser. Check that a browser is available, then connect again.")
    return "YouTube authorization opened in your default browser."


def _expire_flow(state: str, server: ThreadingHTTPServer) -> None:
    with _lock:
        _pending.pop(state, None)
    try:
        server.shutdown()
        server.server_close()
    except (OSError, RuntimeError):
        pass


def _http_json(url: str, data: bytes, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read(2 * 1024 * 1024))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise YouTubeAuthError("Google OAuth could not be completed. Check your internet connection and try again.") from exc


def _exchange_code(client: dict[str, str], code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
    if not code:
        raise YouTubeAuthError("Google did not return an authorization code. Try connecting again.")
    body = urllib.parse.urlencode({
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "code": code, "code_verifier": verifier, "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode()
    tokens = _http_json(TOKEN_ENDPOINT, body)
    tokens["expires_at"] = time.time() + int(tokens.get("expires_in", 3600))
    return tokens


def access_token() -> str:
    tokens = load_tokens()
    if not tokens or not tokens.get("refresh_token"):
        raise YouTubeAuthError("Connect your YouTube account before uploading.")
    if float(tokens.get("expires_at", 0)) > time.time() + 90 and tokens.get("access_token"):
        return str(tokens["access_token"])
    client = _read_installed_client()
    body = urllib.parse.urlencode({
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token",
    }).encode()
    updated = _http_json(TOKEN_ENDPOINT, body)
    tokens["access_token"] = updated["access_token"]
    tokens["expires_at"] = time.time() + int(updated.get("expires_in", 3600))
    save_tokens(tokens)
    return str(tokens["access_token"])


def disconnect() -> None:
    tokens = load_tokens()
    if tokens and tokens.get("refresh_token"):
        try:
            urllib.request.urlopen(urllib.request.Request(
                "https://oauth2.googleapis.com/revoke", data=urllib.parse.urlencode({"token": tokens["refresh_token"]}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST"), timeout=15).close()
        except (urllib.error.URLError, TimeoutError):
            pass
    _token_path().unlink(missing_ok=True)
