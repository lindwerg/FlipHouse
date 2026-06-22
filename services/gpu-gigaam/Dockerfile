# ============================================================================
# FOUNDER-GATED STUB — DOES NOT BUILD AS-IS. DO NOT `docker build` THIS YET.
# ============================================================================
#
# This is a deliberate skeleton outline of the GPU image for the GigaAM-v3
# transcription service. The CUDA base, the gigaam/pyannote install, the model
# weight bake, and the ASGI runner are all TODOs the founder must finalize once
# the GPU host (RunPod vs Modal) is chosen and the HuggingFace gated-model terms
# are accepted. Each TODO below is a real decision, not boilerplate.
#
# Why it cannot build yet:
#   * The CUDA base tag must match the chosen host's driver/runtime.
#   * `gigaam` + the v3 weights are not on PyPI as a clean wheel; the install
#     path (pip index, git ref, or vendored weights) is founder-gated.
#   * pyannote VAD models are GATED on HuggingFace — the build needs an HF_TOKEN
#     secret (BuildKit secret mount), which is provisioned at deploy time.
# ----------------------------------------------------------------------------

# TODO(founder): pin to the CUDA runtime your GPU host actually provides.
#   RunPod / Modal expose different base images; pick one and pin the digest.
# FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04
FROM scratch AS placeholder-do-not-build

# TODO(founder): system deps. ffmpeg is REQUIRED (audio decode for the model);
#   git is needed if gigaam/pyannote install from a git ref.
# RUN apt-get update \
#   && apt-get install -y --no-install-recommends ffmpeg git python3.11 python3-pip \
#   && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dev/runtime is split: requirements-dev.txt is CI tooling only. The LIVE deps
# (gigaam, pyannote.audio, httpx) come from the `live` extra in pyproject.toml.
# COPY pyproject.toml README.md ./
# COPY fliphouse_gigaam ./fliphouse_gigaam

# TODO(founder): install the live extra. gigaam pulls torch+CUDA — make sure the
#   torch wheel matches the CUDA base above (cu124 index, etc.).
# RUN pip install --no-cache-dir ".[live]"

# TODO(founder): bake the pyannote gated VAD model at build time using an HF token
#   mounted as a BuildKit secret (NEVER an ARG/ENV — that leaks into image layers):
#     docker build --secret id=hf_token,env=HF_TOKEN ...
# RUN --mount=type=secret,id=hf_token \
#     HF_TOKEN="$(cat /run/secrets/hf_token)" python -c "import gigaam; gigaam.load_model('v3_e2e_rnnt')"

# GIGAAM_WEBHOOK_SECRET is injected at RUN time by the host's secret manager,
# never baked into the image. See README.

# TODO(founder): pick an ASGI runner (uvicorn/hypercorn) and expose it. The app
#   factory is fliphouse_gigaam.config:build_app_from_env.
# EXPOSE 8080
# CMD ["python", "-m", "uvicorn", "--factory", "fliphouse_gigaam.config:build_app_from_env", \
#      "--host", "0.0.0.0", "--port", "8080"]
