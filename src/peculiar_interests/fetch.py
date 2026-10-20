"""HTTP fetching shared by every source.

aph.gov.au and its Azure API front doors answer plain requests but 403 the
default python-httpx user agent, so every client here presents a browser UA.
The Senate API also throws the odd transient 500 for a single statement, so
every client retries 5xx responses with backoff before letting one through.
Downloads are written atomically and hashed so a re-fetch can be compared with
what is already committed.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx
from loguru import logger

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128 Safari/537.36 (+https://github.com/anucybernetics/peculiar-interests)"
)


# Seconds to wait before each retry of a 5xx; the last 5xx is returned as is.
RETRY_DELAYS = (2.0, 5.0, 15.0, 30.0)


class RetryTransport(httpx.BaseTransport):
    """Retry 5xx responses from `inner`, sleeping `delays[i]` before retry i."""

    def __init__(
        self,
        inner: httpx.BaseTransport,
        delays: tuple[float, ...] = RETRY_DELAYS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._delays = delays
        self._sleep = sleep

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        for delay in self._delays:
            response = self._inner.handle_request(request)
            if response.status_code < 500:
                return response
            response.close()
            logger.warning(
                "{} from {}; retrying in {:.0f}s",
                response.status_code,
                request.url,
                delay,
            )
            self._sleep(delay)
        return self._inner.handle_request(request)

    def close(self) -> None:
        self._inner.close()


def client(
    transport: httpx.BaseTransport | None = None, **headers: str
) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, **headers},
        timeout=httpx.Timeout(60.0),
        follow_redirects=True,
        transport=RetryTransport(transport or httpx.HTTPTransport()),
    )


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def fetched_at_by_id(
    previous: Mapping[str, str],
    ids: Iterable[str],
    changed: Iterable[str],
    stamp: datetime,
) -> dict[str, str]:
    """Per-statement fetch times for a freshly written index.

    A statement keeps the time recorded in `previous` unless it is new or its
    content changed on this fetch, so `fetched_at` says when our copy was
    actually taken and a night with no changes rewrites nothing.
    """
    changed = set(changed)
    fresh = stamp.isoformat()
    return {i: fresh if i in changed or i not in previous else previous[i] for i in ids}


def download(http: httpx.Client, url: str, dest: Path) -> tuple[str, bool]:
    """Fetch `url` into `dest`, replacing it only if the bytes changed.

    Returns the sha256 of the content and whether `dest` was (re)written.
    """
    response = http.get(url)
    response.raise_for_status()
    body = response.content
    digest = hashlib.sha256(body).hexdigest()
    if dest.exists() and sha256_of(dest) == digest:
        logger.debug("unchanged {}", dest.name)
        return digest, False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(body)
    tmp.replace(dest)
    logger.info("wrote {} ({} bytes)", dest, len(body))
    return digest, True
