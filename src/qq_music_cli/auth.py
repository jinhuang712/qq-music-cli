"""Credential model, storage (macOS Keychain via `keyring`, or a file) and cookie import.

Facts this module relies on (verified against y.qq.com on 2026-10-11):
- The session key `musickey` is the `qm_keyst` / `qqmusic_key` cookie; WeChat keys start with `W_X`.
- WeChat logins carry the account id in `wxuin` (there is no `uin` cookie); QQ logins use `uin`.
- `g_tk` = hash33(musickey, seed 5381) and is sent as an int in `comm`.
- The key cookies expire 3 days after login.
- Browser cookies `login_type` / `tmeLoginType` are 2 / 1 for WeChat (the two use opposite numbering).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import AuthError, UsageError

KEY_LIFETIME = 259_200  # seconds; observed cookie lifetime and `keyExpiresIn`
KEYRING_SERVICE = "qq-music-cli"
KEYRING_USER = "credential"

WECHAT = 1
QQ = 2
# Login-response fields worth keeping: what refresh needs plus identity. Phone numbers etc. are dropped.
LOGIN_FIELDS = (
    "openid", "unionid", "access_token", "refresh_token", "refresh_key", "expired_at",
    "musicid", "str_musicid", "encryptUin", "loginType", "keyExpiresIn", "musickeyCreateTime", "nick",
)
LOGIN_TYPE_NAMES = {WECHAT: "wechat", QQ: "qq"}


def hash33(s: str, seed: int = 5381) -> int:
    h = seed
    for ch in s:
        h = (h * 33 + ord(ch)) & 0x7FFFFFFF
    return h


@dataclass
class Credential:
    uin: str
    musickey: str
    login_type: int
    euin: str = ""
    created_at: int = 0
    expires_at: int = 0
    source: str = ""
    cookies: dict[str, str] = field(default_factory=dict)
    login: dict[str, Any] = field(default_factory=dict)  # raw login response, kept for refresh

    @property
    def g_tk(self) -> int:
        return hash33(self.musickey)

    @property
    def login_type_name(self) -> str:
        return LOGIN_TYPE_NAMES.get(self.login_type, "unknown")

    def seconds_left(self, now: float | None = None) -> int | None:
        if not self.expires_at:
            return None
        return int(self.expires_at - (now if now is not None else time.time()))

    def cookie_jar(self) -> dict[str, str]:
        """Cookies to send, shaped like the browser's after the same kind of login."""
        jar = dict(self.cookies)
        jar["qm_keyst"] = self.musickey
        jar["qqmusic_key"] = self.musickey
        if self.login_type == WECHAT:
            jar["wxuin"] = self.uin
            jar.setdefault("login_type", "2")
            jar.setdefault("tmeLoginType", "1")
        else:
            jar.setdefault("uin", self.uin)
            jar.setdefault("login_type", "1")
            jar.setdefault("tmeLoginType", "2")
        if self.euin:
            jar.setdefault("euin", self.euin)
        return jar

    def summary(self) -> dict[str, Any]:
        """Non-secret view for `qqmusic status`."""
        return {
            "uin": self.uin,
            "euin": self.euin or None,
            "login_type": self.login_type_name,
            "source": self.source,
            "created_at": self.created_at or None,
            "expires_at": self.expires_at or None,
            "seconds_left": self.seconds_left(),
            "can_refresh": bool(self.login.get("refresh_key") or self.login.get("refresh_token")),
        }

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> Credential:
        data = json.loads(text)
        return cls(**data)


def credential_from_login(data: dict[str, Any], source: str) -> Credential:
    """Build a credential from a `music.login.LoginServer` / `QQConnectLogin` response."""
    key = str(data.get("musickey") or "")
    uin = str(data.get("str_musicid") or data.get("musicid") or "")
    if not key or not uin or uin == "0":
        raise AuthError("login response has no musicid/musickey", data=data)
    login_type = int(data.get("loginType") or (WECHAT if key.startswith("W_X") else QQ))
    created = int(data.get("musickeyCreateTime") or time.time())
    lifetime = int(data.get("keyExpiresIn") or KEY_LIFETIME)
    return Credential(
        uin=uin,
        musickey=key,
        login_type=login_type,
        euin=str(data.get("encryptUin") or ""),
        created_at=created,
        expires_at=created + lifetime,
        source=source,
        login={k: data[k] for k in LOGIN_FIELDS if data.get(k) not in (None, "")},
    )


