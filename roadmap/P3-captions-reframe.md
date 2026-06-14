# P3 — Субтитры + speaker-tracking reframe (captacity + LR-ASD)

> Фаза «сделать клип вирусным на вид»: карооке-субтитры (captacity) поверх контента + точный 9:16-реврейм по активному спикеру (LR-ASD на GPU-провайдере Modal, submit-and-park через webhook). Safe-zone субтитров примиряется с зарезервированной баннер-полосой **сейчас**, чтобы Phase 4 (ad-insertion) встал без перепланировки.
>
> Источники-доки: `docs/01-АРХИТЕКТУРА-И-RAILWAY.md` (§2 контракты стадий, §3 GPU-стратегия, §6 FFmpeg-рантайм) и `docs/03-ОФФЕРЫ-И-ВСТАВКА-РЕКЛАМЫ.md` (§3.1 clip_meta / caption_safe / speaker_box, safe-zone-инвариант).

---

## Цель фазы (Phase goal)

Дать конвейеру две новые CPU-CPU/GPU-стадии и единый source-of-truth safe-zones:

1. **`reframe` (CPU-оркестратор + Modal-GPU)** — `source.mp4` → LR-ASD на Modal → `asd_frames.json` → детерминированный reframe-planner → `crop_keyframes.json` → FFmpeg-crop → `1080×1920.mp4`. Лицо активного спикера держится **выше `banner.y`**.
2. **`caption` (CPU)** — пропатченный captacity жжёт karaoke-субтитры **строго внутри `caption_band`** и **никогда** в баннер-полосе.
3. **`safe_zones.json`** — единый контракт зон, CI-инвариант `caption_band ⊂ content_safe` и `caption_band ∩ banner = ∅` (`1180+420=1600 ≤ 1640`).

Definition of Done фазы: на фикстуре-клипе end-to-end рендер выдаёт `1080×1920` mp4 с burnt-in субтитрами в content-зоне, нулём пикселей субтитров в баннер-полосе, и crop-кейфреймами, выведенными из реального ASD-скоринга. Все тесты зелёные, покрытие ≥ 80% по новым модулям.

## Зависимости (что должно быть готово)

- **P0** — Railway-каркас: проект, `staging`/`production`, Postgres, Redis, R2-доступ, LGPL FFmpeg-образ (doc 01 §6). Фаза P3 переиспользует FFmpeg-образ и `cpu-worker`.
- **P1** — клиппинг-движок MVP: `ai-render-worker`/`cpu-worker` с BullMQ, `word_segments.json` от ASR (faster-whisper / fal Wizper), per-clip 9:16 cut. P3 — стадии `reframe`/`caption`, которые встают **между** `score` и `store` как параллельные сиблинги (doc 01 §5 Flow-DAG).
- **P2** — бан­нер-оверлей (`ad_banner.py`) уже зарезервировал banner-полосу; P3 **примиряет** caption safe-zone с этой полосой (но сам баннер не рендерит).
- **webhook-receiver** сервис (HMAC-verify, doc 01 §3) — поднят в P0/P1 как приёмник GPU-колбэков; P3 добавляет в него ASD-маршрут.

## Репозитории, клонируемые/используемые в этой фазе

```bash
# captacity — karaoke caption burn-in (MIT). Lift + patch.
git clone https://github.com/unconv/captacity vendor/captacity

# LR-ASD — точный Active Speaker Detection (CUDA). Wrap, не форкать.
git clone https://github.com/Junhua-Liao/LR-ASD vendor/lr-asd
```

Дополнительно (через пакет-менеджеры, не клон):

```bash
# Python worker deps (в pyproject воркера)
pip install moviepy==2.* opencv-python-headless numpy pytest pytest-cov pillow ffmpeg-python pydantic jsonschema
# Modal SDK для submit-and-park GPU ASD
pip install modal
# TS webhook-receiver
pnpm add ajv zod   # валидация ASD-колбэка
```

Из `vendor/captacity` поднимаем **только** файлы:
- `captacity/segment_parser.py` → `worker/captions/segment_parser.py`
- `captacity/text_drawer.py` → `worker/captions/text_drawer.py`

(`captacity/__init__.py` и CLI-обёртку **не** тащим — у нас свой orchestration-слой и свой safe-zone-aware placement вместо хардкода `text_y_offset = video.h//2`.)

Из `vendor/lr-asd` запускаем как есть `Columbia_test.py` внутри Modal-контейнера (выдаёт `tracks.pckl` + `scores.pckl`); наш тонкий post-processor конвертит их в `asd_frames.json`.

## Чек-пойнты фазы

