"""Worker stage CLI entrypoint (impure I/O harness — integration-only).

Invoked by the Node BullMQ worker as ``python -m fliphouse_worker.cli <stage>``:
reads a StageRequest JSON from stdin, runs the stage, and writes exactly one
framed ``@@FLIPHOUSE_RESULT@@<json>`` envelope to stdout. All human/library
output goes to stderr so the framed channel stays clean.

This module is coverage-omitted (real stdin/stdout/process I/O); the pure logic
lives in ``_dispatch`` (100% unit-tested). NOTE: the per-stage handlers (R2
fetch → run render/transcribe/score → R2 upload) are wired in the stages step;
until then the registry is empty and any stage returns UNKNOWN_STAGE.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping

from ._dispatch import StageHandler, dispatch, frame_result


def _build_handlers() -> Mapping[str, StageHandler]:
    """Real R2/ffmpeg-backed stage handlers (env-built R2 client + subprocess seams)."""
    from ..stages import build_handlers

    return build_handlers()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fliphouse-stage")
    # `stage` is optional so `--selftest` (the Docker build / boot gate) can run
    # with no positional. argparse would otherwise exit(2) on the missing arg
    # BEFORE the selftest short-circuit, making the image build always fail.
    parser.add_argument("stage", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)

    if args.selftest:
        # Boot gate: assert ffmpeg has BOTH the finalist (libvpx-vp9/libopus) and
        # delivery (libopenh264/aac) encoders, so a libvpx-less image fails the
        # Docker build / boot here, not silently per finalist clip mid-job.
        from ..clipping import assert_startup_codecs

        assert_startup_codecs()
        print("fliphouse worker selftest ok", file=sys.stderr)
        return 0

    if args.stage is None:
        parser.error("stage is required unless --selftest is given")

    request = json.loads(sys.stdin.read())
    result = dispatch(args.stage, request, _build_handlers())
    print(frame_result(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
