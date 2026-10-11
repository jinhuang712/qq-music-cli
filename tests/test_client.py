from __future__ import annotations


import httpx
import pytest

from qq_music_cli.auth import hash33
from qq_music_cli.errors import ApiError, AuthError, NetworkError, QQMusicError, RiskControlError
from conftest import FAKE_KEY, FAKE_UIN, ok, rpc_body


def seen_bodies(make_client, handler_response=None):
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return handler_response(request) if handler_response else ok({"x": 1})

    return seen, make_client(handler)


# -- request shape --------------------------------------------------------------------------------


def test_comm_contents(make_client):
    seen, client = seen_bodies(make_client)
    assert client.rpc("mod.A", "Meth", {"k": "v"}) == {"x": 1}
    body = rpc_body(seen[0])
    comm = body["comm"]
    assert comm["ct"] == 24 and comm["cv"] == 4747474
    assert comm["uin"] == FAKE_UIN
    assert isinstance(comm["g_tk"], int) and comm["g_tk"] == hash33(FAKE_KEY)
    assert comm["g_tk_new_20200303"] == comm["g_tk"]
    assert body["req_0"] == {"module": "mod.A", "method": "Meth", "param": {"k": "v"}}
    assert str(seen[0].url) == "https://u.y.qq.com/cgi-bin/musicu.fcg"
    assert seen[0].method == "POST"


def test_cookie_header_has_session_cookies(make_client):
    seen, client = seen_bodies(make_client)
    client.rpc("m", "n")
    cookie = seen[0].headers["cookie"]
    assert f"qm_keyst={FAKE_KEY}" in cookie
    assert f"wxuin={FAKE_UIN}" in cookie
    names = {part.split("=", 1)[0].strip() for part in cookie.split(";")}
    assert "uin" not in names


def with_set_cookie(response):
    response.headers["Set-Cookie"] = "evil=1; Domain=.qq.com"
    return response


def test_server_set_cookie_is_never_replayed(make_client):
    seen, client = seen_bodies(
        make_client, lambda r: with_set_cookie(ok({}))
    )
    client.rpc("m", "n")
    client.rpc("m", "n")
    assert "evil" not in seen[1].headers.get("cookie", "")


def test_anonymous_client_has_zero_uin_and_no_cookie(make_client):
    seen, client = seen_bodies(make_client)
    anon = make_client(lambda r: (seen.append(r), ok({}))[1], credential=None)
    anon.rpc("m", "n")
    comm = rpc_body(seen[0])["comm"]
    assert comm["uin"] == "0" and comm["g_tk"] == 5381
    assert "cookie" not in seen[0].headers


def test_comm_override_replaces_comm_entirely(make_client):
    seen, client = seen_bodies(make_client)
    client.rpc("m", "n", comm={"ct": 11, "cv": 1})
    assert rpc_body(seen[0])["comm"] == {"ct": 11, "cv": 1}


def test_comm_extra_is_merged(make_client):
    seen, client = seen_bodies(make_client)
    client.rpc("m", "n", comm_extra={"tmeLoginType": 1, "ct": 99})
    comm = rpc_body(seen[0])["comm"]
    assert comm["tmeLoginType"] == 1 and comm["ct"] == 99 and comm["cv"] == 4747474


def test_rpc_many_preserves_order(make_client):
    def handler(request):
        body = rpc_body(request)
        return ok(*[{"method": body[f"req_{i}"]["method"]} for i in range(2)])

    client = make_client(handler)
    out = client.rpc_many([("m", "First", {}), ("m", "Second", {})])
    assert [d["method"] for d in out] == ["First", "Second"]


# -- per-request errors ---------------------------------------------------------------------------


def slot(code, data=None):
    return httpx.Response(200, json={"code": 0, "req_0": {"code": code, "data": data}})


def test_auth_error_code_1000(make_client):
    client = make_client(lambda r: slot(1000))
    with pytest.raises(AuthError) as e:
        client.rpc("mod.A", "Meth")
    assert e.value.exit_code == 3 and e.value.code == 1000
    assert e.value.module == "mod.A" and e.value.method == "Meth"


@pytest.mark.parametrize("code", [104400, 104401])
def test_other_auth_codes(make_client, code):
    with pytest.raises(AuthError):
        make_client(lambda r: slot(code)).rpc("m", "n")