- 🛑 **ЧЕКПОИНТ A** (после Шага 3.2): `safe_zones.json` + CI-инвариант — геометрия зон, которую увидит и Phase 4.
- 🛑 **ЧЕКПОИНТ B** (после Шага 3.5): пропатченный captacity жжёт субтитры в content-зоне; golden-frame доказывает «ноль пикселей в баннер-полосе».
- 🛑 **ЧЕКПОИНТ C** (после Шага 3.8): ASD output-contract — `scores.pckl` → `asd_frames.json` → `crop_keyframes.json`, EMA + min-hold.
- 🛑 **ЧЕКПОИНТ D** (после Шага 3.11): Modal submit-and-park + webhook-receiver маршрут ASD, идемпотентный.
- 🛑 **ЧЕКПОИНТ E** (после Шага 3.13): end-to-end рендер на фикстуре — `1080×1920` + субтитры + crop из реального ASD.

---

## Шаг 3.0 — Скелет worker-модуля и фикстуры

- **Цель / DoD:** создан пакет `worker/` (Python) с под-пакетами `captions/`, `reframe/`, `safezones/`, тест-харнесс pytest + coverage-гейт 80%, и крошечный детерминированный видео-фикстур-набор. `pytest` зелёный на пустом скелете.
- **Репозитории/команды:**
  ```bash
  mkdir -p worker/{captions,reframe,safezones} worker/tests/fixtures
  # детерминированный 3-сек тест-клип 1280x720, 25fps, синус-тон, цветные полосы + 1 «лицо»-патч
  ffmpeg -f lavfi -i testsrc2=size=1280x720:rate=25:duration=3 \
         -f lavfi -i sine=frequency=440:duration=3 \
         -vf "drawbox=x=520:y=180:w=240:h=300:color=white:t=fill" \
         -c:v libopenh264 -pix_fmt yuv420p -c:a aac -shortest \
         worker/tests/fixtures/source_3s.mp4
  ```
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_smoke.py::test_fixture_exists_and_is_25fps` — `ffprobe` на `source_3s.mp4` ассертит `avg_frame_rate == "25/1"`, `width==1280`, `height==720`, `nb_frames>=74`.
  - `tests/test_smoke.py::test_package_imports` — импорт `worker.captions`, `worker.reframe`, `worker.safezones` без ошибок.
- **Реализация:** `pyproject.toml` (pytest, pytest-cov, `--cov-fail-under=80`), `worker/__init__.py` + пустые `__init__.py` в под-пакетах, `conftest.py` с фикстурой `fixture_clip` → путь к `source_3s.mp4`.
- **✅ Готово когда:** оба теста зелёные; `pytest --cov=worker` показывает гейт активным (на скелете 100%).
- **Commit:** `chore(worker): скелет caption/reframe пакета + детерминированная видео-фикстура`

---

## Шаг 3.1 — Контракт safe-zones: pydantic-модели + JSON Schema

- **Цель / DoD:** формализован `safe_zones.json` как pydantic-модель + JSON Schema. Поля выведены из doc 01 §2 и doc 03 §3.1: `canvas{w,h,fps}`, `content_safe`, `caption_band`, `banner` (зарезервированная полоса). Все боксы в OUT-координатах 1080×1920.
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_safezones_schema.py::test_valid_safezones_parses` — валидный объект (`canvas 1080x1920@30`, `content_safe {0,0,1080,1640}`, `caption_band {60,1180,960,420}`, `banner {0,1640,1080,280}`) парсится в модель.
  - `tests/test_safezones_schema.py::test_negative_box_rejected` — бокс с `w<0` → `ValidationError`.
  - `tests/test_safezones_schema.py::test_box_out_of_canvas_rejected` — `caption_band.y+h > canvas.h` → `ValidationError`.
- **Реализация:** `worker/safezones/models.py` — `Box(x,y,w,h)` (clamp-валидаторы, `x+w<=canvas.w`), `SafeZones(canvas, content_safe, caption_band, banner)`. `worker/safezones/schema.json` (Draft 2020-12) сгенерирована из модели. Дефолт-конструктор `default_9x16()` отдаёт каноничную геометрию.
- **✅ Готово когда:** 3 теста зелёные; `schema.json` коммитится как build-артефакт модели (тест `test_schema_matches_model` сверяет).
- **Commit:** `feat(safezones): pydantic-контракт safe_zones.json + JSON Schema`

---

## Шаг 3.2 — CI-инвариант safe-zones (`caption_band ⊂ content_safe`, `∩ banner = ∅`)

