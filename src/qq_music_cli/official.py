"""Tencent's official QQ Music skill gateway (`https://a.y.qq.com`, API key from y.qq.com/n/ryqq_v2/qqmusic_skills).

It is read-only and covers search, recommendations, charts, playlist detail and listening reports.
Only the listening report and recommendations add something the web API above does not.
Request and response shapes follow tencentmusic/qqmusic-skills v0.0.3. Untested: needs a key.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .errors import ApiError, AuthError, NetworkError

BASE_URL = "https://a.y.qq.com"
SKILL_VERSION = "0.0.3"


def call(path: str, params: dict[str, Any] | None = None, *, timeout: float = 20.0) -> dict[str, Any]:
    key = os.environ.get("QQMUSIC_API_KEY")
    if not key:
        raise AuthError("QQMUSIC_API_KEY is not set; get a key at https://y.qq.com/n/ryqq_v2/qqmusic_skills")
    if not path.startswith("/"):
        path = "/" + path
    try:
        response = httpx.post(
            BASE_URL + path,
            json={"params": params or {}, "comm": {"skill_version": SKILL_VERSION}},
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
    except httpx.TransportError as exc:
        raise NetworkError(f"official API unreachable: {exc}") from exc
    data = response.json()
    for field in ("ret", "sub_ret"):
        if data.get(field) not in (None, 0):
            raise ApiError(data.get("msg") or f"{field}={data[field]}", code=data[field], module=path)
    return data
