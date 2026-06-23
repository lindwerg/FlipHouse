"""Unit tests for the CLI entrypoint `main` — the Docker/boot selftest gate.

`cli/__main__.py` is coverage-omitted (real stdin/stdout I/O), but the
`--selftest` boot gate is load-bearing for the Docker build (`RUN python3 -m
fliphouse_worker.cli --selftest`) and the Node `runPythonSelftest`, so we assert
it returns 0 and does not require the `stage` positional. The bug this guards
against: a required `stage` arg made argparse exit(2) before the selftest
short-circuit, so the image build could never succeed.

The selftest now also runs `assert_startup_codecs` (the libvpx-vp9/libopenh264
boot gate), which probes real ffmpeg — patched out here so the unit test stays
hermetic; the codec assertions are unit-tested in tests/clipping/.
"""

from __future__ import annotations

import pytest

import fliphouse_worker.clipping as clipping
from fliphouse_worker.cli.__main__ import main


def test_selftest_returns_zero_without_a_stage_positional(monkeypatch) -> None:
    monkeypatch.setattr(clipping, "assert_startup_codecs", lambda: None)
    assert main(["--selftest"]) == 0


def test_missing_stage_without_selftest_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
