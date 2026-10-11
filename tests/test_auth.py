from __future__ import annotations

import json
import os
import stat

import pytest

from qq_music_cli.auth import (
    KEY_LIFETIME,
    LOGIN_FIELDS,
    QQ,
    WECHAT,
    Credential,
    CredentialStore,
    credential_from_cookies,
    credential_from_login,
    hash33,
    parse_cookie_text,
)
from qq_music_cli.errors import AuthError, UsageError

UIN = "1152921500000000001"


def shift_hash(s: str, seed: int) -> int:
    h = seed
    for c in s:
        h += (h << 5) + ord(c)
        h &= 0x7FFFFFFF
    return h


# -- hash33 ---------------------------------------------------------------------------------------


def test_hash33_empty_returns_seed():
    assert hash33("") == 5381
    assert hash33("", 0) == 0


def test_hash33_known_value():
    # 5381*33 + ord("a") = 177573 + 97
    assert hash33("a") == 177670
    assert hash33("a", 0) == 97


@pytest.mark.parametrize("seed", [5381, 0])
@pytest.mark.parametrize("text", ["a", "W_X_fake_key", "x" * 500, "歌曲"])
def test_hash33_matches_shift_formula(text, seed):
    assert hash33(text, seed) == shift_hash(text, seed)


def test_hash33_seed_changes_result_and_stays_31_bit():
    assert hash33("W_X_fake_key", 5381) != hash33("W_X_fake_key", 0)
    assert 0 <= hash33("y" * 1000) <= 0x7FFFFFFF


# -- parse_cookie_text ----------------------------------------------------------------------------


def test_parse_playwright_storage_state_filters_domain_and_captures_expiry():
    state = {
        "cookies": [
            {"name": "qm_keyst", "value": "W_X_fake_key", "domain": ".qq.com", "expires": 1_900_000_000},
            {"name": "wxuin", "value": UIN, "domain": ".y.qq.com", "expires": -1},
            {"name": "tracker", "value": "zzz", "domain": ".example.com", "expires": 1_900_000_000},
        ],
        "origins": [],
    }
    cookies, expiry = parse_cookie_text(json.dumps(state))
    assert cookies == {"qm_keyst": "W_X_fake_key", "wxuin": UIN}
    assert expiry == 1_900_000_000


def test_parse_session_cookie_has_no_expiry():
    state = {"cookies": [{"name": "qm_keyst", "value": "W_X_fake_key", "domain": ".qq.com", "expires": -1}]}
    assert parse_cookie_text(json.dumps(state)) == ({"qm_keyst": "W_X_fake_key"}, None)


def test_parse_json_cookie_list_with_expiration_date():
    items = [
        {"name": "qm_keyst", "value": "W_X_fake_key", "domain": ".qq.com", "expirationDate": 1_900_000_123.456},
        {"name": "wxuin", "value": UIN, "domain": ".qq.com", "expirationDate": 1_900_000_999},
        {"name": "empty", "value": "", "domain": ".qq.com"},
    ]
    cookies, expiry = parse_cookie_text(json.dumps(items))
    assert cookies == {"qm_keyst": "W_X_fake_key", "wxuin": UIN}
    assert expiry == 1_900_000_123


def test_parse_json_list_without_domain_defaults_to_qq():
    cookies, _ = parse_cookie_text(json.dumps([{"name": "a", "value": "b"}]))
    assert cookies == {"a": "b"}


def test_parse_cookie_header():
    cookies, expiry = parse_cookie_text("Cookie: a=b; c=d=e;  ; empty=")
    assert cookies == {"a": "b", "c": "d=e"}
    assert expiry is None


def test_parse_bare_cookie_string_and_first_value_wins():
    cookies, _ = parse_cookie_text("a=1; a=2; b=3")
    assert cookies == {"a": "1", "b": "3"}


def test_parse_cookie_domain_filter_rejects_lookalike_domains():
    state = {"cookies": [{"name": "x", "value": "1", "domain": ".evilqq.com"}]}
    cookies, _ = parse_cookie_text(json.dumps(state))
    assert cookies == {}


# -- credential_from_cookies ----------------------------------------------------------------------


def test_credential_from_wechat_cookies():
    cred = credential_from_cookies({"qm_keyst": "W_X_fake_key", "wxuin": UIN, "euin": "fake_euin", "wxopenid": "oid"})
    assert cred.login_type == WECHAT
    assert cred.uin == UIN
    assert cred.musickey == "W_X_fake_key"
    assert cred.euin == "fake_euin"
    assert cred.login == {"openid": "oid"}
    assert cred.source == "cookie-import"
    assert cred.expires_at - cred.created_at == KEY_LIFETIME


def test_credential_from_qq_cookies_strips_o_prefix_and_zeros():
    cred = credential_from_cookies({"qqmusic_key": "Q_H_L_fake", "uin": "o0012345"})
    assert cred.login_type == QQ
    assert cred.uin == "12345"
    assert cred.musickey == "Q_H_L_fake"


def test_credential_from_cookies_uses_key_expiry():
    cred = credential_from_cookies({"qm_keyst": "W_X_fake_key", "wxuin": UIN}, key_expiry=1_900_000_000)
    assert cred.expires_at == 1_900_000_000
    assert cred.created_at == 1_900_000_000 - KEY_LIFETIME


