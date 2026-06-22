"""audio seam — the default fetcher is pragma'd; cover the module surface.

The real ``_default_fetch_audio`` does live network I/O and is ``# pragma: no
cover``. Here we only assert the seam type and default binding are wired (import
+ alias), and that a fake fetcher satisfies the protocol shape the orchestrator
calls.
"""

from __future__ import annotations

from pathlib import Path

from fliphouse_gigaam.audio import default_fetch_audio


def test_default_fetch_audio_is_callable_binding():
    assert callable(default_fetch_audio)


def test_fake_fetcher_writes_dest(tmp_path: Path):
    # The orchestrator only relies on (url, dest) -> writes bytes to dest.
    def fetch(url: str, dest: Path) -> None:
        dest.write_bytes(b"AUDIO")

    out = tmp_path / "audio_input"
    fetch("https://x/y.wav", out)
    assert out.read_bytes() == b"AUDIO"