def test_risk_control_retried_for_idempotent(make_client):
    calls = []

    def handler(r):
        calls.append(1)
        return slot(2001)

    client = make_client(handler)
    with pytest.raises(RiskControlError) as e:
        client.rpc("m", "n")
    assert e.value.exit_code == 4
    assert len(calls) == 3  # risk_retries=2 -> 3 attempts
    assert len(client.sleeps) == 2 and client.sleeps[0] >= 3  # backed off between them


def test_risk_control_custom_retries(make_client):
    calls = []
    client = make_client(lambda r: (calls.append(1), slot(2001))[1])
    with pytest.raises(RiskControlError):
        client.rpc("m", "n", risk_retries=0)
    assert len(calls) == 1
    with pytest.raises(RiskControlError):
        client.rpc("m", "n", risk_retries=4)
    assert len(calls) == 1 + 5


def test_risk_control_not_retried_for_non_idempotent(make_client):
    calls = []
    client = make_client(lambda r: (calls.append(1), slot(2001))[1])
    with pytest.raises(RiskControlError):
        client.rpc("m", "n", idempotent=False)
    assert len(calls) == 1
    assert client.sleeps == []


def test_risk_control_recovers(make_client):
    responses = iter([slot(2001), slot(0, {"v": 1})])
    client = make_client(lambda r: next(responses))
    assert client.rpc("m", "n") == {"v": 1}


def test_sign_required_code_2000(make_client):
    with pytest.raises(ApiError, match="signed"):
        make_client(lambda r: slot(2000)).rpc("m", "n")


def test_unknown_slot_code_is_api_error_with_msg(make_client):
    with pytest.raises(ApiError) as e:
        make_client(lambda r: slot(7, {"msg": "boom"})).rpc("m", "n")
    assert e.value.code == 7 and e.value.message == "boom" and e.value.exit_code == 1


def test_data_ret_code_nonzero_is_api_error(make_client):
    with pytest.raises(ApiError) as e:
        make_client(lambda r: slot(0, {"retCode": 5, "msg": "bad"})).rpc("m", "n")
    assert e.value.code == 5 and e.value.module == "m" and e.value.method == "n"


def test_data_ret_code_zero_is_fine(make_client):
    assert make_client(lambda r: slot(0, {"retCode": 0, "a": 1})).rpc("m", "n") == {"retCode": 0, "a": 1}


def test_null_data_becomes_empty_dict(make_client):
    assert make_client(lambda r: slot(0, None)).rpc("m", "n") == {}


@pytest.mark.parametrize("outer,exc", [(1000, AuthError), (2001, RiskControlError), (500001, ApiError)])
def test_outer_code_errors(make_client, outer, exc):
    client = make_client(lambda r: httpx.Response(200, json={"code": outer}))
    with pytest.raises(exc) as e:
        client.rpc("m", "n", idempotent=False)
    assert e.value.code == outer


def test_missing_request_slot(make_client):
    client = make_client(lambda r: httpx.Response(200, json={"code": 0}))
    with pytest.raises(ApiError, match="no slot for m.n"):
        client.rpc("m", "n")


def test_non_json_and_non_object_bodies(make_client):
    with pytest.raises(ApiError, match="non-JSON"):
        make_client(lambda r: httpx.Response(200, text="<html>nope</html>")).rpc("m", "n")
    with pytest.raises(ApiError, match="shape"):
        make_client(lambda r: httpx.Response(200, text="[1,2]")).rpc("m", "n")


def test_all_errors_are_qqmerror_with_dict(make_client):
    with pytest.raises(QQMusicError) as e:
        make_client(lambda r: slot(1000)).rpc("m", "n")
    d = e.value.to_dict()
    assert d["kind"] == "auth" and d["code"] == 1000 and d["module"] == "m"


# -- HTTP errors ----------------------------------------------------------------------------------


def test_http_500_retried_then_succeeds(make_client):
    responses = iter([httpx.Response(500), httpx.Response(502), ok({"v": 1})])
    calls = []
    client = make_client(lambda r: (calls.append(1), next(responses))[1])
    assert client.rpc("m", "n") == {"v": 1}
    assert len(calls) == 3
    assert len(client.sleeps) == 2


def test_http_500_exhausts_retries(make_client):
    calls = []
    client = make_client(lambda r: (calls.append(1), httpx.Response(503))[1], retries=3)
    with pytest.raises(NetworkError) as e:
        client.rpc("m", "n")
    assert e.value.exit_code == 5 and e.value.code == 503
    assert len(calls) == 4