- **Цель / DoD:** чистая функция-валидатор инварианта из doc 01 §2, плюс property-тест на каноничную геометрию `1180+420=1600 ≤ 1640`. Это «контракт, который Phase 4 наследует».
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_safezone_invariant.py::test_caption_band_subset_of_content_safe` — `assert_invariant(default_9x16())` не кидает.
  - `tests/test_safezone_invariant.py::test_caption_band_disjoint_from_banner` — `caption_band` (`y..y+h = 1180..1600`) не пересекает `banner` (`y=1640`) → ок.
  - `tests/test_safezone_invariant.py::test_overlap_with_banner_raises` — искусственный `caption_band.h=500` (→1680, заходит в banner@1640) → `SafeZoneViolation`.
  - `tests/test_safezone_invariant.py::test_caption_band_outside_content_safe_raises` — `caption_band` шире `content_safe` → `SafeZoneViolation`.
  - `tests/test_safezone_invariant.py::test_canonical_numbers` — явный ассерт `1180+420 == 1600 and 1600 <= 1640`.
- **Реализация:** `worker/safezones/invariant.py` — `assert_invariant(sz: SafeZones)`: проверяет subset (AABB containment) и disjoint (AABB separation) → кидает `SafeZoneViolation(reason)`. Экспорт `check_invariant() -> list[str]` для CI (возвращает список нарушений, пусто = ок).
- **✅ Готово когда:** 5 тестов зелёные; добавлен `scripts/check_safezones.py` (exit 1 при нарушении) — повесить в CI как gate.
- 🛑 **ЧЕКПОИНТ A:** *Фаундер ревьюит геометрию зон.* Здесь фиксируются числа `content_safe`/`caption_band`/`banner`, которые увидят и P3-субтитры, и P4-баннер. Можно подвинуть полосы (например, под другой UI-bleed TikTok) до того, как они «забетонируются» в golden-тестах ниже. **Изменение здесь дешёвое, после Шага 3.5 — дорогое.**
- **Commit:** `feat(safezones): CI-инвариант caption_band ⊂ content_safe ∧ ∩banner=∅`

---

## Шаг 3.3 — Lift captacity: `segment_parser.py` + `text_drawer.py`

- **Цель / DoD:** файлы captacity перенесены в `worker/captions/`, привязаны к нашему moviepy v2, и покрыты unit-тестами на парсинг word-сегментов. **Ничего ещё не патчим** — фиксируем исходное поведение характеризующими тестами, чтобы патч safe-zone не сломал парсинг незаметно.
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/unconv/captacity vendor/captacity
  cp vendor/captacity/captacity/segment_parser.py worker/captions/segment_parser.py
  cp vendor/captacity/captacity/text_drawer.py     worker/captions/text_drawer.py
  ```
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_segment_parser.py::test_parse_segments_splits_on_max_chars` — вход `word_segments` (каждое слово с `start/end`, **ведущий пробел** — требование captacity, doc 01 §2) → группы ≤ `max_caption_size`.
  - `tests/test_segment_parser.py::test_leading_space_preserved` — сегменты сохраняют ведущий пробел у каждого word (иначе слова слипнутся при burn-in).
  - `tests/test_text_drawer.py::test_create_text_returns_image_with_alpha` — `create_text(...)` возвращает RGBA-картинку с непустым bbox текста.
  - `tests/test_text_drawer.py::test_text_color_and_highlight` — highlight-цвет применяется к «активному» слову (karaoke), базовый — к остальным.
- **Реализация:** перенесённые файлы + тонкий adapter `worker/captions/word_segments.py` — pydantic-модель `WordSegment(start,end,words:[{word,start,end}])`, конвертер из `word_segments.json` (ASR-выход P1) в формат, который ждёт `segment_parser`. Зафиксировать версию moviepy в pyproject.
- **✅ Готово когда:** 4 теста зелёные; покрытие новых файлов ≥ 80%.
- **Commit:** `feat(captions): lift captacity segment_parser + text_drawer под moviepy v2`

---

## Шаг 3.4 — Патч captacity: safe-zone-aware placement (убрать `text_y_offset = video.h//2`)

- **Цель / DoD:** заменён хардкод вертикальной позиции субтитров на placement, выводимый из `caption_band` (doc 01 §2: «`position` kwarg — no-op TODO; хардкод `text_y_offset = video.h//2` надо заменить на safe-zone-aware placement»). Субтитры центруются внутри `caption_band`, **никогда** не вылезая за `content_safe` и **никогда** не заходя в `banner`.
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_caption_placement.py::test_caption_y_within_caption_band` — для `default_9x16()` вычисленный `y` текстового блока (с учётом высоты блока) лежит в `[caption_band.y, caption_band.y+caption_band.h]`.
  - `tests/test_caption_placement.py::test_caption_never_enters_banner` — `y + block_h <= banner.y` для блока любой допустимой высоты (1–3 строки).
  - `tests/test_caption_placement.py::test_position_kwarg_respected` — `position="caption_band"` ставит блок в полосу; неизвестный enum → `ValueError` (no silent fallback).
  - `tests/test_caption_placement.py::test_block_too_tall_shrinks_font` — если 3-строчный блок не влезает в `caption_band` при базовом кегле, функция уменьшает кегль, а не выходит за полосу.
- **Реализация:** `worker/captions/placement.py` — `place_caption_block(sz: SafeZones, n_lines, line_h) -> CaptionPlacement(x,y,max_w,font_px)`. Патч в `worker/captions/render.py` (наша обёртка вокруг captacity): вместо `video.h//2` вызываем `place_caption_block(...)`; `position` — enum `{caption_band}` (расширяемо), whitelisted. Кегль ужимается, пока блок не влезет.
- **✅ Готово когда:** 4 теста зелёные; coverage ≥ 80%; ручной чек: лог печатает вычисленный `y` и подтверждает `< banner.y`.
- **Commit:** `fix(captions): safe-zone-aware placement вместо хардкода text_y_offset=h/2`

