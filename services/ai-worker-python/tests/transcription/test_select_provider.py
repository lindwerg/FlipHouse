"""select_provider factory — cloud-only (GigaAM-v3 is the sole engine)."""

from __future__ import annotations

import pytest

from fliphouse_worker.transcription import (
    CloudTranscriptionProvider,
    select_provider,
)


def test_select_provider_without_transport_raises_not_silent_fallback():
    # GigaAM-v3 is the sole engine: no transport is a wiring bug, NOT a degradation
    # path. It must fail loud (pointing at the GPU ASR lane) instead of returning text.
    with pytest.raises(ValueError, match="GPU_ASR_ENABLED"):
        select_provider(transport=None)


def test_select_provider_with_transport_returns_cloud_provider():
    p = select_provider(transport=lambda ref, lang: {"segments": [], "duration": 0.0})
    assert isinstance(p, CloudTranscriptionProvider)
