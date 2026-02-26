from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit_per_minute: int) -> None:
        now = time.time()
        window_start = now - 60

        with self._lock:
            entries = self._events[key]
            while entries and entries[0] < window_start:
                entries.popleft()

            if len(entries) >= limit_per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please retry in 1 minute.",
                )

            entries.append(now)


rate_limiter = InMemoryRateLimiter()


def _extract_token(credentials: HTTPAuthorizationCredentials | None, request: Request) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials

    header_token = request.headers.get("x-api-key")
    if header_token:
        return header_token

    return None


def verify_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> str:
    token = _extract_token(credentials, request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")

    for valid in settings.api_key_list:
        if secrets.compare_digest(token, valid):
            rate_key = f"{request.client.host if request.client else 'unknown'}:{valid}"
            rate_limiter.check(rate_key, settings.rate_limit_per_minute)
            return token

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
