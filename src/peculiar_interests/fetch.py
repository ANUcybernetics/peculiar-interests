"""HTTP fetching shared by every source.

aph.gov.au and its Azure API front doors answer plain requests but 403 the
default python-httpx user agent, so every client here presents a browser UA.
Downloads are written atomically and hashed so a re-fetch can be compared with
what is already committed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx
from loguru import logger

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128 Safari/537.36 (+https://github.com/anucybernetics/peculiar-interests)"
)


def client(**headers: str) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, **headers},
        timeout=httpx.Timeout(60.0),
        follow_redirects=True,
    )


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


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
