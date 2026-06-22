"""Cloudflare R2 client seam — the ONE network boundary a stage handler touches.

Everything testable (Config building, key parsing, error classification, env
wiring) is a pure module function; only the three methods that actually move bytes
(``_client`` / ``download_file`` / ``upload_file``) are ``# pragma: no cover`` and
exercised by the live-gated suite.

R2 is S3-compatible with sharp edges, all handled here:
- botocore ≥ 1.36 rejects R2 unless the checksum knobs are ``when_required``.
- R2 has no ``GetObjectAttributes``; integrity comes from our streamed SHA-256.
- Multipart parts must be ≥ 5 MiB and ≤ 10 000 per object → 64 MiB chunks, with a
  pre-flight size guard so an over-limit object fails fast (fatal), not mid-upload.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

_MiB = 1 << 20
MULTIPART_CHUNK_BYTES = 64 * _MiB  # == threshold; R2 needs equal parts ≥ 5 MiB
MAX_MULTIPART_PARTS = 10_000  # S3/R2 hard limit
MAX_OBJECT_BYTES = MAX_MULTIPART_PARTS * MULTIPART_CHUNK_BYTES  # ≈ 640 GiB ceiling

# Error codes / HTTP status that mean "the object isn't there" → fatal, not retry.
_MISSING_CODES = frozenset({"NoSuchKey", "NoSuchBucket", "NotFound", "404"})


def build_config() -> Config:
    """botocore Config tuned for R2 (checksum knobs + adaptive retries + timeouts)."""
    return Config(
        signature_version="s3v4",
        region_name="auto",  # R2 ignores region but requires a literal value
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
        retries={"max_attempts": 5, "mode": "adaptive"},
        connect_timeout=10,
        read_timeout=120,
        max_pool_connections=20,
    )


def build_transfer_config() -> TransferConfig:
    """Multipart transfer tuning: 64 MiB equal parts, bounded concurrency."""
    return TransferConfig(
        multipart_threshold=MULTIPART_CHUNK_BYTES,
        multipart_chunksize=MULTIPART_CHUNK_BYTES,
        max_concurrency=4,
        use_threads=True,
    )


def parse_key(key: str) -> str:
    """Strip a defensive ``r2://bucket/`` prefix, returning the bare object key."""
    if key.startswith("r2://"):
        _, _, path = key[len("r2://") :].partition("/")
        return path
    return key


def is_missing_key(exc: BaseException) -> bool:
    """True if a botocore error means the object/bucket is absent (404 / NoSuchKey)."""
    response = getattr(exc, "response", None) or {}
    code = response.get("Error", {}).get("Code")
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in _MISSING_CODES or status == 404


def check_part_limit(size_bytes: int) -> None:
    """Raise if an object would exceed R2's 10 000-part multipart ceiling."""
    if size_bytes > MAX_OBJECT_BYTES:
        raise ValueError(f"object {size_bytes} bytes exceeds R2 multipart limit {MAX_OBJECT_BYTES}")


def _require_env(env: Mapping[str, str], name: str) -> str:
    """Return a required env var or raise a clear ValueError (→ fatal misconfig)."""
    value = env.get(name)
    if not value:
        raise ValueError(f"missing required R2 env var: {name}")
    return value


class R2Client:
    """A bucket-scoped R2 client. The boto3 client is built lazily on first use."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._s3 = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> R2Client:
        """Build from ``R2_ACCOUNT_ID``/``R2_BUCKET``/``R2_ACCESS_KEY_ID``/``R2_SECRET_ACCESS_KEY``."""
        env = os.environ if env is None else env
        account_id = _require_env(env, "R2_ACCOUNT_ID")
        return cls(
            bucket=_require_env(env, "R2_BUCKET"),
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            access_key_id=_require_env(env, "R2_ACCESS_KEY_ID"),
            secret_access_key=_require_env(env, "R2_SECRET_ACCESS_KEY"),
        )

    @property
    def bucket(self) -> str:
        return self._bucket

    def _client(self):  # pragma: no cover - constructs the real boto3 client
        if self._s3 is None:
            import boto3

            self._s3 = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
                config=build_config(),
            )
        return self._s3

    def download_file(self, key: str, dest: str | Path) -> None:  # pragma: no cover - live R2 I/O
        """Stream an object to ``dest``. A missing object is FATAL (ValueError)."""
        try:
            self._client().download_file(self._bucket, parse_key(key), str(dest))
        except ClientError as exc:
            if is_missing_key(exc):
                raise ValueError(f"R2 object not found: {key}") from exc
            raise

    def upload_file(self, src: str | Path, key: str) -> None:  # pragma: no cover - live R2 I/O
        """Stream ``src`` to R2 under ``key`` (multipart for large files)."""
        path = Path(src)
        check_part_limit(path.stat().st_size)
        self._client().upload_file(
            str(path), self._bucket, parse_key(key), Config=build_transfer_config()
        )

    def object_exists(self, key: str) -> bool:  # pragma: no cover - live R2 I/O
        """True if ``key`` exists (HEAD). A missing object is a clean False, not an error.

        Used by the asr-finalize idempotency guard: a present ``_COMPLETE`` sentinel
        means the work is already durable and the step short-circuits.
        """
        try:
            self._client().head_object(Bucket=self._bucket, Key=parse_key(key))
            return True
        except ClientError as exc:
            if is_missing_key(exc):
                return False
            raise
