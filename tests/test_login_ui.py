"""LoginPage serves on 127.0.0.1 only; these tests talk to it over loopback, never the internet."""

import json
import time
import urllib.error
import urllib.request

import pytest

from qq_music_cli.login_ui import LoginPage


def get(url: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, "", b""


@pytest.fixture
def page():
    p = LoginPage()
    p.start()
    yield p
    p.close(linger=0)


def test_serves_page_status_and_qr(page):
    status, ctype, body = get(page.url)
    assert status == 200 and ctype.startswith("text/html")
    assert "QQ 音乐登录".encode() in body

    status, _, body = get(page.url + "status")
    assert status == 200
    assert json.loads(body) == {"status": "starting", "qr_version": -1}

    assert get(page.url + "qr")[0] == 404  # no QR yet

    deadline = time.time() + 180
    page.set_qr(b"\x89PNGfake", "image/png", "QQ", deadline)
    status, ctype, body = get(page.url + "qr?v=0")
    assert (status, ctype, body) == (200, "image/png", b"\x89PNGfake")
    state = json.loads(get(page.url + "status")[2])
    assert state["status"] == "waiting" and state["app"] == "QQ" and state["qr_version"] == 0

    page.set_qr(b"second", "image/jpeg", "微信", deadline)
    assert json.loads(get(page.url + "status")[2])["qr_version"] == 1

    page.update(status="success", nickname="jin")
    state = json.loads(get(page.url + "status")[2])
    assert state["status"] == "success" and state["nickname"] == "jin"


def test_requires_path_token(page):
    port = page.url.split(":")[2].split("/")[0]
    assert get(f"http://127.0.0.1:{port}/")[0] == 404
    assert get(f"http://127.0.0.1:{port}/wrong-token/status")[0] == 404
    assert page.url.startswith("http://127.0.0.1:")


def test_close_stops_serving():
    p = LoginPage()
    url = p.start()
    assert get(url + "status")[0] == 200
    p.close(linger=0)
    with pytest.raises(urllib.error.URLError):
        urllib.request.urlopen(url + "status", timeout=2)
