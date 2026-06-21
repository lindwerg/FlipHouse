"""Pure artifact helpers shared by every stage handler.

No network, no subprocess — just deterministic key derivation and a streamed
content hash. Kept boto3-free so the cheap helpers import without the SDK.

The SHA-256 is streamed (never ``f.read()``) so hashing a multi-GB delivery clip
does not buffer it in RAM, and it is returned in every ``ArtifactRef`` so the
Node side can persist integrity without R2's ``GetObjectAttributes`` (which R2
does not implement) — the multipart ETag is MD5-of-part-MD5s, not a usable hash.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_HASH_CHUNK = 1 << 20  # 1 MiB — stream the file, never read it whole


def sha256_file(path: str | Path) -> str:
    """Return the hex SHA-256 of a file, read in 1 MiB chunks (constant memory)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_key(output_prefix: str, name: str) -> str:
    """Join a stage's content-addressed ``outputPrefix`` with an artifact name.

    ``outputPrefix`` is already ``${stage}-${contentHash}`` on the Node side, so a
    retried/duplicate compute writes the same key — R2 PUT is last-writer-wins
    idempotent and two workers race byte-identical bytes harmlessly.
    """
    return f"{output_prefix.rstrip('/')}/{name}"


def artifact_ref(key: str, path: str | Path) -> dict:
    """Build the ``ArtifactRef`` dict for an uploaded file: key + bytes + sha256.

    Always returns all three fields (the wire contract marks bytes/sha256 optional,
    but the Node sentinel/clips row wants them on every output).
    """
    file_path = Path(path)
    return {
        "key": key,
        "bytes": file_path.stat().st_size,
        "sha256": sha256_file(file_path),
    }
