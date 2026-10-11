"""A small local web page that shows the login QR code and live status.

The login protocol itself stays plain HTTP in `login.py`; this page only displays state. It is
served from 127.0.0.1 on a random port under a random path token, using the standard library only.
With Chrome installed it opens as a small app window in a separate, throwaway Chrome instance
(a fresh temporary profile), so the window size is honoured even when the user's Chrome is already
running, and the instance is shut down after login. Without Chrome it opens in the default browser.
"""

from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
TERMINAL = {"success", "expired", "refused", "error"}
WINDOW_SIZE = (360, 480)  # outer size in points; fits the card below

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QQ 音乐登录</title>
<style>
  :root { --bg:#f5f6f7; --card:#fff; --fg:#1d1f22; --muted:#6b7280; --ok:#16a34a; --warn:#d97706; --bad:#dc2626; --accent:#31c27c; }
  @media (prefers-color-scheme: dark) { :root { --bg:#111315; --card:#1b1e21; --fg:#e8eaed; --muted:#9aa0a6; } }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; }
  .card { width:340px; padding:28px 24px 22px; background:var(--card); border-radius:16px;
          box-shadow:0 8px 30px rgba(0,0,0,.08); text-align:center; }
  @media (max-width: 420px) {  /* the app window: drop the card chrome and fill the window */
    body { background:var(--card); }
    .card { width:100%; padding:14px 16px; border-radius:0; box-shadow:none; }
    .sub { margin-bottom:12px; }
    .status { margin-top:12px; }
    .foot { margin-top:10px; }
  }
  h1 { margin:0 0 4px; font-size:18px; font-weight:600; }
  .sub { margin:0 0 18px; color:var(--muted); font-size:13px; }
  .qr { position:relative; width:232px; height:232px; margin:0 auto; border-radius:12px; background:#fff;
        display:flex; align-items:center; justify-content:center; overflow:hidden; }
  .qr img { width:220px; height:220px; image-rendering:pixelated; }
  .qr .veil { position:absolute; inset:0; display:none; align-items:center; justify-content:center;
              background:rgba(255,255,255,.92); color:#1d1f22; font-size:44px; }
  .qr.done .veil { display:flex; }
  .spinner { width:28px; height:28px; border:3px solid #e5e7eb; border-top-color:var(--accent); border-radius:50%;
             animation:spin 0.9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .status { margin:18px 0 4px; font-weight:600; display:flex; align-items:center; justify-content:center; gap:8px; }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--muted); }
  .status.waiting .dot { background:var(--accent); animation:pulse 1.4s ease-in-out infinite; }
  .status.scanned .dot { background:var(--warn); }
  .status.success .dot { background:var(--ok); }
  .status.expired .dot, .status.refused .dot, .status.error .dot { background:var(--bad); }
  @keyframes pulse { 50% { opacity:.3; } }
  .hint { color:var(--muted); font-size:13px; min-height:20px; }
  .foot { margin-top:16px; color:var(--muted); font-size:12px; }
</style>
</head>
<body>
<main class="card">
  <h1>QQ 音乐登录</h1>
  <p class="sub" id="sub">qqmusic CLI</p>
  <div class="qr" id="qr"><div class="spinner" id="spin"></div><div class="veil" id="veil"></div></div>
  <div class="status" id="status"><span class="dot"></span><span id="label">正在获取二维码…</span></div>
  <div class="hint" id="hint"></div>
  <div class="foot" id="foot"></div>
</main>
<script>
const $ = (id) => document.getElementById(id);
const LABEL = {
  starting: "正在获取二维码…", waiting: "等待扫码", scanned: "已扫码，请在手机上确认",
  success: "登录成功", expired: "二维码已过期", refused: "已在手机上取消", error: "登录失败",
};
let qrVersion = -1, timer = null;
async function tick() {
  let s;
  try { s = await (await fetch(`status?w=${outerWidth}&h=${outerHeight}`, { cache: "no-store" })).json(); }
  catch (e) { $("hint").textContent = "CLI 已退出"; clearInterval(timer); return; }
  $("sub").textContent = s.app ? `请用${s.app}扫一扫` : "qqmusic CLI";
  if (s.qr_version !== qrVersion && s.qr_version >= 0) {
    qrVersion = s.qr_version;
    const img = new Image(); img.alt = "登录二维码"; img.src = `qr?v=${qrVersion}`;
    $("spin")?.remove(); $("qr").querySelector("img")?.remove(); $("qr").prepend(img);
  }
  $("status").className = "status " + s.status;
  $("label").textContent = LABEL[s.status] || s.status;
  if (s.status === "success") {
    $("qr").classList.add("done"); $("veil").textContent = "✓";
    $("hint").textContent = s.nickname ? `欢迎，${s.nickname}` : "";
    $("foot").textContent = "凭证已保存到钥匙串，可以关闭此窗口";
  } else if (["expired", "refused", "error"].includes(s.status)) {
    $("qr").classList.add("done"); $("veil").textContent = "✕";
    $("hint").textContent = s.message || "";
    $("foot").textContent = "请重新运行 qqmusic login";
  } else if (s.deadline) {
    const left = Math.max(0, Math.round(s.deadline - Date.now() / 1000));
    $("foot").textContent = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")} 后过期`;
  }
  if (["success", "expired", "refused", "error"].includes(s.status)) {
    clearInterval(timer);
    if (s.status === "success") setTimeout(() => window.close(), 2500);
  }
}
timer = setInterval(tick, 800); tick();
</script>
</body>
</html>
"""


class LoginPage:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(12)
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"status": "starting", "qr_version": -1}
        self._qr: tuple[bytes, str] | None = None
        self._server: ThreadingHTTPServer | None = None
        self._browser: subprocess.Popen[bytes] | None = None
        self._profile: str | None = None

    # -- state ------------------------------------------------------------------------------

    def update(self, **fields: Any) -> None:
        with self._lock:
            self._state.update(fields)

    def set_qr(self, image: bytes, mimetype: str, app: str, deadline: float) -> None:
        with self._lock:
            self._qr = (image, mimetype)
            self._state.update(
                status="waiting", app=app, deadline=deadline, qr_version=self._state["qr_version"] + 1
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    # -- server -----------------------------------------------------------------------------

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/{self.token}/"

    def start(self) -> str:
        page = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                prefix = f"/{page.token}/"
                if not self.path.startswith(prefix):
                    self.send_error(404)
                    return
                route, _, query = self.path[len(prefix) :].partition("?")
                if route == "":
                    self._send(200, "text/html; charset=utf-8", PAGE.encode())
                elif route == "status":
                    size = dict(kv.split("=", 1) for kv in query.split("&") if "=" in kv)
                    if size.get("w", "").isdigit() and size.get("h", "").isdigit():
                        page.update(client_size=[int(size["w"]), int(size["h"])])
                    self._send(200, "application/json", json.dumps(page.snapshot(), ensure_ascii=False).encode())
                elif route == "qr" and page._qr:
                    self._send(200, page._qr[1], page._qr[0])
                else:
                    self.send_error(404)

            def _send(self, code: int, ctype: str, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002  keep stderr clean
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self.url

    def open(self) -> None:
        """Open a small Chrome app window in its own instance; fall back to the default browser."""
        if sys.platform == "darwin" and CHROME.exists():
            self._profile = tempfile.mkdtemp(prefix="qqmusic-login-")
            w, h = WINDOW_SIZE
            try:
                self._browser = subprocess.Popen(
                    [
                        str(CHROME),
                        f"--user-data-dir={self._profile}",
                        f"--app={self.url}",
                        f"--window-size={w},{h}",
                        "--window-position=120,120",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-extensions",
                        "--disable-sync",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            except OSError:
                shutil.rmtree(self._profile, ignore_errors=True)
                self._profile = None
        webbrowser.open(self.url)

    def close(self, linger: float = 3.0) -> None:
        """Let the page show the final state, then stop the window and the server."""
        if self._server is None:
            return
        time.sleep(linger)
        if self._browser is not None:
            self._browser.terminate()
            try:
                self._browser.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._browser.kill()
            self._browser = None
        if self._profile:
            shutil.rmtree(self._profile, ignore_errors=True)
            self._profile = None
        self._server.shutdown()
        self._server.server_close()
        self._server = None
