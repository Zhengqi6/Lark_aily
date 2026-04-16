"""Feishu OAuth — CLI-friendly browser + localhost callback.

Flow:
  1. Get app_access_token (app_id + app_secret → POST auth/v3/app_access_token/internal)
  2. Start local HTTP server on configured port (default 18080)
  3. Open browser to authorize URL with redirect_uri=http://127.0.0.1:<port>/callback
  4. User authorizes → Feishu redirects with ?code=<> to our local server
  5. Exchange code for user_access_token via authen/v1/access_token
  6. Save tokens to ~/.baf/credentials.json

References: Feishu open platform 《网页应用登录预授权码》 / 《获取 user_access_token》.
"""
from __future__ import annotations

import http.server
import secrets
import socketserver
import threading
import time
import urllib.parse
import webbrowser
from typing import Any

import httpx
from rich.console import Console

from ..config import Config, Credentials

FEISHU_BASE = "https://open.feishu.cn"
console = Console()


# ----- low-level token helpers -------------------------------------
def get_app_access_token(cfg: Config) -> str:
    """Self-built app -- returns `app_access_token`."""
    if not (cfg.feishu_app_id and cfg.feishu_app_secret):
        raise RuntimeError("feishu_app_id / feishu_app_secret 未配置")
    r = httpx.post(
        f"{FEISHU_BASE}/open-apis/auth/v3/app_access_token/internal",
        json={"app_id": cfg.feishu_app_id, "app_secret": cfg.feishu_app_secret},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get app_access_token failed: {data}")
    return data["app_access_token"]


def exchange_code_for_user_token(cfg: Config, code: str) -> dict[str, Any]:
    app_token = get_app_access_token(cfg)
    r = httpx.post(
        f"{FEISHU_BASE}/open-apis/authen/v1/access_token",
        headers={"Authorization": f"Bearer {app_token}"},
        json={"grant_type": "authorization_code", "code": code},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"exchange code failed: {data}")
    return data["data"]


def refresh_user_token(cfg: Config, refresh_token: str) -> dict[str, Any]:
    app_token = get_app_access_token(cfg)
    r = httpx.post(
        f"{FEISHU_BASE}/open-apis/authen/v1/refresh_access_token",
        headers={"Authorization": f"Bearer {app_token}"},
        json={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"refresh token failed: {data}")
    return data["data"]


# ----- OAuth dance -------------------------------------------------
def _build_authorize_url(cfg: Config, state: str, redirect_uri: str) -> str:
    q = urllib.parse.urlencode(
        {"app_id": cfg.feishu_app_id, "redirect_uri": redirect_uri, "state": state}
    )
    return f"{FEISHU_BASE}/open-apis/authen/v1/index?{q}"


def oauth_login(cfg: Config) -> Credentials:
    port = cfg.feishu_oauth_port or 18080
    redirect_uri = f"http://127.0.0.1:{port}/callback"
    state = secrets.token_urlsafe(16)
    authorize_url = _build_authorize_url(cfg, state, redirect_uri)

    result: dict[str, Any] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence default noisy logging
            pass

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if not parsed.path.startswith("/callback"):
                self.send_response(404)
                self.end_headers()
                return
            qs = urllib.parse.parse_qs(parsed.query)
            code = (qs.get("code") or [""])[0]
            got_state = (qs.get("state") or [""])[0]
            if got_state != state:
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h2>state mismatch</h2>".encode())
                result["error"] = "state mismatch"
                return
            if not code:
                self.send_response(400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<h2>no code</h2>".encode())
                result["error"] = "no code"
                return
            result["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h2>✅ 已授权，请回到终端查看</h2><p>You can close this tab.</p>".encode("utf-8")
            )

    class QuietTCP(socketserver.TCPServer):
        allow_reuse_address = True

    with QuietTCP(("127.0.0.1", port), Handler) as httpd:
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        console.print(f"[cyan]等待浏览器授权…[/cyan]  监听 {redirect_uri}")
        try:
            webbrowser.open(authorize_url)
        except Exception:
            pass
        console.print(f"[dim]如未自动打开，请手动访问：{authorize_url}[/dim]")
        # wait for code
        deadline = time.time() + 180
        while "code" not in result and "error" not in result and time.time() < deadline:
            time.sleep(0.3)
        httpd.shutdown()

    if "error" in result:
        raise RuntimeError(f"OAuth failed: {result['error']}")
    if "code" not in result:
        raise RuntimeError("OAuth timeout (180s)")

    token_data = exchange_code_for_user_token(cfg, result["code"])
    creds = Credentials(
        user_access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token", ""),
        expires_at=time.time() + int(token_data.get("expires_in", 7200)) - 60,
        open_id=token_data.get("open_id", ""),
        name=token_data.get("name", ""),
    )
    creds.save()
    return creds


def ensure_user_token(cfg: Config) -> str:
    """Return a fresh user_access_token, refreshing if needed."""
    creds = Credentials.load()
    if not creds.user_access_token:
        raise RuntimeError("尚未登录，请先运行 `baf login`")
    if creds.expires_at <= time.time() + 30 and creds.refresh_token:
        new_data = refresh_user_token(cfg, creds.refresh_token)
        creds.user_access_token = new_data["access_token"]
        creds.refresh_token = new_data.get("refresh_token", creds.refresh_token)
        creds.expires_at = time.time() + int(new_data.get("expires_in", 7200)) - 60
        creds.save()
    return creds.user_access_token
