"""Unit tests for the pure R2 helpers (stages/r2.py); byte-moving I/O is live-tested."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from fliphouse_worker.stages import r2


def test_build_config_sets_r2_checksum_and_retry_knobs() -> None:
    cfg = r2.build_config()
    assert cfg.request_checksum_calculation == "when_required"
    assert cfg.response_checksum_validation == "when_required"
    assert cfg.signature_version == "s3v4"
    assert cfg.region_name == "auto"
    assert cfg.retries == {"max_attempts": 5, "mode": "adaptive"}
    assert (cfg.connect_timeout, cfg.read_timeout, cfg.max_pool_connections) == (10, 120, 20)


def test_build_transfer_config_uses_equal_64mib_parts() -> None:
    tc = r2.build_transfer_config()
    assert tc.multipart_threshold == r2.MULTIPART_CHUNK_BYTES
    assert tc.multipart_chunksize == r2.MULTIPART_CHUNK_BYTES
    assert tc.max_concurrency == 4
    assert tc.use_threads is True


def test_parse_key_strips_r2_scheme_and_bucket() -> None:
    assert r2.parse_key("r2://fliphouse-media/clips/a.mp4") == "clips/a.mp4"
    assert r2.parse_key("clips/a.mp4") == "clips/a.mp4"
    assert r2.parse_key("r2://bucket-only") == ""


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "GetObject",
    )


def test_is_missing_key_detects_404_and_nosuchkey() -> None:
    assert r2.is_missing_key(_client_error("NoSuchKey", 404)) is True
    assert r2.is_missing_key(_client_error("SomethingElse", 404)) is True  # status path
    assert r2.is_missing_key(_client_error("NoSuchBucket", 200)) is True  # code path


def test_is_missing_key_allows_transient_and_non_client_errors() -> None:
    assert r2.is_missing_key(_client_error("SlowDown", 503)) is False
    assert r2.is_missing_key(ValueError("not a client error")) is False  # no .response


def test_check_part_limit_accepts_max_and_rejects_oversized() -> None:
    r2.check_part_limit(r2.MAX_OBJECT_BYTES)  # exactly at the ceiling: ok
    with pytest.raises(ValueError, match="exceeds R2 multipart limit"):
        r2.check_part_limit(r2.MAX_OBJECT_BYTES + 1)


def _full_env() -> dict[str, str]:
    return {
        "R2_ACCOUNT_ID": "acc123",
        "R2_BUCKET": "fliphouse-media",
        "R2_ACCESS_KEY_ID": "ak",
        "R2_SECRET_ACCESS_KEY": "sk",
    }


def test_from_env_builds_bucket_scoped_client() -> None:
    client = r2.R2Client.from_env(_full_env())
    assert client.bucket == "fliphouse-media"
    assert client._endpoint_url == "https://acc123.r2.cloudflarestorage.com"
    assert client._s3 is None  # lazy — no network at construction


def test_from_env_defaults_to_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in _full_env().items():
        monkeypatch.setenv(name, value)
    client = r2.R2Client.from_env()
    assert client.bucket == "fliphouse-media"


def test_from_env_missing_var_raises_named_error() -> None:
    env = _full_env()
    del env["R2_BUCKET"]
    with pytest.raises(ValueError, match="R2_BUCKET"):
        r2.R2Client.from_env(env)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
