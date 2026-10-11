"""Login parsing and both QR flows against a scripted fake of the QQ / WeChat endpoints.

Waiting-state strings below were captured from the real endpoints on 2026-10-11; success
strings follow the same format with fake values.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from qq_music_cli import login
from qq_music_cli.auth import QQ, WECHAT
from qq_music_cli.client import Client
from qq_music_cli.errors import AuthError
from conftest import ok

REAL_WX_IMG = '<img class="qrcode lightBorder js_qrcode_img" src="/connect/qrcode/031S0Qr20P9Z000G">'
REAL_WX_WAITING = "window.wx_errcode=408;window.wx_code='';"
REAL_QQ_WAITING = "ptuiCB('66','0','','0','二维码未失效。', '')"
CHECK_SIG = (
    "https://ptlogin2.graph.qq.com/check_sig?pttype=1&uin=12345&service=ptqrlogin&nodirect=0"
    "&ptsigx=fakesig&s_url=https%3A%2F%2Fgraph.qq.com%2Foauth2.0%2Flogin_jump&ptlang=2052"
)
LOGIN_REPLY = {
    "code": 0,
    "musicid": 12345,
    "str_musicid": "12345",
    "musickey": "Q_H_L_fake",
    "encryptUin": "fake_euin",
    "musickeyCreateTime": 1_800_000_000,
    "keyExpiresIn": 259_200,
    "refresh_token": "rt",
}


# -- parsers --------------------------------------------------------------------------------------


def test_ptui_args_real_waiting_reply():
    assert login.ptui_args(REAL_QQ_WAITING) == ["66", "0", "", "0", "二维码未失效。", ""]


def test_ptui_args_success_and_escapes():
    text = f"ptuiCB('0','0','{CHECK_SIG}','0','登录成功！', 'it\\'s me')"
    args = login.ptui_args(text)
    assert args[0] == "0" and args[2] == CHECK_SIG and args[5] == "it's me"


def test_ptui_args_garbage():
    assert login.ptui_args("<html>nope</html>") == []


def test_wx_status_real_waiting_and_success():
    assert login.wx_status(REAL_WX_WAITING) == (408, "")
    assert login.wx_status("window.wx_errcode=405;window.wx_code='0a1B2c';") == (405, "0a1B2c")
    assert login.wx_status("nothing here") == (None, "")


def test_wx_qr_uuid_from_real_markup():
    assert login.wx_qr_uuid(f"<div>{REAL_WX_IMG}</div>") == "031S0Qr20P9Z000G"
    assert login.wx_qr_uuid("<html>no qr</html>") is None


# -- flows ----------------------------------------------------------------------------------------


class FakeTencent:
    """Scripted endpoints. `polls` is the sequence of poll replies to hand out."""

    def __init__(self, polls: list[str]) -> None:
        self.polls = list(polls)
        self.poll_queries: list[dict[str, list[str]]] = []
        self.exchanges: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        path = url.path
        if url.host == "u.y.qq.com":
            body = json.loads(request.content)
            self.exchanges.append(body)
            return ok(LOGIN_REPLY)
        if path == "/connect/qrconnect":
            return httpx.Response(200, text=f"<html>{REAL_WX_IMG}</html>")
        if path.startswith("/connect/qrcode/"):
            return httpx.Response(200, content=b"\xff\xd8jpeg")
        if path in ("/connect/l/qrconnect", "/ptqrlogin"):
            self.poll_queries.append(parse_qs(url.query.decode()))
            return httpx.Response(200, text=self.polls.pop(0))
        if path == "/ptqrshow":
            return httpx.Response(200, content=b"\x89PNG", headers={"Set-Cookie": "qrsig=abcDEF123; Domain=.qq.com; Path=/"})
        if path == "/check_sig":
            return httpx.Response(302, headers={"Set-Cookie": "p_skey=PSKEY; Domain=.qq.com; Path=/", "Location": "https://graph.qq.com/x"})
        if path == "/oauth2.0/authorize":
            return httpx.Response(302, headers={"Location": "https://y.qq.com/portal/wx_redirect.html?code=OAUTHCODE&state=state"})
        return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch):
    def install(polls: list[str]) -> FakeTencent:
        server = FakeTencent(polls)
        transport = httpx.MockTransport(server.handler)
        monkeypatch.setattr(
            login, "_browser", lambda: httpx.Client(transport=transport, follow_redirects=False)
        )
        monkeypatch.setattr(
            login, "Client", lambda cred: Client(cred, transport=transport, sleep=lambda s: None, min_interval=0)
        )
        monkeypatch.setattr(login.time, "sleep", lambda s: None)
        return server

    return install


def test_wechat_flow(fake):
    server = fake([REAL_WX_WAITING, "window.wx_errcode=404;window.wx_code='';", "window.wx_errcode=405;window.wx_code='WXCODE';"])
    events: list[tuple[str, dict]] = []
    cred = login.wechat_login(lambda e, info: events.append((e, info)), timeout=30)
    assert [e for e, _ in events] == ["qr_ready", "waiting", "scanned"]
    assert events[0][1]["url"].endswith("uuid=031S0Qr20P9Z000G")
    assert "last" not in server.poll_queries[0]
    assert server.poll_queries[1]["last"] == ["408"] and server.poll_queries[2]["last"] == ["404"]
    req = server.exchanges[0]["req_0"]
    assert (req["module"], req["method"]) == ("music.login.LoginServer", "Login")
    assert req["param"] == {"strAppid": login.WX_APP, "code": "WXCODE"}
    assert server.exchanges[0]["comm"]["tmeLoginType"] == WECHAT
    assert cred.uin == "12345" and cred.musickey == "Q_H_L_fake" and cred.source == "wechat-qr"


def test_wechat_expired(fake):
    fake(["window.wx_errcode=402;window.wx_code='';"])
    with pytest.raises(AuthError, match="expired"):
        login.wechat_login(lambda e, i: None, timeout=30)


def test_qq_flow(fake):
    server = fake([REAL_QQ_WAITING, "ptuiCB('67','0','','0','二维码认证中。', '')", f"ptuiCB('0','0','{CHECK_SIG}','0','登录成功！', 'nick')"])
    events: list[str] = []
    cred = login.qq_login(lambda e, info: events.append(e), timeout=30)
    assert events == ["qr_ready", "waiting", "scanned"]
    first = server.poll_queries[0]
    expected_token = 0
    for ch in "abcDEF123":
        expected_token = (expected_token * 33 + ord(ch)) & 0x7FFFFFFF
    assert first["ptqrtoken"] == [str(expected_token)] and first["aid"] == ["716027609"]
    req = server.exchanges[0]["req_0"]
    assert (req["module"], req["method"], req["param"]) == ("QQConnectLogin.LoginServer", "QQLogin", {"code": "OAUTHCODE"})
    assert server.exchanges[0]["comm"]["tmeLoginType"] == QQ
    assert cred.source == "qq-qr"


def test_qq_refused(fake):
    fake(["ptuiCB('68','0','','0','本次登录已被拒绝', '')"])
    with pytest.raises(AuthError, match="refused"):
        login.qq_login(lambda e, i: None, timeout=30)


def test_refresh_sends_expected_fields(fake):
    server = fake([])
    from qq_music_cli.auth import Credential

    cred = Credential(uin="12345", musickey="W_X_old", login_type=WECHAT, source="wechat-qr",
                      login={"openid": "oid", "unionid": "uid", "refresh_token": "rt"})
    fresh = login.refresh(cred)
    param = server.exchanges[0]["req_0"]["param"]
    assert param == {"musickey": "W_X_old", "str_musicid": "12345", "openid": "oid", "unionid": "uid",
                     "refresh_key": "", "refresh_token": "rt", "loginMode": 2}
    assert fresh.musickey == "Q_H_L_fake" and fresh.source == "wechat-qr" and fresh.login["openid"] == "oid"


def test_oauth_redirect_uri_uses_qq_landing():
    assert parse_qs(urlsplit(login.landing_page(1)).query)["login_type"] == ["1"]
    assert parse_qs(urlsplit(login.landing_page(2)).query)["login_type"] == ["2"]
