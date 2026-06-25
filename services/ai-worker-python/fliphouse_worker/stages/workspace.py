"""Per-job scratch space + R2 input/output marshalling for stage handlers.

All of a job's local files live in ONE ``TemporaryDirectory`` (same filesystem →
``os.replace`` in render is atomic), auto-swept on exit even when the handler
raises. ``download_inputs`` validates the wiring (a required logical input absent
from the request is a fatal ``ValueError``, not a retryable I/O error) and pulls
only what the stage needs; ``upload_outputs`` streams each result to R2 and
returns an ``ArtifactRef`` (key + bytes + streamed sha256) for every output.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .artifacts import artifact_ref, content_key
from .r2 import parse_key


@contextmanager
def job_workspace(req: dict) -> Iterator[Path]:
    """Yield a fresh temp dir for one stage run; removed on exit (even on error)."""
    with tempfile.TemporaryDirectory(prefix=f"fh_{req.get('stage', 'stage')}_") as tmp:
        yield Path(tmp)


def download_inputs(
    r2: object,
    req: dict,
    ws: Path,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> dict[str, Path]:
    """Fetch each REQUIRED (+ present OPTIONAL) logical input into ``ws``.

    Returns ``{logical: local_path}``. A missing REQUIRED input is a wiring bug (fatal
    ``ValueError``), checked before any download. An OPTIONAL input absent from the
    request is silently skipped (its key is simply absent from the returned dict) — used
    by SPD-1's reframe caption fold, where ``word_segments`` is fail-open. The local
    filename keeps the R2 key's suffix so downstream ffmpeg / json readers see a sensible
    extension; logical names are unique so no clash.
    """
    inputs = req.get("inputs", {})
    missing = [name for name in required if name not in inputs]
    if missing:
        raise ValueError(f"stage {req.get('stage')!r} missing required inputs: {missing}")

    paths: dict[str, Path] = {}
    for name in (*required, *optional):
        key = inputs.get(name)
        if key is None:
            continue
        dest = ws / f"{name}{Path(parse_key(key)).suffix}"
        r2.download_file(key, dest)
        paths[name] = dest
    return paths


def upload_outputs(r2: object, output_prefix: str, out_paths: Sequence[Path]) -> list[dict]:
    """Stream each output to R2 under a content-addressed key; return its ArtifactRef."""
    refs: list[dict] = []
    for path in out_paths:
        key = content_key(output_prefix, path.name)
        r2.upload_file(path, key)
        refs.append(artifact_ref(key, path))
    return refs