---

## Шаг 3.5 — Golden-frame тест: субтитры в content-зоне, ноль пикселей в баннер-полосе

- **Цель / DoD:** настоящий burn-in одного субтитра на 1080×1920-канвас и **pixel-region ассерты**: внутри `caption_band` есть непрозрачный текст; внутри `banner`-полосы (y∈[1640,1920)) — **ноль** caption-пикселей. Плюс frame-hash для регресс-защиты.
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_caption_golden.py::test_caption_pixels_present_in_caption_band` — рендер кадра, кроп региона `caption_band`, ассерт `nonzero_alpha_pixels > THRESHOLD` (текст реально нарисован).
  - `tests/test_caption_golden.py::test_zero_caption_pixels_in_banner_strip` — кроп `banner`-региона, ассерт `nonzero_alpha_pixels == 0` (по caption-слою до композита; **жёсткий инвариант фазы**).
  - `tests/test_caption_golden.py::test_caption_pixels_within_content_safe` — все непрозрачные caption-пиксели лежат в `content_safe` (bbox-containment).
  - `tests/test_caption_golden.py::test_frame_hash_stable` — perceptual hash (`imagehash.phash`) субтитр-слоя совпадает с golden ± hamming ≤ 4 (детерминизм рендера).
- **Реализация:** `worker/captions/render.py::render_caption_layer(text, sz, t_active_word) -> RGBA np.array (1920,1080,4)` — рисует один karaoke-кадр на прозрачном канвасе через `text_drawer` + `placement`. Тест-утилита `tests/golden/_regions.py` (кроп по `Box`). Golden-png + golden-hash в `tests/golden/`.
- **✅ Готово когда:** 4 теста зелёные; golden-артефакты закоммичены; ручной чек: открыть `tests/golden/caption_layer.png` — текст визуально в нижней трети, баннер-полоса пустая.
- 🛑 **ЧЕКПОИНТ B:** *Фаундер ревьюит, как выглядят субтитры и доказательство «ноль пикселей в баннере».* Здесь можно поменять шрифт/кегль/highlight-цвет (бренд-шрифт FlipHouse, doc 01 §6) до того, как golden-hash зафиксируется. Если меняем — обновляем golden и hash в этом же шаге.
- **Commit:** `test(captions): golden-frame — субтитры в content-зоне, ноль пикселей в баннер-полосе`

---

## Шаг 3.6 — ASD output-contract: `scores.pckl` + `tracks.pckl` → `asd_frames.json`

- **Цель / DoD:** post-processor, конвертящий сырой выход LR-ASD (`tracks.pckl`, `scores.pckl`) в `asd_frames.json` строго по контракту doc 01 §2: `{fps:25, frame_w, frame_h, frames:[{frame,t,faces:[{bbox,score}]}]}`, где **score = signed logit, порог 0 (НЕ probability)**.
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/Junhua-Liao/LR-ASD vendor/lr-asd  # если ещё не склонирован
  ```
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_asd_contract.py::test_scores_are_signed_logits_not_probabilities` — синтетические `scores.pckl` со значениями `[-3.2, 0.0, 4.1]` пробрасываются как есть (не sigmoid'ятся); ассерт диапазон выходит за `[0,1]`.
  - `tests/test_asd_contract.py::test_active_speaker_is_score_gt_zero` — `is_speaking == (score > 0)` (порог 0).
  - `tests/test_asd_contract.py::test_frame_units_at_25fps` — `t == frame / 25.0`; число кадров совпадает с `tracks.pckl`.
  - `tests/test_asd_contract.py::test_bbox_in_pixel_coords` — bbox каждого лица в пиксельных координатах исходника, clamp в `[0, frame_w/h]`.
  - `tests/test_asd_contract.py::test_output_validates_against_schema` — `asd_frames.json` валиден против `worker/reframe/asd_schema.json`.
- **Реализация:** `worker/reframe/asd_postprocess.py::asd_to_frames(tracks_path, scores_path, fps=25) -> dict`. `worker/reframe/asd_schema.json` (Draft 2020-12). Фикстура `tests/fixtures/asd/{tracks,scores}.pckl` — крошечный синтетический набор (2 трека, 10 кадров), сгенерированный скриптом `tests/fixtures/asd/_gen.py` (детерминированно).
- **✅ Готово когда:** 5 тестов зелёные; coverage ≥ 80%; ручной чек: `asd_frames.json` человекочитаем, score-знаки сохранены.
- **Commit:** `feat(reframe): ASD post-processor scores.pckl → asd_frames.json (signed logits, порог 0)`

---

## Шаг 3.7 — Reframe-planner: `asd_frames.json` → `crop_keyframes.json` (EMA + min-hold 12)

- **Цель / DoD:** детерминированный планнер, выбирающий активного спикера по кадрам и строящий crop-кейфреймы для 9:16 с **EMA-сглаживанием + min-hold 12 кадров** (анти-whip-pan, doc 01 §2). Crop держит лицо спикера **выше `banner.y`** (doc 01 §2: «Reframe обязан держать лицо спикера выше `banner.y`»).
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_reframe_planner.py::test_picks_highest_scoring_face_per_frame` — на кадре с двумя лицами выбирается то, у кого `score` больше (и >0).
  - `tests/test_reframe_planner.py::test_min_hold_12_frames_no_whip_pan` — два соседних speaker-свитча в пределах <12 кадров → planner НЕ переключает crop (держит предыдущий ≥12 кадров).
  - `tests/test_reframe_planner.py::test_ema_smoothing_monotonic` — резкий скачок bbox → выходной crop.x меняется плавно (|Δ| ≤ ema_cap на кадр).
  - `tests/test_reframe_planner.py::test_speaker_kept_above_banner_y` — для каждого кейфрейма центр лица проецируется в OUT-координаты так, что `face_center_y_out < banner.y` (1640).
  - `tests/test_reframe_planner.py::test_crop_is_9x16_and_within_source` — каждый crop имеет аспект 9:16 и лежит внутри `frame_w×frame_h`.
  - `tests/test_reframe_planner.py::test_no_active_speaker_falls_back_to_center` — кадры без `score>0` → центрированный crop (blur-pad general path, doc 01 §1).