def test_credential_from_cookies_missing_key():
    with pytest.raises(UsageError) as e:
        credential_from_cookies({"wxuin": UIN})
    assert e.value.exit_code == 2


def test_credential_from_cookies_missing_uin():
    with pytest.raises(UsageError):
        credential_from_cookies({"qm_keyst": "W_X_fake_key"})
    with pytest.raises(UsageError):
        credential_from_cookies({"qm_keyst": "Q_H_L_fake"})
    # a QQ-style uin does not satisfy a WeChat key
    with pytest.raises(UsageError):
        credential_from_cookies({"qm_keyst": "W_X_fake_key", "uin": "o012345"})


# -- Credential -----------------------------------------------------------------------------------


def test_cookie_jar_wechat(cred):
    jar = cred.cookie_jar()
    assert jar["wxuin"] == UIN
    assert jar["login_type"] == "2"
    assert jar["tmeLoginType"] == "1"
    assert "uin" not in jar
    assert jar["qm_keyst"] == jar["qqmusic_key"] == "W_X_fake_key"
    assert jar["euin"] == "fake_euin"


def test_cookie_jar_qq():
    cred = Credential(uin="12345", musickey="Q_H_L_fake", login_type=QQ)
    jar = cred.cookie_jar()
    assert jar["uin"] == "12345"
    assert jar["login_type"] == "1"
    assert jar["tmeLoginType"] == "2"
    assert "wxuin" not in jar


def test_g_tk_and_summary(cred):
    assert cred.g_tk == hash33("W_X_fake_key")
    s = cred.summary()
    assert s["login_type"] == "wechat"
    assert s["can_refresh"] is True
    assert "musickey" not in json.dumps(s)
    assert cred.seconds_left(now=cred.expires_at - 10) == 10
    assert Credential(uin="1", musickey="k", login_type=QQ).seconds_left() is None


# -- credential_from_login ------------------------------------------------------------------------


def login_response(**extra):
    return {
        "musicid": 1152921500000000001,
        "str_musicid": UIN,
        "musickey": "W_X_fake_key",
        "musickeyCreateTime": 1_800_000_000,
        "keyExpiresIn": 259_200,
        "encryptUin": "fake_euin",
        "loginType": 1,
        "openid": "oid",
        "refresh_key": "rk",
        "nick": "Fake",
        "phoneNo": "13800000000",
        **extra,
    }


def test_credential_from_login_keeps_only_login_fields():
    cred = credential_from_login(login_response(), "qr")
    assert "phoneNo" not in cred.login
    assert set(cred.login) <= set(LOGIN_FIELDS)
    assert cred.login["refresh_key"] == "rk"
    assert "musickey" not in cred.login
    assert "13800000000" not in cred.to_json()
    assert cred.uin == UIN and cred.euin == "fake_euin" and cred.login_type == WECHAT


def test_credential_from_login_expiry():
    cred = credential_from_login(login_response(keyExpiresIn=1000), "qr")
    assert cred.created_at == 1_800_000_000
    assert cred.expires_at == 1_800_001_000


def test_credential_from_login_defaults_lifetime_and_type():
    data = login_response()
    del data["keyExpiresIn"], data["loginType"]
    cred = credential_from_login(data, "qr")
    assert cred.expires_at == 1_800_000_000 + KEY_LIFETIME
    assert cred.login_type == WECHAT  # inferred from the W_X prefix


@pytest.mark.parametrize("patch", [{"musickey": ""}, {"str_musicid": "0", "musicid": 0}, {"str_musicid": "", "musicid": ""}])
def test_credential_from_login_rejects_incomplete(patch):
    with pytest.raises(AuthError) as e:
        credential_from_login(login_response(**patch), "qr")
    assert e.value.exit_code == 3


# -- CredentialStore ------------------------------------------------------------------------------


def test_store_round_trip_and_mode(tmp_path, cred):
    store = CredentialStore(path=tmp_path / "sub" / "c.json")
    assert store.load() is None
    store.save(cred)
    assert store.load() == cred
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600
    assert store.backend == f"file:{store.path}"
    assert not list(store.path.parent.glob("*.tmp"))


def test_store_overwrite_keeps_mode_and_updates(tmp_path, cred):
    store = CredentialStore(path=tmp_path / "c.json")
    store.save(cred)
    cred.musickey = "W_X_other"
    store.save(cred)
    assert store.load().musickey == "W_X_other"
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


def test_store_env_path_and_clear(tmp_path, monkeypatch, cred):
    p = tmp_path / "env.json"
    monkeypatch.setenv("QQMUSIC_CLI_CREDENTIAL_FILE", str(p))
    store = CredentialStore()
    assert store.path == p
    store.save(cred)
    assert p.exists()
    assert store.clear() is True
    assert store.clear() is False
    assert store.load() is None


def test_store_without_path_reports_keychain_backend(monkeypatch):
    monkeypatch.delenv("QQMUSIC_CLI_CREDENTIAL_FILE")
    store = CredentialStore()
    assert store.path is None
    assert store.backend.startswith("keychain:")