def _strip_qq_uin(value: str) -> str:
    """Browser `uin` cookies look like `o0123456789`."""
    value = value.strip()
    if value[:1] in ("o", "O"):
        value = value[1:]
    return value.lstrip("0") or "0"


def parse_cookie_text(text: str) -> tuple[dict[str, str], int | None]:
    """Parse cookies from a Playwright storage-state JSON, a JSON cookie list, or a `Cookie:` header.

    Returns the qq.com cookies and the expiry (unix seconds) of `qm_keyst` when the source has it.
    """
    text = text.strip()
    cookies: dict[str, str] = {}
    key_expiry: int | None = None
    if text.startswith("{") or text.startswith("["):
        data = json.loads(text)
        items = data.get("cookies", []) if isinstance(data, dict) else data
        for item in items:
            name, value = item.get("name"), item.get("value")
            domain = str(item.get("domain", ".qq.com"))
            host = domain.lstrip(".")
            if not name or value in (None, "") or not (host == "qq.com" or host.endswith(".qq.com")):
                continue
            cookies.setdefault(name, str(value))
            expiry = item.get("expires", item.get("expirationDate"))
            if name == "qm_keyst" and isinstance(expiry, (int, float)) and expiry > 0:
                key_expiry = int(expiry)
    else:
        if text.lower().startswith("cookie:"):
            text = text.split(":", 1)[1]
        for part in text.split(";"):
            if "=" in part:
                name, value = part.split("=", 1)
                if name.strip() and value.strip():
                    cookies.setdefault(name.strip(), value.strip())
    return cookies, key_expiry


def credential_from_cookies(
    cookies: dict[str, str], *, key_expiry: int | None = None, source: str = "cookie-import"
) -> Credential:
    key = cookies.get("qm_keyst") or cookies.get("qqmusic_key")
    if not key:
        raise UsageError("cookies have no qm_keyst / qqmusic_key; log in on y.qq.com first")
    login_type = WECHAT if key.startswith("W_X") else QQ
    if login_type == WECHAT:
        uin = cookies.get("wxuin", "")
    else:
        raw = cookies.get("uin") or cookies.get("p_uin") or cookies.get("qqmusic_uin") or ""
        uin = _strip_qq_uin(raw) if raw else ""
    if not uin:
        raise UsageError("cookies have no account id (wxuin for WeChat, uin for QQ)")
    now = int(time.time())
    expires = key_expiry or now + KEY_LIFETIME
    created = expires - KEY_LIFETIME if key_expiry else now
    login = {}
    for src, dst in (
        ("wxopenid", "openid"),
        ("wxunionid", "unionid"),
        ("wxrefresh_token", "refresh_token"),
        ("psrf_qqopenid", "openid"),
        ("psrf_qqunionid", "unionid"),
        ("psrf_qqrefresh_token", "refresh_token"),
        ("psrf_qqaccess_token", "access_token"),
    ):
        if cookies.get(src):
            login.setdefault(dst, cookies[src])
    return Credential(
        uin=uin,
        musickey=key,
        login_type=login_type,
        euin=cookies.get("euin", ""),
        created_at=created,
        expires_at=expires,
        source=source,
        cookies=dict(cookies),
        login=login,
    )


class CredentialStore:
    """Keychain by default; a 0600 JSON file when `$QQMUSIC_CLI_CREDENTIAL_FILE` (or `path`) is set."""

    def __init__(self, path: str | Path | None = None) -> None:
        env = os.environ.get("QQMUSIC_CLI_CREDENTIAL_FILE")
        chosen = path or env
        self.path = Path(chosen).expanduser() if chosen else None

    @property
    def backend(self) -> str:
        return f"file:{self.path}" if self.path else f"keychain:{KEYRING_SERVICE}"

    def load(self) -> Credential | None:
        if self.path:
            if not self.path.exists():
                return None
            return Credential.from_json(self.path.read_text())
        import keyring

        text = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        return Credential.from_json(text) if text else None

    def save(self, credential: Credential) -> None:
        text = credential.to_json()
        if self.path:
            os.makedirs(self.path.parent, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(text)
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)
            return
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, text)

    def clear(self) -> bool:
        if self.path:
            if self.path.exists():
                self.path.unlink()
                return True
            return False
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
            return True
        except PasswordDeleteError:
            return False