- **Реализация:** `worker/reframe/planner.py::plan_crops(asd: dict, sz: SafeZones) -> dict` (`crop_keyframes.json`). Константы: `MIN_HOLD_FRAMES = 12`, `EMA_ALPHA`, `EMA_MAX_STEP_PX`. Чистая функция (нет I/O/RNG/часов — диффабельно/кешируемо, как rules-engine в doc 03 §3).
- **✅ Готово когда:** 6 тестов зелёные; coverage ≥ 80%; ручной чек: `crop_keyframes.json` диффится стабильно на повторном прогоне.
- **Commit:** `feat(reframe): детерминированный planner asd→crop_keyframes (EMA + min-hold 12, лицо выше banner.y)`

---

## Шаг 3.8 — FFmpeg crop-executor: `crop_keyframes.json` → 1080×1920.mp4

- **Цель / DoD:** исполнитель, превращающий crop-кейфреймы в реальный реврейм-видеофайл через FFmpeg (LGPL-образ из P0/doc 01 §6). Output-ассерты на **dimensions + длительность + frame-hash**, не «команда отработала».
- **Тесты СНАЧАЛА (pytest, e2e-render на фикстуре):**
  - `tests/test_reframe_render.py::test_output_is_1080x1920` — `ffprobe` выхода → `width==1080`, `height==1920`.
  - `tests/test_reframe_render.py::test_output_duration_matches_source` — длительность выхода ≈ длительности `source_3s.mp4` (±1 кадр).
  - `tests/test_reframe_render.py::test_codec_is_h264_lgpl` — `codec_name=="h264"` (через libopenh264, не x264 — doc 01 §6).
  - `tests/test_reframe_render.py::test_center_crop_frame_hash` — на синтетическом «центрированном спикере» извлечённый кадр совпадает с golden-hash (crop попал куда планнер сказал).
  - `tests/test_reframe_render.py::test_filtergraph_via_script_not_shell` — graph пишется в файл и подаётся `-filter_complex_script` (анти-injection, doc 01 §6 / doc 03 §3.7).
- **Реализация:** `worker/reframe/render.py::render_reframe(src, crop_keyframes, out)` — генерит filtergraph (`crop` с покадровыми `x/y` через `sendcmd`/zoompan или per-segment `crop`), пишет в `*.filtergraph` файл, вызывает FFmpeg argv-списком (никогда не shell-строкой). Параметры энкода из doc 01 §6: `-c:v libopenh264 -g 48 -threads 2 -movflags +faststart`.
- **✅ Готово когда:** 5 тестов зелёные; ручной чек: выход открывается, спикер в кадре, аспект 9:16.
- 🛑 **ЧЕКПОИНТ C:** *Фаундер ревьюит полную ASD→crop→video цепочку.* Здесь видно качество трекинга на фикстуре: можно подкрутить `EMA_ALPHA`/`MIN_HOLD_FRAMES`/clearance до лица. Output-контракт (`asd_frames.json` → `crop_keyframes.json` → 1080×1920) зафиксирован.
- **Commit:** `feat(reframe): FFmpeg crop-executor crop_keyframes → 1080x1920 (libopenh264, filtergraph-script)`

