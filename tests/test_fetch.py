from datetime import UTC, datetime

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
