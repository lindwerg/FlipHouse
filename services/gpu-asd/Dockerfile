# ============================================================================
# DEPLOY VIA MODAL — there is NO standalone `docker build` for this service.
# ============================================================================
#
# The REAL container image for the LR-ASD GPU active-speaker service is defined in
# code, in `modal_app.py` (`gpu_image`): a debian-slim base + CUDA torch, the cloned
# LR-ASD repo (Junhua-Liao/LR-ASD, MIT, bundled weights + S3FD), scenedetect /
# python_speech_features / opencv-headless, ffmpeg, and the `fliphouse_asd` package.
# Modal builds and caches that image on `modal deploy modal_app.py`.
#
# This Dockerfile exists only so the service has the same on-disk shape as the rest
# of the fleet and to document the image contract. It is intentionally a non-building
# placeholder — do NOT `docker build` it.
#
# Image contract (kept in sync with modal_app.py:gpu_image):
#   * Base:        debian-slim + python 3.11, CUDA torch==2.2.2 / torchaudio==2.2.2
#   * System deps: ffmpeg, git, libgl1, libglib2.0-0
#   * LR-ASD:      git clone https://github.com/Junhua-Liao/LR-ASD.git -> /opt/LR-ASD
#                  (weights in-tree: weight/finetuning_TalkSet.model — NO pyannote,
#                   NO gated checkpoints, NO Ultralytics/InsightFace)
#   * Package:     fliphouse_asd (add_local_python_source)
#   * Secret:      GPU_ASD_SECRET (Modal secret `fliphouse-asd`, injected at RUN time)
#   * Entrypoint:  the @modal.asgi_app `web` (synchronous signed /score)
# ----------------------------------------------------------------------------

FROM scratch AS deploy-via-modal-only
# Deploy:    modal deploy modal_app.py
# Self-test: modal run modal_app.py --selftest
