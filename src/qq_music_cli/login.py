"""QR-code login over plain HTTP, for QQ and for WeChat.

QQ, as y.qq.com's login popup does it:
  1. `ptqrshow` returns the QR image plus a `qrsig` cookie.
  2. `ptqrlogin` is polled with `ptqrtoken = hash33(qrsig, seed 0)`. Its JS callback `ptuiCB(...)` reports
     the state. On success the third argument is a `check_sig` URL.
  3. Fetching that URL sets the `p_skey` cookie.
  4. graph.qq.com's OAuth `authorize` answers with a redirect whose query has a `code`.
  5. `QQConnectLogin.LoginServer.QQLogin` turns the code into a QQ Music session.

WeChat, as open.weixin.qq.com's QR page does it:
  1. The page embeds the QR as `<img src="/connect/qrcode/<uuid>">`.
  2. `/connect/l/qrconnect` is long-polled with that uuid, passing `last=<previous errcode>` like the
     page's own script. The reply is `window.wx_errcode=…;window.wx_code='…';`, and errcode 405 carries
     the code.
  3. `music.login.LoginServer.Login` turns the code into a QQ Music session.

The final exchange is tried with the web `comm`, then with the Android one. A code consumed by a
failed first attempt cannot be reused, so in that case the user scans again.
"""

from __future__ import annotations

import random
import time
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from .auth import QQ, WECHAT, Credential, credential_from_login, hash33
from .client import USER_AGENT, Client
from .errors import AuthError, QQMusicError

# Event names passed to the `on_event` callback.
QR_READY, SCANNED, WAITING, EXPIRED, REFUSED = "qr_ready", "scanned", "waiting", "expired", "refused"
EventFn = Callable[[str, dict[str, Any]], None]

PT_HOST = "https://ssl.ptlogin2.qq.com"
PT_REFERER = {"Referer": "https://xui.ptlogin2.qq.com/"}
OAUTH_URL = "https://graph.qq.com/oauth2.0/authorize"
WX_HOST = "https://open.weixin.qq.com"
WX_POLL_URL = "https://lp.open.weixin.qq.com/connect/l/qrconnect"
WX_APP = "wx48db31d50e334801"  # y.qq.com's WeChat Open Platform app
QQ_CONNECT_APP = "100497308"  # y.qq.com's QQ Connect app


def landing_page(kind: int) -> str:
    """Where y.qq.com expects the OAuth redirect (`login_type` 1 = QQ, 2 = WeChat in this URL)."""
    return f"https://y.qq.com/portal/wx_redirect.html?login_type={kind}&surl=https://y.qq.com/"


# y.qq.com's registration with QQ's ptlogin service.
PT_APP = {"aid": "716027609", "daid": "383", "pt_3rd_aid": QQ_CONNECT_APP}
PT_POLL_FIXED = {
    "from_ui": 1,
    "g": 1,
    "h": 1,
    "has_onekey": 1,
    "js_type": 1,
    "js_ver": 20102616,
    "pt_uistyle": 40,
    "ptlang": 2052,
    "ptredirect": 0,
    "t": 1,
    "u1": "https://graph.qq.com/oauth2.0/login_jump",
}
ANDROID_COMM = dict(tmeAppID="qqmusic", chid="10003505", ct=11, cv=20090008, v=20090008)

# ptuiCB status codes and wx_errcode values worth naming.
PT_OK, PT_EXPIRED, PT_WAITING, PT_SCANNED, PT_REFUSED = "0", "65", "66", "67", "68"
WX_OK, WX_SCANNED, WX_WAITING, WX_EXPIRED, WX_REFUSED = 405, 404, 408, 402, 403


def ptui_args(text: str) -> list[str]:
    """Split the quoted arguments of a `ptuiCB('a','b',...)` callback, honouring backslash escapes."""
    start = text.find("ptuiCB(")
    if start < 0:
        return []
    args: list[str] = []
    current: list[str] | None = None
    escaped = False
    for ch in text[start + len("ptuiCB(") :]:
        if current is None:
            if ch == "'":
                current = []
            elif ch == ")":
                break
            continue
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "'":
            args.append("".join(current))
            current = None
        else:
            current.append(ch)
    return args


def wx_status(text: str) -> tuple[int | None, str]:
    """Read `window.wx_errcode=…;window.wx_code='…';` into (errcode, code)."""
    fields: dict[str, str] = {}
    for statement in text.split(";"):
        name, sep, value = statement.strip().partition("=")
        if sep:
            fields[name.strip().removeprefix("window.")] = value.strip().strip("'\"")
    raw = fields.get("wx_errcode", "")
    return (int(raw) if raw.isdigit() else None), fields.get("wx_code", "")