def test_http_500_sent_once_when_not_idempotent(make_client):
    calls = []
    client = make_client(lambda r: (calls.append(1), httpx.Response(500))[1])
    with pytest.raises(NetworkError):
        client.rpc("m", "n", idempotent=False)
    assert len(calls) == 1


def test_http_429_is_retried(make_client):
    responses = iter([httpx.Response(429), ok({"v": 2})])
    assert make_client(lambda r: next(responses)).rpc("m", "n") == {"v": 2}


def test_transport_error_retried_then_network_error(make_client):
    calls = []

    def handler(r):
        calls.append(1)
        raise httpx.ConnectError("offline")

    client = make_client(handler, retries=2)
    with pytest.raises(NetworkError, match="ConnectError"):
        client.rpc("m", "n")
    assert len(calls) == 3
    calls.clear()
    with pytest.raises(NetworkError):
        client.rpc("m", "n", idempotent=False)
    assert len(calls) == 1


def test_throttle_sleeps_when_min_interval_set(cred):
    sleeps: list[float] = []
    client = __import__("qq_music_cli.client", fromlist=["Client"]).Client(
        cred, transport=httpx.MockTransport(lambda r: ok({})), sleep=sleeps.append, min_interval=1000
    )
    client.rpc("m", "n")
    client.rpc("m", "n")
    client.close()
    assert sleeps and all(0 < s <= 1000 for s in sleeps)


# -- get_legacy -----------------------------------------------------------------------------------


def test_get_legacy_plain_json_and_query(make_client):
    seen = []

    def handler(r):
        seen.append(r)
        return httpx.Response(200, json={"code": 0, "lyric": "la la"})

    client = make_client(handler)
    data = client.get_legacy("https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg", {"songmid": "abc", "nobase64": 1})
    assert data["lyric"] == "la la"
    req = seen[0]
    assert req.method == "GET" and req.url.path == "/lyric/fcgi-bin/fcg_query_lyric_new.fcg"
    q = dict(req.url.params)
    assert q["songmid"] == "abc" and q["g_tk"] == str(hash33(FAKE_KEY)) and q["loginUin"] == FAKE_UIN
    assert f"qm_keyst={FAKE_KEY}" in req.headers["cookie"]


@pytest.mark.parametrize("body", ['MusicJsonCallback({"code":0,"lyric":"x"})', 'cb({"code":0,"lyric":"x"});', ' jsonp1 ( {"code": 0, "lyric": "x"} ) '])
def test_get_legacy_jsonp(make_client, body):
    client = make_client(lambda r: httpx.Response(200, text=body))
    assert client.get_legacy("https://c.y.qq.com/x/y.fcg", {})["lyric"] == "x"


def test_get_legacy_jsonp_with_parens_inside_payload(make_client):
    client = make_client(lambda r: httpx.Response(200, text='cb({"code":0,"lyric":"(live) version"})'))
    assert client.get_legacy("https://c.y.qq.com/x/y.fcg", {})["lyric"] == "(live) version"


def test_get_legacy_error_codes(make_client):
    with pytest.raises(AuthError):
        make_client(lambda r: httpx.Response(200, json={"code": 1000})).get_legacy("https://c.y.qq.com/a/b.fcg", {})
    with pytest.raises(ApiError) as e:
        make_client(lambda r: httpx.Response(200, json={"code": -1, "msg": "nope"})).get_legacy("https://c.y.qq.com/a/b.fcg", {})
    assert e.value.module == "b.fcg"
    # missing code is treated as success
    assert make_client(lambda r: httpx.Response(200, json={"lyric": "x"})).get_legacy("https://c.y.qq.com/a/b.fcg", {}) == {"lyric": "x"}


def test_get_legacy_anonymous(make_client):
    seen = []
    client = make_client(lambda r: (seen.append(r), httpx.Response(200, json={}))[1], credential=None)
    client.get_legacy("https://c.y.qq.com/a/b.fcg", {})
    assert dict(seen[0].url.params)["g_tk"] == "5381" and "cookie" not in seen[0].headers


def test_get_legacy_500_retried(make_client):
    responses = iter([httpx.Response(500), httpx.Response(200, json={"code": 0})])
    assert make_client(lambda r: next(responses)).get_legacy("https://c.y.qq.com/a/b.fcg", {}) == {"code": 0}
