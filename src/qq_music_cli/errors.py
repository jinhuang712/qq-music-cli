"""Error types. Each maps to a stable `kind` and process exit code so agents can branch on them."""

from __future__ import annotations

from typing import Any


class QQMusicError(Exception):
    kind = "error"
    exit_code = 1

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        module: str | None = None,
        method: str | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.module = module
        self.method = method
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "message": self.message}
        for key in ("code", "module", "method"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


class ApiError(QQMusicError):
    kind = "api"
    exit_code = 1


class UsageError(QQMusicError):
    kind = "usage"
    exit_code = 2


class AuthError(QQMusicError):
    kind = "auth"
    exit_code = 3


class RiskControlError(QQMusicError):
    kind = "risk_control"
    exit_code = 4


class NetworkError(QQMusicError):
    kind = "network"
    exit_code = 5
