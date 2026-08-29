import time
from typing import Any, Callable, Protocol, TypeVar, runtime_checkable
import requests
from edgedash.config import Config


class SourceError(Exception):
    """Raised when a job source fetch or network call fails."""

    pass


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) EdgeDash/1.0 "
    "(Autonomous Career Intelligence Agent; +https://github.com/edgedash)"
)


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 10,
    max_retries: int = 2,
) -> dict[str, Any]:
    req_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        req_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, headers=req_headers, timeout=timeout)
            response.raise_for_status()
            return response.json()  # type: ignore[no-any-return]
        except (requests.RequestException, ValueError) as err:
            last_error = err
            if attempt < max_retries:
                time.sleep(1 * (2**attempt))

    raise SourceError(f"HTTP request failed for {url} after {max_retries + 1} attempts: {last_error}")


@runtime_checkable
class Source(Protocol):
    name: str

    def fetch(self, config: Config) -> list[dict[str, Any]]:
        ...


SOURCES: dict[str, type[Source]] = {}

S = TypeVar("S", bound=type[Source])


def register(name_or_cls: str | S | None = None) -> Callable[[S], S] | S:
    def _decorator(cls: S) -> S:
        key = (
            name_or_cls
            if isinstance(name_or_cls, str)
            else getattr(cls, "name", cls.__name__.lower())
        )
        SOURCES[key] = cls
        return cls

    if isinstance(name_or_cls, type):
        cls = name_or_cls
        key = getattr(cls, "name", cls.__name__.lower())
        SOURCES[key] = cls
        return cls

    return _decorator