---

## Шаг 3.9 — Modal-контейнер для LR-ASD (GPU, bring-your-own-container)

- **Цель / DoD:** Modal-функция, оборачивающая `vendor/lr-asd/Columbia_test.py` (CUDA-required, doc 01 §3) — принимает presigned R2-URL исходника, гоняет ASD, грузит `tracks.pckl`+`scores.pckl` обратно в R2 `intermediate/{jobId}/`. **На Railway GPU нет** — это исполняется на Modal. Локально тестируем через mock-режим (без GPU).
- **Репозитории/команды:**
  ```bash
  pip install modal
  # vendor/lr-asd уже склонирован (Шаг 3.6)
  ```
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_modal_asd.py::test_handler_builds_correct_command` — собранная команда запуска ссылается на `Columbia_test.py` с правильными путями video/out (проверяем argv, не запускаем GPU).
  - `tests/test_modal_asd.py::test_handler_uploads_both_pickles` — mock R2-клиент: хендлер грузит ровно `tracks.pckl` и `scores.pckl` в `intermediate/{jobId}/`.
  - `tests/test_modal_asd.py::test_handler_idempotent_on_existing_output` — если оба pickle уже в R2 → хендлер не пере-гоняет ASD (skip).
  - `tests/test_modal_asd.py::test_invalid_input_url_rejected` — не-https / не-R2 URL → reject до запуска.
- **Реализация:** `infra/modal/asd_app.py` — `@app.function(gpu="T4", image=lr_asd_image)` `run_asd(job_id, src_url)`; `lr_asd_image` ставит CUDA-deps + копирует `vendor/lr-asd`. R2 I/O вынесен в `worker/reframe/r2_io.py` (мокаемый). Команда — argv-список.
- **✅ Готово когда:** 4 теста зелёные (без реального GPU); `modal run infra/modal/asd_app.py` деплоится в staging Modal-workspace (ручной smoke на одном клипе вне CI).
- **Commit:** `feat(infra): Modal-контейнер LR-ASD (CUDA), tracks/scores.pckl → R2`

---

## Шаг 3.10 — gpu-score-worker: submit-and-park к Modal (никогда не блокировать BullMQ)

- **Цель / DoD:** BullMQ-воркер очереди `gpu-score`, который **отправляет** ASD-джобу на Modal и **паркуется** (doc 01 §3/§5): сохраняет `provider_request_id → bullmq_jobId` в Redis, переходит в `waiting-on-callback`, **не ждёт GPU синхронно**. `concurrency:1` + `setGlobalConcurrency(2)` (GPU-клапан, doc 01 §5).
- **Тесты СНАЧАЛА (Vitest, TS-воркер):**
  - `tests/gpu-score.test.ts > submits to Modal and parks without blocking` — мок Modal-клиента: воркер вызывает submit, сохраняет mapping в Redis, **возвращает управление** (не await на результат GPU).
  - `tests/gpu-score.test.ts > persists provider_request_id → jobId in Redis` — после submit в Redis есть ключ `asd:req:{providerId}` со значением `jobId`.
  - `tests/gpu-score.test.ts > respects setGlobalConcurrency(2)` — при 3 одновременных джобах ≤2 уходят в submit, 3-я ждёт (global cap).
  - `tests/gpu-score.test.ts > concurrency 1 per worker` — конфиг воркера `concurrency===1`.
- **Реализация:** `services/gpu-score-worker/index.ts` — BullMQ `Worker('gpu-score', processor, {concurrency:1})`, `Queue.setGlobalConcurrency(2)`; processor: presign R2 → `modal.run_asd.spawn(...)` → `redis.set('asd:req:'+reqId, jobId)` → `await job.moveToWaitingChildren()`/park-паттерн. Мок Modal через DI.
- **✅ Готово когда:** 4 теста зелёные; coverage ≥ 80%; ручной чек: лог показывает submit+park без блокировки.
- **Commit:** `feat(gpu-score): submit-and-park ASD к Modal (concurrency:1 + global:2, без блокировки)`

---

## Шаг 3.11 — webhook-receiver: маршрут ASD-колбэка (HMAC-verify, идемпотентность)

- **Цель / DoD:** в существующем `webhook-receiver` (doc 01 §3, HMAC-verify) — маршрут `POST /webhooks/asd`, который принимает Modal-колбэк, **верифицирует подпись ДО мутации**, валидирует payload, находит джобу по `provider_request_id` и продвигает state-machine (ставит `score`-child как completed → flow идёт дальше к `reframe`).
- **Тесты СНАЧАЛА (Vitest):**
  - `tests/webhook-asd.test.ts > rejects bad HMAC before any state mutation` — невалидная подпись → 401, Redis/PG не тронуты.
  - `tests/webhook-asd.test.ts > idempotent on duplicate provider_request_id` — два одинаковых колбэка → джоба продвигается один раз (дедуп по reqId, вендоры ретраят — doc 01 §3).
  - `tests/webhook-asd.test.ts > invalid asd payload rejected` — payload не по `asd_callback` схеме → 422, state не двигается.
  - `tests/webhook-asd.test.ts > resolves jobId from provider_request_id and advances flow` — валидный колбэк → находит `jobId` в Redis → помечает `score`-стадию done.
- **Реализация:** `services/webhook-receiver/routes/asd.ts` — verify HMAC (timing-safe), zod/ajv-валидация payload (`{provider_request_id, status, tracks_url, scores_url}`), `redis.get('asd:req:'+reqId)` → если уже обработан (флаг `asd:done:'+reqId`) → 200 no-op; иначе продвигаем flow и ставим флаг. **Верификация подписи строго до мутации.**
- **✅ Готово когда:** 4 теста зелёные; coverage ≥ 80%.
- 🛑 **ЧЕКПОИНТ D:** *Фаундер ревьюит submit-and-park контур целиком.* Modal ↔ Redis-mapping ↔ webhook ↔ flow. Можно сменить GPU-провайдера на fallback (Replicate `luma/reframe-video`, doc 01 §3) или поменять HMAC-секрет-источник. Идемпотентность и «никогда не блокировать воркер» подтверждены.
- **Commit:** `feat(webhook): ASD-колбэк маршрут (HMAC-verify до мутации, идемпотентный по request_id)`

