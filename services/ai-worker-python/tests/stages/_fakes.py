"""Shared test doubles for the stage-handler suite (FakeR2 + request builder)."""

from __future__ import annotations

from pathlib import Path


class FakeR2:
    """In-memory stand-in for ``R2Client`` — mirrors download_file/upload_file."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects: dict[str, bytes] = dict(objects or {})  # key → bytes (downloadable)
        self.uploaded: dict[str, bytes] = {}  # key → bytes (what handlers PUT)

    def download_file(self, key: str, dest: str | Path) -> None:
        Path(dest).write_bytes(self.objects[key])

    def upload_file(self, src: str | Path, key: str) -> None:
        self.uploaded[key] = Path(src).read_bytes()

    def object_exists(self, key: str) -> bool:
        # A sentinel written by a prior run lives in `objects` (pre-seeded) or in
        # `uploaded` (written this run); either presence means "already there".
        return key in self.objects or key in self.uploaded


def make_request(
    stage: str,
    *,
    inputs: dict[str, str] | None = None,
    output_prefix: str | None = None,
    params: dict | None = None,
    content_hash: str = "h1",
) -> dict:
    """Build a StageRequest dict matching packages/shared stage-io.ts."""
    return {
        "version": 1,
        "stage": stage,
        "contentHash": content_hash,
        "ownerId": "u1",
        "inputs": inputs or {},
        "outputPrefix": output_prefix or f"{stage}-{content_hash}",
        "params": params or {},
    }
