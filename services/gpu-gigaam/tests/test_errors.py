"""errors.py — HF/pyannote auth-class classification (TRANS-4)."""

from __future__ import annotations

import pytest

from fliphouse_gigaam.errors import (
    GIGAAM_AUTH_ERROR_PREFIX,
    classify_transcription_error,
    is_hf_auth_error,
)


@pytest.mark.parametrize(
    "message",
    [
        "401 Client Error: Unauthorized for url",
        "403 Forbidden",
        "Access to model pyannote/segmentation-3.0 is restricted",
        "You must accept the terms to use this gated model",
        "HF_TOKEN is invalid",
        "Please use use_auth_token to access this repo",
        "your token is not authorized",
    ],
)
def test_is_hf_auth_error_matches_auth_messages(message):
    assert is_hf_auth_error(RuntimeError(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "CUDA out of memory",
        "ffmpeg failed to decode the input",
        "RuntimeError: tensor shape mismatch",
        "",
    ],
)
def test_is_hf_auth_error_ignores_non_auth_faults(message):
    assert is_hf_auth_error(RuntimeError(message)) is False


def test_classify_tags_auth_error_with_prefix():
    out = classify_transcription_error(RuntimeError("401 Unauthorized: gated model"))
    assert out.startswith(GIGAAM_AUTH_ERROR_PREFIX)
    assert "401" in out


def test_classify_leaves_plain_fault_untagged():
    out = classify_transcription_error(RuntimeError("cuda oom"))
    assert out == "cuda oom"
    assert GIGAAM_AUTH_ERROR_PREFIX not in out