---

## Шаг 3.12 — Стадия `caption` в Flow-DAG + интеграция с `word_segments.json`

- **Цель / DoD:** `caption`-стадия как BullMQ-сиблинг в `cpu`-очереди (doc 01 §5 Flow-DAG: `[banner, caption, reframe]` параллельны после `score`). Воркер берёт `reframed.mp4` + `word_segments.json` + `safe_zones.json`, жжёт субтитры пропатченным captacity, грузит результат в R2. Порядок наложения соблюдён: `reframe → banner → captions` (doc 01 §2).
- **Тесты СНАЧАЛА (pytest integration):**
  - `tests/test_caption_stage.py::test_burns_captions_onto_reframed_clip` — на `reframed 1080x1920` фикстуре + синтетических `word_segments` → выход содержит непрозрачные текст-пиксели в `caption_band`.
  - `tests/test_caption_stage.py::test_requires_leading_space_in_words` — `word_segments` без ведущих пробелов → стадия нормализует их (captacity-требование) или фейлит явно.
  - `tests/test_caption_stage.py::test_caption_after_banner_order` — стадия читает уже-баннеренный клип, если баннер был (проверяем, что subs поверх, не под).
  - `tests/test_caption_stage.py::test_output_uploaded_to_r2_clips_prefix` — mock R2: результат лёг в `clips/{clipId}/`.
- **Реализация:** `worker/captions/stage.py::run_caption_stage(job)` — загрузка входов из R2, `render.py` burn-in через FFmpeg (`-filter_complex_script`, `ass`/overlay caption-слоя), upload. `services/cpu-worker` регистрирует processor очереди `cpu` на тип `caption`.
- **✅ Готово когда:** 4 теста зелёные; coverage ≥ 80%.
- **Commit:** `feat(caption): стадия caption в Flow-DAG (burn-in поверх reframe, порядок reframe→banner→captions)`

---

## Шаг 3.13 — End-to-end render-тест на фикстуре: 1080×1920 + субтитры присутствуют

- **Цель / DoD:** один e2e-тест, прогоняющий **всю P3-цепочку** на фикстуре (ASD-выход замокан pickle-фикстурой Шага 3.6, GPU не нужен): `source → (mock ASD) asd_frames → crop_keyframes → reframe 1080×1920 → caption burn-in` и ассертящий финал: **`1080×1920` + субтитры в content-зоне + ноль пикселей в баннер-полосе + crop выведен из ASD-скоринга**.
- **Тесты СНАЧАЛА (pytest e2e):**
  - `tests/test_e2e_pipeline.py::test_final_is_1080x1920_h264` — `ffprobe` финала → `1080×1920`, `h264`.
  - `tests/test_e2e_pipeline.py::test_captions_present_in_content_area` — извлечённый кадр (на `t` активного слова): непрозрачные caption-пиксели есть в `caption_band`.
  - `tests/test_e2e_pipeline.py::test_zero_caption_pixels_in_banner_strip` — на финальном composite в `banner`-полосе ноль caption-пикселей (инвариант фазы сквозь весь пайплайн).
  - `tests/test_e2e_pipeline.py::test_crop_derived_from_asd_scores` — изменив фикстуру `scores.pckl` (спикер слева → справа), финальный crop-центр сдвигается соответственно (реврейм реально слушает ASD).
  - `tests/test_e2e_pipeline.py::test_pipeline_deterministic_frame_hash` — повторный прогон даёт тот же perceptual-hash финального кадра.
