"""Live R2 round-trip — opt-in, hits real Cloudflare R2.

Skipped unless ``FLIPHOUSE_LIVE_R2=1`` and the R2_* credentials are set. Verifies
the two things unit tests can't: that botocore's checksum knobs don't make R2
reject the request (the boto3≥1.36 fix), and that an upload→download round-trips
byte-identically. Run manually:

    FLIPHOUSE_LIVE_R2=1 R2_ACCOUNT_ID=… R2_BUCKET=… \
    R2_ACCESS_KEY_ID=… R2_SECRET_ACCESS_KEY=… pytest -m live tests/stages/test_r2_live.py
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import pytest

from fliphouse_worker.stages.artifacts import sha256_file
from fliphouse_worker.stages.r2 import R2Client

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FLIPHOUSE_LIVE_R2") != "1",
        reason="set FLIPHOUSE_LIVE_R2=1 + R2_* creds to run the live R2 round-trip",
    ),
]


def test_botocore_meets_checksum_floor() -> None:
    import botocore

    major, minor = (int(p) for p in botocore.__version__.split(".")[:2])
    assert (major, minor) >= (1, 36), "R2 needs botocore≥1.36 checksum knobs"


def test_r2_upload_download_round_trips(tmp_path: Path) -> None:
    client = R2Client.from_env()
    key = f"_selftest/{uuid.uuid4().hex}.bin"
    payload = b"fliphouse-r2-live-" + os.urandom(64)

    src = tmp_path / "up.bin"
    src.write_bytes(payload)
    client.upload_file(src, key)  # must not raise a checksum 400

    dest = tmp_path / "down.bin"
    client.download_file(key, dest)
    assert dest.read_bytes() == payload
    assert sha256_file(dest) == hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-m", "live"]))