def wx_qr_uuid(page: str) -> str | None:
    """The QR id is the last path segment of the page's `/connect/qrcode/<uuid>` image."""
    marker = "/connect/qrcode/"
    at = page.find(marker)
    if at < 0:
        return None
    tail = page[at + len(marker) :]
    end = next((i for i, ch in enumerate(tail) if not (ch.isalnum() or ch in "-_")), len(tail))
    return tail[:end] or None


def _browser() -> httpx.Client:
    return httpx.Client(timeout=20.0, follow_redirects=False, headers={"User-Agent": USER_AGENT})


def _now_ms() -> int:
    return int(time.time() * 1000)


def _report(on_event: EventFn, state: str, last: list[str]) -> None:
    """Emit a state change once, not on every poll."""
    if not last or last[0] != state:
        on_event(state, {})
        last[:] = [state]


def _exchange(module: str, method: str, param: dict[str, Any], login_type: int, source: str) -> Credential:
    attempts = (("web", None), ("android", {**ANDROID_COMM, "tmeLoginType": login_type}))
    problems: list[str] = []
    for label, comm in attempts:
        with Client(None) as client:
            try:
                reply = client.rpc(
                    module, method, param, comm=comm, comm_extra={"tmeLoginType": login_type}, idempotent=False
                )
            except QQMusicError as exc:
                problems.append(f"{label} comm: {exc.message}")
                continue
        status = reply.get("code")
        if status not in (None, 0):
            problems.append(f"{label} comm: login code {status}")
            continue
        try:
            return credential_from_login(reply, source)
        except AuthError as exc:
            problems.append(f"{label} comm: {exc.message}")
    raise AuthError("login exchange failed: " + "; ".join(problems))


# -- QQ -------------------------------------------------------------------------------------------


def qq_login(on_event: EventFn, *, timeout: float = 180.0, poll: float = 1.5) -> Credential:
    with _browser() as web:
        shown = web.get(
            f"{PT_HOST}/ptqrshow",
            params={
                "appid": PT_APP["aid"],
                "daid": PT_APP["daid"],
                "pt_3rd_aid": QQ_CONNECT_APP,
                "d": 72,
                "e": 2,
                "l": "M",
                "s": 3,
                "v": 4,
                "t": random.random(),
            },
            headers=PT_REFERER,
        )
        qrsig = shown.cookies.get("qrsig")
        if shown.status_code != 200 or not qrsig:
            raise AuthError(f"could not get a QQ QR code (HTTP {shown.status_code})")
        on_event(QR_READY, {"kind": "qq", "image": shown.content, "mimetype": "image/png"})

        token = hash33(qrsig, seed=0)
        stop_at = time.monotonic() + timeout
        last: list[str] = []
        while stop_at - time.monotonic() > 0:
            reply = web.get(
                f"{PT_HOST}/ptqrlogin",
                params={**PT_POLL_FIXED, **PT_APP, "ptqrtoken": token, "action": f"0-0-{_now_ms()}"},
                headers={**PT_REFERER, "Cookie": f"qrsig={qrsig}"},
            )
            args = ptui_args(reply.text)
            status = args[0] if args else ""
            if status == PT_OK and len(args) > 2:
                return _qq_finish(web, args[2])
            if status == PT_EXPIRED:
                on_event(EXPIRED, {})
                raise AuthError("QR code expired; run `qqmusic login` again")
            if status == PT_REFUSED:
                on_event(REFUSED, {})
                raise AuthError("login refused on the phone")
            _report(on_event, SCANNED if status == PT_SCANNED else WAITING, last)
            time.sleep(poll)
    raise AuthError("timed out waiting for the QR scan")


