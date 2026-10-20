from datetime import UTC, datetime

import httpx

from peculiar_interests import fetch


def test_fetched_at_by_id_keeps_unchanged_and_stamps_changed_or_new() -> None:
    previous = {"A": "2026-01-01T00:00:00+00:00", "B": "2026-01-02T00:00:00+00:00"}
    stamp = datetime(2026, 3, 1, tzinfo=UTC)

    result = fetch.fetched_at_by_id(
        previous, ["A", "B", "C"], changed=["B"], stamp=stamp
    )

    assert result == {
        "A": "2026-01-01T00:00:00+00:00",
        "B": "2026-03-01T00:00:00+00:00",
        "C": "2026-03-01T00:00:00+00:00",
    }


def test_fetched_at_by_id_drops_ids_no_longer_in_index() -> None:
    previous = {"GONE": "2026-01-01T00:00:00+00:00"}
    result = fetch.fetched_at_by_id(
        previous, ["A"], changed=[], stamp=datetime(2026, 3, 1, tzinfo=UTC)
    )
    assert list(result) == ["A"]


def _flaky(statuses: list[int]) -> tuple[httpx.MockTransport, list[int]]:
    """A transport answering with `statuses` in turn, recording each call."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses[len(calls)]
        calls.append(status)
        return httpx.Response(status, json={"ok": status == 200})

    return httpx.MockTransport(handler), calls


def test_retry_recovers_from_transient_5xx() -> None:
    inner, calls = _flaky([500, 503, 200])
    slept: list[float] = []
    transport = fetch.RetryTransport(inner, delays=(1.0, 2.0, 3.0), sleep=slept.append)
    with httpx.Client(transport=transport) as http:
        response = http.get("https://example.test/statement")
    assert response.json() == {"ok": True}
    assert calls == [500, 503, 200]
    assert slept == [1.0, 2.0]


def test_retry_gives_up_and_returns_the_last_5xx() -> None:
    inner, calls = _flaky([500, 500, 500])
    slept: list[float] = []
    transport = fetch.RetryTransport(inner, delays=(1.0, 2.0), sleep=slept.append)
    with httpx.Client(transport=transport) as http:
        response = http.get("https://example.test/statement")
    assert response.status_code == 500
    assert len(calls) == 3
    assert slept == [1.0, 2.0]


def test_retry_passes_4xx_straight_through() -> None:
    inner, calls = _flaky([404])
    transport = fetch.RetryTransport(inner, sleep=lambda _: None)
    with httpx.Client(transport=transport) as http:
        assert http.get("https://example.test/statement").status_code == 404
    assert calls == [404]