- **Реализация:** `worker/pipeline.py::run_p3(src, word_segments, asd_pickles, sz) -> final_path` — последовательный вызов всех модулей P3, без сети (ASD из фикстуры). Тест-утилиты переиспользуют `tests/golden/_regions.py`.
- **✅ Готово когда:** 5 тестов зелёные; coverage по всему `worker/` ≥ 80%; ручной чек: открыть финальный mp4 — вертикальный клип, спикер в кадре, karaoke-субтитры внизу, баннер-полоса чистая.
- 🛑 **ЧЕКПОИНТ E:** *Фаундер смотрит готовый «вирусный» клип на фикстуре.* Финальная визуальная приёмка P3: реврейм + субтитры + примирённая safe-zone. Если что-то выглядит не так (трекинг дёргается, субтитры мелкие) — крутим параметры из ЧЕКПОИНТов B/C; иначе фаза закрыта и P4 (баннер в `banner`-полосу) встаёт без перепланировки.
- **Commit:** `test(pipeline): e2e P3-рендер на фикстуре — 1080x1920 + субтитры + crop из ASD`

---

## Шаг 3.14 — CI-гейт фазы: инвариант safe-zones + golden-набор + coverage

- **Цель / DoD:** CI запускает (а) `scripts/check_safezones.py` (exit 1 при нарушении инварианта), (б) весь pytest-набор P3 с `--cov-fail-under=80`, (в) golden-frame регресс. Фаза не мерджится, если инвариант или golden сломан.
- **Тесты СНАЧАЛА:** мета-тест `tests/test_ci_gate.py::test_safezone_script_exits_nonzero_on_violation` — подсовываем битую геометрию, ассертим exit-code 1; `::test_ci_gate_runs_full_suite` — smoke, что pytest-конфиг подхватывает все P3-тесты.
- **Реализация:** `.github/workflows/p3-render.yml` (или Railway CI-эквивалент) — джоб: build LGPL-FFmpeg-образ (кэш из P0) → `pytest worker/ --cov=worker --cov-fail-under=80` → `python scripts/check_safezones.py`. Golden-png в репо, hamming-порог в тестах.
- **✅ Готово когда:** оба мета-теста зелёные; CI-джоб проходит на чистом клоне; намеренная порча golden/инварианта роняет CI (проверено локально).
- **Commit:** `ci(p3): гейт safe-zone-инварианта + golden-frame + coverage 80%`

---

## Выход фазы (Phase exit criteria)

- [ ] `safe_zones.json`-контракт + CI-инвариант `caption_band ⊂ content_safe ∧ caption_band ∩ banner = ∅` (`1180+420=1600 ≤ 1640`) — зелёный, заблокирован для P4 (ЧЕКПОИНТ A).
- [ ] captacity пропатчен: хардкод `text_y_offset = video.h//2` заменён на safe-zone-aware placement; `position` — whitelisted enum, не no-op.
- [ ] Golden-frame доказывает: субтитры присутствуют в `caption_band` и **ноль** caption-пикселей в `banner`-полосе (ЧЕКПОИНТ B).
- [ ] ASD output-contract: `scores.pckl`+`tracks.pckl` → `asd_frames.json` (signed logits, порог 0, 25fps) → `crop_keyframes.json` (EMA + min-hold 12, лицо выше `banner.y`) (ЧЕКПОИНТ C).
- [ ] LR-ASD исполняется на Modal (GPU), Railway остаётся CPU-only; gpu-score-worker делает submit-and-park (`concurrency:1` + `global:2`), webhook-receiver принимает колбэк с HMAC-verify до мутации и идемпотентностью (ЧЕКПОИНТ D).
- [ ] FFmpeg-реврейм через `-filter_complex_script` (анти-injection), `libopenh264` (LGPL), выход строго `1080×1920`.
- [ ] `caption`-стадия встроена в Flow-DAG как сиблинг, порядок наложения `reframe → banner → captions` соблюдён.
- [ ] End-to-end рендер на фикстуре: `1080×1920` + субтитры в content-зоне + crop, выведенный из реального ASD-скоринга, детерминированный frame-hash (ЧЕКПОИНТ E).
- [ ] Покрытие новых модулей `worker/` ≥ 80%; CI-гейт (инвариант + golden + coverage) зелёный и роняется при намеренной порче.
- [ ] Каждый шаг закоммичен отдельно, TDD-цикл (RED→GREEN→refactor) соблюдён, ни один шаг не «готов» без зелёных тестов.