def _qq_finish(web: httpx.Client, check_sig_url: str) -> Credential:
    # Following the callback's URL is what the browser does; it plants p_skey for graph.qq.com.
    web.get(check_sig_url, headers=PT_REFERER)
    p_skey = web.cookies.get("p_skey")
    if not p_skey:
        raise AuthError("QQ login finished but no p_skey cookie was issued")
    form = dict(client_id=QQ_CONNECT_APP, redirect_uri=landing_page(1), response_type="code", state="state")
    form.update(scope="get_user_info,get_app_friends", openapi="1010_1030", switch="")
    form.update(from_ptlogin=1, src=1, update_auth=1, ui=str(uuid.uuid4()))
    form.update(g_tk=hash33(p_skey), auth_time=_now_ms())
    answer = web.post(OAUTH_URL, data=form)
    redirect = answer.headers.get("Location", "")
    code = parse_qs(urlsplit(redirect).query).get("code", [""])[0]
    if not code:
        raise AuthError(f"graph.qq.com did not return an authorization code (HTTP {answer.status_code})")
    return _exchange("QQConnectLogin.LoginServer", "QQLogin", {"code": code}, QQ, "qq-qr")


# -- WeChat ---------------------------------------------------------------------------------------


def wechat_login(on_event: EventFn, *, timeout: float = 180.0) -> Credential:
    with _browser() as web:
        page = web.get(
            f"{WX_HOST}/connect/qrconnect",
            params=dict(
                appid=WX_APP,
                redirect_uri=landing_page(2),
                response_type="code",
                scope="snsapi_login",
                state="STATE",
                href="https://y.qq.com/mediastyle/music_v17/src/css/popup_wechat.css#wechat_redirect",
            ),
        )
        qr_id = wx_qr_uuid(page.text)
        if not qr_id:
            raise AuthError(f"could not find the WeChat QR code (HTTP {page.status_code})")
        image = web.get(f"{WX_HOST}/connect/qrcode/{qr_id}", headers={"Referer": f"{WX_HOST}/connect/qrconnect"})
        on_event(
            QR_READY,
            {
                "kind": "wechat",
                "image": image.content,
                "mimetype": "image/jpeg",
                "url": f"{WX_HOST}/connect/confirm?uuid={qr_id}",
            },
        )
        stop_at = time.monotonic() + timeout
        last: list[str] = []
        previous: int | None = None
        while stop_at - time.monotonic() > 0:
            query: dict[str, Any] = {"uuid": qr_id, "_": _now_ms()}
            if previous is not None:
                query["last"] = previous
            try:
                reply = web.get(WX_POLL_URL, params=query, headers={"Referer": f"{WX_HOST}/"}, timeout=35.0)
            except httpx.TimeoutException:
                continue  # long poll timed out with no news
            errcode, wx_code = wx_status(reply.text)
            if errcode is None:
                time.sleep(1)
                continue
            if errcode == WX_OK and wx_code:
                param = {"strAppid": WX_APP, "code": wx_code}
                return _exchange("music.login.LoginServer", "Login", param, WECHAT, "wechat-qr")
            if errcode == WX_EXPIRED:
                on_event(EXPIRED, {})
                raise AuthError("QR code expired; run `qqmusic login` again")
            if errcode == WX_REFUSED:
                on_event(REFUSED, {})
                raise AuthError("login refused on the phone")
            previous = errcode
            _report(on_event, SCANNED if errcode == WX_SCANNED else WAITING, last)
    raise AuthError("timed out waiting for the QR scan")


# -- refresh --------------------------------------------------------------------------------------

# Fields the refresh call wants, per login type; missing ones are sent empty.
_REFRESH_FIELDS = {
    WECHAT: ("musickey", "str_musicid", "openid", "unionid", "refresh_key", "refresh_token"),
    QQ: ("musickey", "musicid", "openid", "access_token", "refresh_key", "refresh_token", "expired_in"),
}


def refresh(credential: Credential) -> Credential:
    """Renew the session key with `music.login.LoginServer.Login` in `loginMode` 2."""
    saved = credential.login
    known: dict[str, Any] = {
        "musickey": credential.musickey,
        "str_musicid": credential.uin,
        "musicid": int(credential.uin) if credential.uin.isdigit() else credential.uin,
        "expired_in": saved.get("expired_at", 0),
    }
    fields = _REFRESH_FIELDS.get(credential.login_type, _REFRESH_FIELDS[QQ])
    param = {name: known.get(name, saved.get(name, "")) for name in fields}
    param["loginMode"] = 2
    fresh = _exchange("music.login.LoginServer", "Login", param, credential.login_type, credential.source or "refresh")
    fresh.source = credential.source
    fresh.cookies = {k: v for k, v in credential.cookies.items() if k not in ("qm_keyst", "qqmusic_key")}
    for name in ("openid", "unionid", "refresh_token", "refresh_key", "access_token"):
        if saved.get(name) and not fresh.login.get(name):
            fresh.login[name] = saved[name]
    return fresh
