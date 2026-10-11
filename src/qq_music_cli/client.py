"""HTTP transport for QQ Music's web API.

All RPC calls go to `POST https://u.y.qq.com/cgi-bin/musicu.fcg` as plain JSON with the web `comm`
and the account cookies. The y.qq.com page itself now sends AG-1 encrypted, signed requests to
`u6.y.qq.com/cgi-bin/musics.fcg`, but on 2026-10-11 the plain route still answered reads and writes
for a logged-in session, so this client does not implement AG-1 or signing.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

from .auth import Credential
from .errors import ApiError, AuthError, NetworkError, QQMusicError, RiskControlError

RPC_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"  # unsigned batch endpoint
UTF8 = "utf-8"
SITE = "https://y.qq.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# What y.qq.com puts in `comm` (captured 2026-10-11), minus uin/g_tk which come from the session.
WEB_COMM: dict[str, Any] = {"needNewCode": 1, "notice": 0, "platform": "yqq.json", "cv": 4747474, "ct": 24}
WEB_COMM |= {"format": "json", "inCharset": UTF8, "outCharset": UTF8}
AUTH_CODES = {1000, 104400, 104401}
RISK_CODES = {2001}
SIGN_REQUIRED_CODE = 2000

Call = tuple[str, str, dict[str, Any]]


class Client:
    def __init__(
        self,
        cred: Credential | None = None,
        *,
        timeout: float = 20.0,
        retries: int = 3,
        min_interval: float = 0.25,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.credential = cred
        self.retries = retries
        self.min_interval = min_interval
        self._sleep = sleep
        self._last = 0.0
        self._http = httpx.Client(
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Origin": SITE, "Referer": f"{SITE}/"},
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- plumbing -----------------------------------------------------------------------------

    def comm(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.credential
        token = session.g_tk if session else 5381
        comm = {**WEB_COMM, "uin": session.uin if session else "0"}
        for name in ("g_tk", "g_tk_new_20200303"):
            comm[name] = token
        return comm | (extra or {})

    def _cookie_header(self) -> dict[str, str]:
        if not self.credential:
            return {}
        jar = self.credential.cookie_jar()
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())}

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()

    def _send(self, method: str, url: str, *, idempotent: bool, **kwargs: Any) -> httpx.Response:
        """Send with retries on network errors, 429 and 5xx. Non-idempotent calls are sent once."""
        attempts = self.retries + 1 if idempotent else 1
        headers = {**kwargs.pop("headers", {}), **self._cookie_header()}
        for attempt in range(attempts):
            self._throttle()
            try:
                response = self._http.request(method, url, headers=headers, **kwargs)
            except httpx.TransportError as exc:
                if attempt + 1 < attempts:
                    self._sleep(0.5 * 2**attempt + random.random() * 0.3)
                    continue
                raise NetworkError(f"{type(exc).__name__}: {exc}") from exc
            finally:
                # Never let server Set-Cookie mutate what we send; the credential is the source of truth.
                self._http.cookies.clear()
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < attempts:
                    self._sleep(0.5 * 2**attempt + random.random() * 0.3)
                    continue
                raise NetworkError(f"HTTP {response.status_code} from {url}", code=response.status_code)
            return response
        raise NetworkError(f"no response from {url}")  # pragma: no cover

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        text = response.text.strip()
        if text and not text.startswith("{"):
            # JSONP such as `callback({...})`
            start, end = text.find("("), text.rfind(")")
            if start != -1 and end > start:
                text = text[start + 1 : end]
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ApiError(f"non-JSON response (HTTP {response.status_code}): {text[:200]!r}") from exc
        if not isinstance(data, dict):
            raise ApiError("unexpected JSON shape", data=data)
        return data

    @staticmethod
    def error_for(code: int, module: str | None, method: str | None, data: Any = None) -> QQMusicError:
        where = {"method": method, "module": module}
        if code in AUTH_CODES:
            return AuthError(f"login expired or invalid (code {code}); run `qqmusic login`", code=code, **where)
        if code in RISK_CODES:
            text = "risk control / rate limited (code 2001); slow down, or log in again in a browser"
            return RiskControlError(text, code=code, **where)
        if code == SIGN_REQUIRED_CODE:
            return ApiError("server requires a signed request (code 2000)", code=code, **where)
        server_msg = data.get("msg") if isinstance(data, dict) else None
        return ApiError(server_msg or f"API error code {code}", code=code, data=data, **where)

    # -- RPC ----------------------------------------------------------------------------------

    def rpc_many(
        self,
        calls: Sequence[Call],
        *,
        comm_extra: dict[str, Any] | None = None,
        comm: dict[str, Any] | None = None,
        idempotent: bool = True,
        risk_retries: int = 2,
        skip_failed: bool = False,
    ) -> list[dict[str, Any]]:
        """`comm` replaces the web comm entirely; `comm_extra` is merged into it.

        `skip_failed` turns a plain API error in one slot into `{}` for that slot, so one bad item does
        not sink a batch. Login and risk-control errors still raise.
        """
        payload: dict[str, Any] = {"comm": dict(comm) if comm is not None else self.comm(comm_extra)}
        for i, call in enumerate(calls):
            payload[f"req_{i}"] = dict(zip(("module", "method", "param"), call, strict=True))
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        tries = risk_retries + 1 if idempotent else 1
        for attempt in range(tries):
            response = self._send(
                "POST", RPC_URL, idempotent=idempotent, content=body, headers={"Content-Type": "application/json"}
            )
            try:
                return self._unpack(self._json(response), calls, skip_failed=skip_failed)
            except RiskControlError:
                if attempt + 1 < tries:
                    self._sleep(3 * 3**attempt + random.random())
                    continue
                raise
        raise ApiError("unreachable")  # pragma: no cover

    def rpc(self, module: str, method: str, param: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.rpc_many([(module, method, param or {})], **kwargs)[0]

    def _unpack(
        self, resp: dict[str, Any], calls: Sequence[Call], *, skip_failed: bool = False
    ) -> list[dict[str, Any]]:
        outer = resp.get("code", 0)
        if outer != 0:
            raise self.error_for(int(outer), None, None, resp)
        results: list[dict[str, Any]] = []
        for i, (module, method, _) in enumerate(calls):
            item = resp.get(f"req_{i}")
            if not isinstance(item, dict):
                raise ApiError(f"response has no slot for {module}.{method}", data=resp)
            code = item.get("code", 0)
            if code != 0:
                error = self.error_for(int(code), module, method, item.get("data"))
                if skip_failed and type(error) is ApiError:
                    results.append({})
                    continue
                raise error
            data = item.get("data")
            if data is None:
                data = {}
            if isinstance(data, dict):
                ret = data.get("retCode")
                if ret not in (None, 0):
                    raise self.error_for(int(ret), module, method, data)
            results.append(data)
        return results

    # -- legacy c.y.qq.com endpoints ---------------------------------------------------------

    def get_legacy(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        session = self.credential
        token = session.g_tk if session else 5381
        query = {key: WEB_COMM[key] for key in ("format", "inCharset", "outCharset", "platform", "notice")}
        query.update(needNewCode=0, hostUin=0, loginUin=session.uin if session else 0)
        query.update(g_tk=token, g_tk_new_20200303=token)
        query.update(params)
        data = self._json(self._send("GET", url, idempotent=True, params=query))
        code = data.get("code", 0)
        if code not in (0, None):
            raise self.error_for(int(code), url.rsplit("/", 1)[-1], None, data)
        return data
