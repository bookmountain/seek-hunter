import random
import time
from collections.abc import Callable
from typing import Any


class SourceBlocked(Exception):
    """Raised when a source keeps answering 403/429 after backoff."""


class PoliteClient:
    def __init__(
        self,
        session: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        min_delay: float = 2.0,
        max_delay: float = 5.0,
        backoffs: tuple[float, ...] = (30.0, 90.0),
    ) -> None:
        if session is None:
            from curl_cffi import requests as cffi_requests

            session = cffi_requests.Session(impersonate="chrome")
        self.session = session
        self.sleep = sleep
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.backoffs = backoffs
        self.request_count = 0
        self.blocked_count = 0

    def get(self, url: str, **kw: Any) -> Any:
        return self._request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> Any:
        return self._request("POST", url, **kw)

    def _request(self, method: str, url: str, **kw: Any) -> Any:
        if self.request_count > 0:
            self.sleep(random.uniform(self.min_delay, self.max_delay))
        self.request_count += 1
        for attempt in range(len(self.backoffs) + 1):
            resp = self.session.request(method, url, timeout=30, **kw)
            if resp.status_code not in (403, 429):
                return resp
            self.blocked_count += 1
            if attempt < len(self.backoffs):
                self.sleep(self.backoffs[attempt])
        raise SourceBlocked(f"{method} {url} blocked ({resp.status_code})")
