"""In-memory status store transitions + serialization."""

from __future__ import annotations

from fliphouse_gigaam.status_store import InMemoryStatusStore, StatusRecord


def test_unknown_request_is_none():
    assert InMemoryStatusStore().get("missing") is None


def test_processing_then_succeeded():
    store = InMemoryStatusStore()
    store.mark_processing("r1")
    assert store.get("r1").status == "processing"
    store.mark_succeeded("r1")
    assert store.get("r1").to_dict() == {"request_id": "r1", "status": "succeeded"}


def test_failed_carries_error():
    store = InMemoryStatusStore()
    store.mark_failed("r1", "boom")
    record = store.get("r1")
    assert record.status == "failed"
    assert record.to_dict() == {"request_id": "r1", "status": "failed", "error": "boom"}


def test_record_without_error_omits_field():
    assert StatusRecord("r1", "processing").to_dict() == {
        "request_id": "r1",
        "status": "processing",
    }
