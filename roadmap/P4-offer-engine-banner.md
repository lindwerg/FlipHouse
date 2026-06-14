# P4 — Движок офферов + вставка баннера (ТЗ рекла → FFmpeg)

> **Фаза 4 = дифференциатор.** Это шов A+B+C, которым владеет FlipHouse (см. `docs/03` §6, `docs/00` §4). Здесь рекламодатель сдаёт машиночитаемое ТЗ (JSON Schema Draft 2020-12 + 5-шаговая форма), детерминированный rules-engine `plan(offer, clip_meta) → PlacementPlan` решает **куда/когда/поверх чего** ставить баннер, кодоген превращает план в инъекционно-устойчивый FFmpeg `overlay`-граф (+ MoviePy-фолбэк), а fail-closed brand-safety гейт решает, eligible ли клип под оффер вообще.
>
> Референс — `docs/03-ОФФЕРЫ-И-ВСТАВКА-РЕКЛАМЫ.md` целиком. Вспомогательно: `docs/01` §2 (контракт стадий, safe-zones), §6 (FFmpeg-рантайм, filtergraph-injection), `docs/00` §2 (стек), `docs/02` §4 (oklch-токены для формы), `docs/04` §2 (OpenRouter-адаптер — НЕ трогаем здесь, движок чисто детерминированный).

---

## Цель фазы (Phase goal)

Поставить **детерминированное, без I/O, без часов, без RNG** ядро вставки оффера:

1. **Offer Schema + валидатор** (`@fliphouse/offer-schema`) — JSON Schema из `docs/03` §1.1 + строгий валидатор (Ajv 2020) с осмысленными ошибками.
2. **Advertiser intake form** (5-шаговый визард в `web`) — каждое поле мапится на JSON-путь схемы (`docs/03` §2), сериализуется прямо в валидный оффер, `submit → status:in_review`.
3. **Brand-safety гейт** (Python, `ai-render-worker`) — один скан на клип, **fail-closed**: NSFW/violence (eligibility), face/region map (ограничение размещения → `speaker_box`), ASR→profanity/toxicity (eligibility). Unsafe clip → `not eligible`.
4. **Offer-rules engine** (Python) — чистая функция `plan(offer, clip_meta) → PlacementPlan`: `sanitize → chooseWindows → solveSpatial → PlacementPlan` (`docs/03` §3). Коллизии: баннер НИКОГДА не поверх `caption_safe` и активного `speaker_box`; частотные/интервальные правила; инфизибельный баннер → `dropped[]` с причиной (а не наложение на лицо).
5. **FFmpeg codegen** — `PlacementPlan → plan.filtergraph` (`overlay` + `enable='between(t,a,b)'` + `eval=frame` + fade-alpha), инъекционно-устойчивый (`-filter_complex_script FILE`, argv-входы, clamp/whitelist), + MoviePy v2 фолбэк теми же числами.
6. **Render-assertion** — реальный рендер тестового клипа доказывает: баннерные пиксели появляются в запланированных x/y и только во временном окне.

**Инвариант детерминизма (CI-проверяемый):** одинаковый `(offer, clip_meta, engine_version)` → байт-в-байт одинаковый `PlacementPlan` и одинаковый `filtergraph`. `input_hash` = ключ кеша рендера.

---

## Зависимости (что должно быть готово до P4)

- **P0 — Каркас/инфра.** Монорепо (`web` Next.js + `ai-render-worker` Python), Railway prod+staging, Postgres, Redis, CI (Vitest + pytest gate). Нужен dev-able монорепо и работающий CI-pipeline с coverage-гейтом.
- **P1 — Клиппинг-движок MVP.** `ai-render-worker` существует, FFmpeg-рантайм собран (LGPL, `libopenh264`, `--enable-libfreetype`/`libass` — `docs/01` §6). Реврейм отдаёт 1080×1920 + `crop_keyframes.json`/`safe_zones.json` (контракт `clip_meta`, `docs/01` §2). Движок P4 потребляет **уже реврейменный** клип и его per-frame боксы — границу не нарушаем (`docs/03` §3.1).
- **P2 — Banner-overlay прототип.** `hooks.py:add_hook_to_video` / `ad_banner.py` как стартовый референс ffmpeg `overlay`. P4 заменяет наивный прототип на план-движок + кодоген.
- **Soft-dep:** P3 (native in-frame inpainting) и P5 (CPM-атрибуция) НЕ требуются. P4 — это `overlay`-вставка баннера, не diffusion-inpainting. CPM-механика (`docs/03` §5) — отдельная фаза.

> Если P0–P2 ещё не дали `clip_meta`-фикстуры — Шаг 4.1 создаёт **golden-фикстуры вручную** (синтетический `clip_meta.json` + 1080×1920 тестовый mp4 через ffmpeg `testsrc`), чтобы движок тестировался изолированно от реального ASD-плеча.

---

## Репозитории и инструменты, заводимые в этой фазе

Лицензии не ограничивают (берём лучшее). Всё — в `/vendor` (вендорим), либо как npm/pip-зависимости.

**npm / web (TypeScript, Vitest + Playwright):**
```bash
# Валидатор JSON Schema 2020-12 + форматы (uuid/uri/date-time)
pnpm --filter @fliphouse/offer-schema add ajv ajv-formats
# Конвертация oklch для color-picker формы (брендовые цвета)
pnpm --filter web add culori
# Форма: визард-стейт + валидация на клиенте (схема как single source of truth)
pnpm --filter web add react-hook-form @hookform/resolvers
# (тесты — Vitest/Playwright уже из P0; добавляем @ajv-validator типы при нужде)
```

**pip / ai-render-worker (Python, pytest):**
```bash
# Brand-safety: NSFW-гейт (Apache-2.0, license-clean) — docs/03 §4
pip install transformers torch pillow          # Falconsai/nsfw_image_detection (HF ViT)
# ASR word-level + VAD (docs/03 §4)
pip install faster-whisper                      # SYSTRAN/faster-whisper (MIT)
pip install silero-vad                          # snakers4/silero-vad (MIT)
# Toxicity / profanity (docs/03 §4)
pip install detoxify                            # unitaryai/detoxify (Apache-2.0)
pip install better-profanity                    # snguyenthanh/better_profanity (MIT)
# Face/region для размещения (Apache-2.0) — YuNet через opencv-zoo
pip install opencv-python                       # cv2.FaceDetectorYN (YuNet)
# MoviePy v2 фолбэк кодоген
pip install "moviepy>=2.0"                      # docs/03 §3.7
# Тесты рендера: попиксельная проверка кадров
pip install numpy imageio imageio-ffmpeg
```

**Вендоринг моделей/весов и LDNOOBW-листа (file-lift):**
```bash
# Face detector — YuNet ONNX из opencv_zoo (Apache-2.0)
git clone --depth 1 https://github.com/opencv/opencv_zoo.git vendor/opencv_zoo
# берём ТОЛЬКО: vendor/opencv_zoo/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
#   → ai-render-worker/models/yunet.onnx

# Профанити-листы (leetspeak / мультиязычные стоп-слова) — CC-BY-4.0
git clone --depth 1 https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words.git vendor/ldnoobw
# берём ТОЛЬКО: vendor/ldnoobw/{en,ru}  → ai-render-worker/brand_safety/wordlists/

# Banner-overlay референс ffmpeg (MIT) — для сверки графа, не копируем verbatim
git clone --depth 1 https://github.com/mutonby/openshorts.git vendor/openshorts
# смотрим ТОЛЬКО: vendor/openshorts/hooks.py:add_hook_to_video (L171) — паттерн overlay+between
```

> NSFW-веса `Falconsai/nsfw_image_detection` тянутся `transformers` из HF при первом запуске; в CI мокаем классификатор (детерминизм + скорость), реальные веса — в smoke-тесте за маркером `@pytest.mark.heavy`.

---

## Где что живёт (структура файлов)

```
packages/offer-schema/                      # @fliphouse/offer-schema (TS, переиспользуется web + воркером через JSON)
├── src/
│   ├── advertiser-offer.v1.json            # схема из docs/03 §1.1 verbatim
│   ├── validate.ts                         # Ajv 2020 + ajv-formats, compile + типизированный результат
│   ├── errors.ts                           # маппинг Ajv errors → человекочитаемые поля
│   └── index.ts
├── test/
│   ├── valid-offers.test.ts
│   ├── invalid-offers.test.ts
│   └── fixtures/{nitrogg.valid.json, ...}
└── vitest.config.ts

apps/web/src/
├── app/(advertiser)/offers/new/page.tsx    # 5-шаговый визард
├── components/advertiser/
│   ├── OfferWizard.tsx                      # owner стейта (RHF), маппинг шаг→JSON-блок
│   ├── steps/{StepBrand,StepAssets,StepPlacementTiming,StepCtaMessage,StepSafetyPayoutTargeting}.tsx
│   ├── PlacementPicker.tsx                  # 9:16 пикер слотов + safe/forbidden rect-редактор
│   └── offer.css
├── lib/offers/
│   ├── serializeWizard.ts                   # form-state → offer JSON (валидный против схемы)
│   ├── oklch.ts                             # color-picker ↔ oklch() (culori), AA-контраст подсказка
│   └── submitOffer.ts                       # server action: validate → status:in_review → DB
└── ...
apps/web/e2e/advertiser-offer.spec.ts        # Playwright: пройти визард → валидный оффер

services/ai-render-worker/
├── offer_engine/
│   ├── contracts.py                         # dataclass: Offer, ClipMeta, Frame, Box, PlacementPlan (frozen)
│   ├── sanitize.py                          # §3.2 fail-fast на границе
│   ├── windows.py                           # §3.3 chooseWindows (частота/интервалы)
│   ├── spatial.py                           # §3.4 solveSpatial (AABB collision avoidance)
│   ├── animation.py                         # §3.5 offset-функции (slide_up/fade/pop)
│   ├── plan.py                              # §3.6 plan(offer, clip_meta) -> PlacementPlan + input_hash
│   ├── codegen_ffmpeg.py                    # §3.7 PlacementPlan -> filtergraph (script-only)
│   └── codegen_moviepy.py                   # §3.7 MoviePy v2 фолбэк
├── brand_safety/
│   ├── sampler.py                           # §4.1 кадры 1fps + scene-cut keyframes
│   ├── nsfw.py                              # §4.2 Falconsai ViT гейт
│   ├── violence.py                          # §4.2 violence/gore (CLIP/ViT score)
│   ├── faces.py                             # §4.3 YuNet -> per-frame no-banner боксы (= speaker_box)
│   ├── audio_toxicity.py                    # §4.4 VAD->ASR->detoxify/better_profanity
│   ├── gate.py                              # §4.5 fail-closed решение APPROVE/REVIEW/REJECT
│   └── wordlists/{en,ru}
├── tests/
│   ├── test_sanitize.py  test_windows.py  test_spatial.py  test_animation.py
│   ├── test_plan_determinism.py  test_codegen_ffmpeg.py  test_codegen_moviepy.py
│   ├── test_injection.py  test_brand_safety_gate.py  test_render_assertion.py
│   ├── golden/{placement_plan_clip0007.json, plan_0007.filtergraph}
│   └── fixtures/{clip0007.meta.json, testclip_1080x1920.mp4, banner_cta.png}
└── pyproject.toml
```

---

## Чекпоинты этой фазы

- 🛑 **ЧЕКПОИНТ A** (после 4.2) — схема оффера + валидатор: founder ревьюит контракт ТЗ (поля, enum'ы, `if/then`-правила payout/timing) — последний шанс поменять контракт до того, как форма и движок на него завяжутся.
- 🛑 **ЧЕКПОИНТ B** (после 4.4) — advertiser intake form: founder проходит визард, проверяет маппинг полей и качество сериализации в JSON.
- 🛑 **ЧЕКПОИНТ C** (после 4.7) — brand-safety гейт: founder проверяет fail-closed-поведение на edge-клипах (NSFW, мат, лицо в кадре).
- 🛑 **ЧЕКПОИНТ D** (после 4.11) — rules-engine `PlacementPlan`: founder ревьюит детерминированный план на golden-клипе (коллизии, частота, dropped).
- 🛑 **ЧЕКПОИНТ E** (после 4.14) — FFmpeg-вставка end-to-end: founder смотрит реально отрендеренный клип — баннер в нужном месте/времени, не на лице, не на субтитрах.

---

## Принципы исполнения (для каждого шага)

- **TDD обязателен (правило основателя №1 — ZERO bugs).** Каждый шаг: (1) пишем падающие тесты с точными именами + что ассертят → (2) RED → (3) минимальная реализация → (4) GREEN → (5) рефактор → (6) commit. Шаг не «готов», пока тесты не зелёные И coverage-гейт держится.
- **Coverage-гейт:** offer_engine + brand_safety/gate → **≥95%** (это ядро, founder требует zero-bug); web-форма/serialize → **≥85%**; всё остальное → **≥80%**.
- **Один шаг = один атомарный коммит.** Conventional commits.
- Движок — **чистая функция**: запрещены `time`/`random`/`datetime.now`/сеть внутри `offer_engine/` (CI-проверка: `grep`/`flake8`-правило в Шаге 4.8).

---

## Шаг 4.0 — Каркас пакета схемы и Python-движка (леса под TDD)

- **Цель / DoD:** Поднять `packages/offer-schema` (TS, Vitest) и `services/ai-render-worker/offer_engine` + `brand_safety` (Python, pytest) как пустые, но собирающиеся модули с зелёным «smoke»-тестом и подключённым coverage-гейтом в CI. Никакой бизнес-логики.
- **Репозитории/команды:**
  ```bash
  pnpm --filter @fliphouse/offer-schema add ajv ajv-formats
  pnpm --filter web add culori react-hook-form @hookform/resolvers
  # python deps в pyproject воркера:
  #   faster-whisper silero-vad detoxify better-profanity opencv-python
  #   transformers torch pillow moviepy>=2.0 numpy imageio imageio-ffmpeg pytest pytest-cov
  ```
- **Тесты СНАЧАЛА (Vitest + pytest):**
  - `packages/offer-schema/test/smoke.test.ts` → `test('package exports validateOffer fn')` — ассертит `typeof validateOffer === 'function'`.
  - `tests/test_smoke.py` → `test_offer_engine_importable()` ассертит `import offer_engine` и `import brand_safety` без ошибок.
- **Реализация:** заглушки `index.ts` (`export function validateOffer(){throw new Error('todo')}`), пустые `__init__.py`. CI: добавить `vitest run --coverage` для пакета и `pytest --cov=offer_engine --cov=brand_safety --cov-fail-under=80` для воркера (порог поднимем позже пер-модуль).
- **✅ Готово когда:** оба smoke-теста зелёные; CI запускает обе тест-сюиты; coverage-репорт генерится.
- **Commit:** `chore(p4): scaffold offer-schema package and python engine modules`

---

## Шаг 4.1 — Golden-фикстуры: clip_meta + тестовый 1080×1920 клип + RGBA-баннер

- **Цель / DoD:** Детерминированные фикстуры, на которых тестируется весь движок изолированно от реального ASD-плеча: синтетический `clip0007.meta.json` (контракт `docs/03` §3.1 — `crop`/`caption_safe`/`speaker_box` в OUT-координатах), реальный `testclip_1080x1920.mp4` (ffmpeg `testsrc`, 12с, 30fps, с аудио-дорожкой), `banner_cta.png` RGBA 420×120.
- **Репозитории/команды:**
  ```bash
  # тестовый клип: цветные полосы, чтобы пиксель-дифф был детерминированным
  ffmpeg -f lavfi -i testsrc=size=1080x1920:rate=30:duration=12 \
         -f lavfi -i sine=frequency=440:duration=12 \
         -c:v libopenh264 -pix_fmt yuv420p -c:a aac \
         services/ai-render-worker/tests/fixtures/testclip_1080x1920.mp4
  # баннер: сплошной непрозрачный прямоугольник на прозрачном фоне (известный RGBA-паттерн)
  ffmpeg -f lavfi -i color=c=magenta:s=420x120:d=1 -frames:v 1 \
         -vf "format=rgba" services/ai-render-worker/tests/fixtures/banner_cta.png
  ```
- **Тесты СНАЧАЛА (pytest):**
  - `tests/test_fixtures.py::test_clip_meta_matches_contract` — загружает `clip0007.meta.json`, ассертит ключи `clip_id,duration_s,fps,out_w,out_h,frames`, `frames[0].t==0`, монотонно растущие `t`, у каждого frame `crop/caption_safe/speaker_box` — валидные боксы в пределах 1080×1920.
  - `tests/test_fixtures.py::test_testclip_dimensions` — `imageio`/`ffprobe`-обёртка ассертит `1080x1920`, `fps≈30`, `duration≈12`, наличие audio-стрима.
  - `tests/test_fixtures.py::test_banner_is_rgba` — Pillow открывает png, ассертит `mode=='RGBA'`, `size==(420,120)`, есть непрозрачные и прозрачные пиксели.
- **Реализация:** написать `clip0007.meta.json` руками (спикер-бокс по центру верхней половины, caption_safe в нижней трети — как в §3.6-примере), сгенерить mp4/png командами выше, закоммитить фикстуры. Тонкая `ffprobe`-обёртка в `tests/conftest.py`.
- **✅ Готово когда:** 3 теста зелёные; фикстуры в git; mp4 ≤ ~1 МБ.
- **Commit:** `test(p4): add deterministic clip_meta + 1080x1920 testclip + rgba banner fixtures`

---

## Шаг 4.2 — Offer Schema (JSON Schema 2020-12) + Ajv-валидатор

- **Цель / DoD:** Схема из `docs/03` §1.1 **verbatim** + строгий валидатор: валидные офферы проходят, невалидные ловятся **с указанием конкретного поля и причины**. Покрыты `if/then`-правила (`timing.frequency='interval' ⇒ intervalSec`; `payout.model∈{cpm,per_1k_views,hybrid} ⇒ rate`; `payout.model∈{flat,hybrid} ⇒ flatAmount`; `bannerAsset` animated/video ⇒ `durationMs`).
- **Репозитории/команды:** `ajv` + `ajv-formats` (уже добавлены 4.0).
- **Тесты СНАЧАЛА (Vitest, `packages/offer-schema/test/`):**
  - `valid-offers.test.ts`:
    - `test('accepts the canonical NitroGG offer from docs/03 §1.2')` — фикстура `nitrogg.valid.json` (пример из §1.2) → `validateOffer(x).valid === true`.
    - `test('accepts minimal offer with only required blocks')`.
  - `invalid-offers.test.ts` (каждый ассертит `valid===false` И что `errors` указывает на правильный путь):
    - `test('rejects unknown schemaVersion major')` → `schemaVersion:"2.0.0"`.
    - `test('rejects additional properties on brand')` → лишнее поле → error.instancePath `/brand`.
    - `test('rejects non-oklch primaryColor')` → `primaryColor:"#fff"` → pattern-error на `/brand/primaryColor`.
    - `test('rejects http (non-https) urls')` → `websiteUrl:"http://x"`.
    - `test('requires intervalSec when frequency is interval')` → отсутствие `intervalSec` → error.
    - `test('requires rate for cpm payout model')`.
    - `test('requires flatAmount for flat payout model')`.
    - `test('requires durationMs for animated_webm_alpha banner')`.
    - `test('rejects empty banners array')` (`minItems:1`).
    - `test('rejects targeting with empty contentNiches')`.
    - `test('rejects checksumSha256 not matching ^[a-f0-9]{64}$')`.
    - `test('rejects maxCoveragePct above 40')`.
  - `errors.test.ts`: `test('maps ajv error to {field, message} pairs')` — человекочитаемый маппинг.
- **Реализация:** скопировать схему в `advertiser-offer.v1.json`. `validate.ts`: `new Ajv2020({allErrors:true, strict:false})` + `addFormats`, `compile(schema)`, экспорт `validateOffer(data): {valid, errors}`. `errors.ts`: маппинг `instancePath`/`keyword`/`params` → `{field, message}`.
- **✅ Готово когда:** все ~16 тестов зелёные; coverage пакета ≥95%; `pnpm --filter @fliphouse/offer-schema build` чист.
- **Commit:** `feat(p4): advertiser offer JSON Schema 2020-12 + Ajv validator with field-level errors`

🛑 **ЧЕКПОИНТ A:** founder ревьюит контракт ТЗ — поля схемы, enum'ы (`forbiddenCategories`, `position`, `frequency`, `payout.model`), `if/then`-правила, дефолты `forbiddenBands`. Это последний дешёвый момент поменять контракт до того, как форма и движок на него завяжутся. Изменения схемы здесь → дешёвые; после 4.4/4.11 → дорогие.

---

## Шаг 4.3 — Сериализация визарда + oklch color-picker + AA-контраст

- **Цель / DoD:** Чистые функции, превращающие плоский form-state в **валидный** оффер-JSON, и oklch-утилиты для шага «Бренд». `serializeWizard(state)` → объект, который проходит `validateOffer` (используем 4.2 как оракул). Серверные поля (`offerId`/`createdAt`/`updatedAt`/`platformFeePct`) НЕ пишутся клиентом.
- **Репозитории/команды:** `culori` (oklch ↔ rgb, ΔE / контраст).
- **Тесты СНАЧАЛА (Vitest, `apps/web` — jsdom-free unit):**
  - `lib/offers/serializeWizard.test.ts`:
    - `test('serializes full wizard state into a schema-valid offer')` — заполненный стейт → `validateOffer(serializeWizard(s)).valid === true`.
    - `test('omits server-controlled fields (offerId, createdAt, platformFeePct)')`.
    - `test('maps frequency=interval and includes intervalSec')`.
    - `test('drops empty optional blocks instead of writing null')`.
    - `test('coerces numeric slider strings to numbers')` (anchorMarginPct, maxCoveragePct).
  - `lib/offers/oklch.test.ts`:
    - `test('formats hsv picker value as oklch() string')`.
    - `test('parses oklch() string back to picker value (round-trip)')`.
    - `test('computeContrastRatio returns >=4.5 for AA pass pair')` (`contrastColor` на `primaryColor`).
    - `test('flags contrast below AA (4.5) for warning')`.
- **Реализация:** `serializeWizard.ts` (детерминированный маппинг, без побочек), `oklch.ts` (culori `formatCss`/`parse` + APCA/WCAG-контраст-функция). Никаких сетевых вызовов.
- **✅ Готово когда:** все тесты зелёные; `serializeWizard` всегда отдаёт schema-valid JSON на корректном стейте; coverage lib/offers ≥90%.
- **Commit:** `feat(p4): wizard->offer serialization + oklch color utils with AA contrast check`

---

## Шаг 4.4 — Advertiser intake form (5-шаговый визард) + submit→in_review

- **Цель / DoD:** UI-визард (`docs/03` §2): 5 шагов, каждое поле → JSON-путь, клиентская валидация через схему, `submit` ставит `status:"in_review"` и пишет оффер. Дизайн — oklch-токены FlipHouse (`docs/02` §4: glass-поверхность, violet accent), semantic HTML, не template-вид (`web/design-quality`). `PlacementPicker` — визуальный 9:16-пикер слотов + перетаскиваемые safe/forbidden rect'ы.
- **Репозитории/команды:** `react-hook-form` + `@hookform/resolvers` (Ajv-резолвер поверх 4.2).
- **Тесты СНАЧАЛА:**
  - **Vitest + Testing Library (component):**
    - `OfferWizard.test.tsx::test('blocks next step until required fields valid')`.
    - `OfferWizard.test.tsx::test('shows AA contrast warning when contrastColor fails on primaryColor')`.
    - `StepAssets.test.tsx::test('requires at least one 9:16 or 1:1 banner')` (валидатор §2 шаг 2).
    - `StepPlacementTiming.test.tsx::test('reveals intervalSec field only when frequency=interval')`.
    - `PlacementPicker.test.tsx::test('emits normalized rect (0..1) when forbidden band dragged')`.
  - **Playwright e2e (`apps/web/e2e/advertiser-offer.spec.ts`):**
    - `test('advertiser fills wizard end-to-end and submits a valid in_review offer')` — заполнить все 5 шагов → submit → ассертить тост успеха + что persisted-оффер `status==="in_review"` и проходит `validateOffer` (через тест-API/перехват сети).
    - `test('keyboard-only navigation through wizard steps')` (a11y — `web/testing` §2).
- **Реализация:** `OfferWizard.tsx` (RHF owner стейта, `ajvResolver(schema)`), 5 степ-компонентов мапящих поля на блоки `brand/assets/placement+timing/cta/brandSafety+payout+targeting`, `PlacementPicker.tsx` (нормализованные rect'ы, пресеты `tiktok_right_rail`+`bottom_caption_ui` уже нарисованы — дефолты §1.1), `submitOffer.ts` server-action: `validateOffer → reject 422 при invalid → INSERT offer status:in_review`. CSS — токены, без хардкода палитры.
- **✅ Готово когда:** component-тесты + оба e2e зелёные; submit пишет валидный `in_review`-оффер; coverage advertiser-компонентов ≥85%; нет overflow на 320/768/1440 (Playwright screenshots).
- **Commit:** `feat(p4): 5-step advertiser offer intake wizard with placement picker and in_review submit`

🛑 **ЧЕКПОИНТ B:** founder проходит визард сам, проверяет маппинг полей на JSON, качество сериализации (скачать получившийся оффер-JSON), визуальное соответствие токенам, поведение `PlacementPicker`. Можно переставить шаги/поля до того, как движок начнёт потреблять офферы.

---

## Шаг 4.5 — Контракты движка + санитизация входа (fail-fast на границе)

- **Цель / DoD:** Frozen-dataclass контракты (`Offer`, `ClipMeta`, `Frame`, `Box`, `BannerSpec`, `PlacementPlan`) + `sanitize(offer, clip)` из `docs/03` §3.2: clamp каждого бокса в канвас, whitelist enum'ов (animation/anchor), clamp числовых, **отклонение неизвестных enum** (не пробрасываем в FFmpeg), assert монотонности кадров. `asset_path` помечается «argv-only, никогда не в строку графа».
- **Тесты СНАЧАЛА (pytest, `test_sanitize.py`):**
  - `test_rejects_zero_canvas` — `out_w==0` → `ValueError`.
  - `test_rejects_fps_out_of_range` — `fps=300` → reject (диапазон 1..240).
  - `test_rejects_non_monotonic_frames` — `t` не возрастает → reject.
  - `test_clamps_box_to_canvas` — `speaker_box` вылезает за 1080×1920 → клампится (пересечение), не отключает проверку.
  - `test_clamps_negative_box_to_zero_area`.
  - `test_whitelists_unknown_animation_to_default_fade` — `animation="explode"` → `fade`.
  - `test_whitelists_unknown_anchor_to_default_bottom`.
  - `test_clamps_priority_and_min_gap` — out-of-range приоритет/`min_gap_s` клампятся.
  - `test_rejects_banner_larger_than_canvas` — `b.w > out_w` → reject.
  - `test_min_on_screen_le_max_on_screen` — нарушение → reject.
- **Реализация:** `contracts.py` (frozen `@dataclass`), `sanitize.py` — чистые функции, возвращают **новый** sanitized объект (immutability), не мутируют вход. `clampBoxToCanvas`, `whitelist`, `clampInt/Float` как мелкие хелперы.
- **✅ Готово когда:** все тесты зелёные; coverage `sanitize.py`/`contracts.py` ≥95%; функции без I/O.
- **Commit:** `feat(p4): engine contracts + fail-fast input sanitization (clamp/whitelist, reject unknown enums)`

---

## Шаг 4.6 — Анимация → offset-функции (slide_up / fade / pop), closed-form

- **Цель / DoD:** `docs/03` §3.5: каждая анимация — чистая closed-form `(dx,dy,alpha)(τ)` с IN/OUT-рампами `R=0.35с`, покой = `rect.(x,y)`. Те же числа должны давать FFmpeg-expr и MoviePy-колбэк (проверим консистентность в 4.13).
- **Тесты СНАЧАЛА (pytest, `test_animation.py`):**
  - `test_slide_up_starts_80px_below_rest` — `offset(τ=0).dy == 80`, `alpha==... `.
  - `test_slide_up_reaches_rest_after_ramp` — `offset(τ=R).dy == 0`.
  - `test_fade_alpha_ramps_0_to_1_over_R` — `alpha(0)==0`, `alpha(R)==1`, `dx==dy==0`.
  - `test_fade_out_ramps_1_to_0` — на out-рампе `alpha → 0`.
  - `test_pop_scale_maps_to_centered_offset` — scale 0.6→1 мапится в `(dx,dy)` от центра.
  - `test_offsets_are_pure_no_clock` — повторный вызов с тем же τ → идентичный результат.
  - `test_clip_helper_clamps_0_1` — `clip((τ)/R,0,1)` корректен на границах.
- **Реализация:** `animation.py` — `lerp`/`clip` хелперы, `offset_for(anim_type, tau, ramp, rect, from_offset)`. Чистая математика.
- **✅ Готово когда:** все тесты зелёные; coverage ≥95%.
- **Commit:** `feat(p4): closed-form animation offset functions (slide_up/fade/pop) with in/out ramps`

---

## Шаг 4.7 — Brand-safety гейт (fail-closed): NSFW + violence + faces + audio-toxicity

- **Цель / DoD:** `docs/03` §4 целиком. **Один скан на клип, fail-closed.** Разделение: стадии 2/4 — **гейты eligibility**; стадия 3 — **ограничение размещения** (даёт per-frame `speaker_box`-боксы для §3.4). `gate(clip, offer)` → `APPROVE | REVIEW | REJECT`. Любой анализатор упал ИЛИ скор за порогом → **REVIEW** (не auto-list). Задел `forbiddenCategories` / `> minToxicityClearance` / совпал `blockedCompetitorTerms` → клип **not eligible** под этот оффер.
- **Репозитории/команды:** Falconsai NSFW (transformers), YuNet (`vendor/opencv_zoo` → `models/yunet.onnx`), faster-whisper + silero-vad, detoxify + better-profanity + LDNOOBW-листы (`vendor/ldnoobw`). Классификаторы за интерфейсами → в CI мокаются (детерминизм), реальные веса — `@pytest.mark.heavy` smoke.
- **Тесты СНАЧАЛА (pytest, `test_brand_safety_gate.py`):**
  - `test_sampler_emits_1fps_plus_scene_keyframes` — `sampler` на тестклипе даёт ≥ `duration` кадров.
  - `test_nsfw_over_threshold_rejects` (NSFW-классификатор замокан → `nsfw=0.97`) → `REJECT`.
  - `test_nsfw_below_threshold_approves`.
  - `test_violence_over_threshold_rejects`.
  - `test_faces_produce_per_frame_no_banner_boxes` — мок YuNet отдаёт bbox → `gate` персистит `speaker_box`-боксы в результат (НЕ reject — это размещение).
  - `test_face_clearance_px_expands_box` — `faceClearancePx=28` расширяет bbox на 28px каждую сторону.
  - `test_profanity_in_transcript_flags` — мок ASR отдаёт мат из LDNOOBW → severity-flag.
  - `test_toxicity_over_clearance_rejects` — `detoxify`-скор `> minToxicityClearance` → not eligible.
  - `test_blocked_competitor_term_suppresses_offer` — `blockedCompetitorTerms=["Red Bull"]` встретилось в транскрипте → клип not eligible под оффер.
  - `test_forbidden_category_hit_makes_not_eligible` — клип-категория ∈ `offer.forbiddenCategories` → not eligible.
  - **`test_analyzer_exception_fails_closed`** — любой анализатор бросает → результат `REVIEW`, никогда `APPROVE`.
  - `test_gate_is_deterministic_given_mocked_analyzers` — два прогона → идентичный результат.
- **Реализация:** `sampler.py`, `nsfw.py`, `violence.py`, `faces.py` (YuNet `cv2.FaceDetectorYN`, отдаёт боксы + clearance), `audio_toxicity.py` (VAD→ASR→detoxify+better_profanity+LDNOOBW), `gate.py` — оркестратор с `try/except → REVIEW`-обёрткой вокруг **каждого** анализатора (fail-closed), агрегирует решение + персистит safe-боксы размещения. Анализаторы за протоколами для подмены в тестах.
- **✅ Готово когда:** все тесты зелёные; `gate.py` coverage ≥95%; fail-closed-инвариант покрыт; `heavy`-smoke с реальным Falconsai прогнан локально (не в обычном CI).
- **Commit:** `feat(p4): fail-closed brand-safety gate (nsfw/violence/faces/audio-toxicity) with eligibility + placement boxes`

🛑 **ЧЕКПОИНТ C:** founder проверяет fail-closed-поведение на наборе edge-клипов (реальный NSFW, мат в аудио, лицо крупным планом, чистый клип). Убедиться: анализатор-падение → REVIEW; лицо → no-banner-зона, не reject; forbiddenCategory → not eligible. Можно подкрутить пороги до того, как движок начнёт полагаться на `speaker_box`.

---

## Шаг 4.8 — Гард детерминизма движка (CI-инвариант: нет часов/RNG/сети)

- **Цель / DoD:** Зацементировать «rules-engine — чистая детерминированная функция» (`docs/03` §0/§3) тестом-гардом, который **падает**, если в `offer_engine/` появляется `time`/`random`/`datetime.now`/`os.urandom`/сетевой импорт. Это структурный предохранитель против регрессий детерминизма.
- **Тесты СНАЧАЛА (pytest, `test_determinism_guard.py`):**
  - `test_no_clock_or_random_imports_in_offer_engine` — AST-скан всех модулей `offer_engine/` → ассертит отсутствие `import time/random/datetime/secrets`, вызовов `now()/uuid4()/random(`.
  - `test_no_network_imports_in_offer_engine` — нет `requests/httpx/socket/urllib`.
- **Реализация:** `test_determinism_guard.py` — `ast.walk` по файлам пакета, allowlist (напр. `math`). Документировать исключения явно.
- **✅ Готово когда:** гард зелёный на текущем коде; добавлен в CI.
- **Commit:** `test(p4): determinism guard forbidding clock/rng/network imports in offer_engine`

---

## Шаг 4.9 — Выбор временных окон (частота / интервалы / max_concurrent)

- **Цель / DoD:** `docs/03` §3.3 `chooseWindows`: per-banner по приоритету, scan-старты с `step`, интервал `min_gap_s`, частотный кап `max_per_minute`, ужимание длительности `[max..min]_on_screen_s` до бесколлизионного слота, `enforceConcurrency(max_concurrent)`. `scheduleHint`: `even`/`front_load`/`on_silence` (старты только где `speaker_box` отсутствует). **(solveSpatial замокан в этом шаге — реальный в 4.10.)**
- **Тесты СНАЧАЛА (pytest, `test_windows.py`, `solveSpatial` инъектируется как fake):**
  - `test_respects_min_gap_between_appearances` — два появления разнесены ≥ `min_gap_s`.
  - `test_caps_appearances_per_minute` — частотный кап не превышен.
  - `test_max_appearances_per_clip_enforced`.
  - `test_shrinks_duration_until_feasible` — fake отдаёт feasible только при `dur<=N` → окно ужалось до N.
  - `test_drops_banner_when_never_feasible` — fake всегда infeasible → баннер не размещён (уйдёт в dropped в 4.11).
  - `test_priority_order_high_first` — баннер с высшим приоритетом получает слот первым.
  - `test_schedule_hint_on_silence_only_starts_without_speaker` — старты только в кадрах без `speaker_box`.
  - `test_enforce_concurrency_limits_overlap` — ≤ `max_concurrent` одновременных.
  - `test_windows_deterministic` — идентичный вход → идентичный список окон (порядок `(priority desc, t asc)` тотален).
- **Реализация:** `windows.py` — `chooseWindows(offer, clip, solve_spatial)` (DI для теста), `rateLimiter`, `scanStarts(scheduleHint)`, `enforceConcurrency`. Чистые функции.
- **✅ Готово когда:** все тесты зелёные; coverage ≥95%.
- **Commit:** `feat(p4): temporal window selection (frequency/interval/concurrency/schedule-hint)`

---

## Шаг 4.10 — Пространственное решение: AABB collision avoidance (ядро)

- **Цель / DoD:** `docs/03` §3.4 `solveSpatial`: для окна `[t0,t1]` — **union всех боксов-препятствий по кадрам окна** (worst-case occupancy), затем поиск якоря, чей rect не задевает препятствия (AABB-разделение с `pad=M=24px`). `caption_safe` и `speaker_box` — **жёсткие** (если не `allow_overlap_*`). Кандидаты в порядке `preferred_anchor`. Никакой feasible-якорь → `{feasible:false}`. **Это гарантия «баннер никогда поверх субтитров или активного лица».**
- **Тесты СНАЧАЛА (pytest, `test_spatial.py`):**
  - `test_obstacle_union_over_window` — препятствия = union боксов всех кадров окна, не per-frame.
  - `test_banner_never_overlaps_caption_safe` — кандидат, пересекающий `caption_safe`, отвергнут.
  - `test_banner_never_overlaps_speaker_box` — кандидат на активном лице отвергнут.
  - `test_respects_margin_padding` — баннер впритык (зазор < M) считается коллизией.
  - `test_allow_overlap_caption_relaxes_constraint` — при `allow_overlap_caption=True` нижний слот допустим.
  - `test_prefers_anchor_order` — `preferred_anchor='top'` → top-кандидат выбран раньше bottom.
  - `test_returns_infeasible_when_no_anchor_fits` — препятствия покрывают все кандидаты → `feasible=False`.
  - `test_rect_stays_inside_canvas` — выбранный rect ⊂ канвас.
  - `test_noOverlap_aabb_separation_axis` — юнит-тесты `noOverlap` на 4 осях разделения + перекрытие.
  - `test_spatial_deterministic`.
- **Реализация:** `spatial.py` — `solveSpatial`, `mergeBoxes` (union), `anchorRects(preferenceOrder)`, `noOverlap(a,b,pad)` (AABB), `insideCanvas`. Именованная константа `M = 24`.
- **✅ Готово когда:** все тесты зелёные; coverage ≥95%; collision-инвариант доказан.
- **Commit:** `feat(p4): spatial solver with AABB collision avoidance (banner never over caption/face)`

---

## Шаг 4.11 — `plan(offer, clip_meta) → PlacementPlan` + input_hash + dropped[]

- **Цель / DoD:** Композиция `docs/03` §3.6: `sanitize → chooseWindows(solveSpatial) → makeAssignment → PlacementPlan`. Выход — JSON-контракт `offer-rules/placement-plan@1` (`canvas`, `placements[]` с `rect/anchor/t_start/t_end/animation/constraints_resolved`, `dropped[]` с `{banner_id, reason}`, `determinism.input_hash`). `input_hash = sha256(offer, clip_meta, engine_version)` — ключ кеша. Golden-сравнение против `golden/placement_plan_clip0007.json`.
- **Тесты СНАЧАЛА (pytest, `test_plan_determinism.py`):**
  - `test_plan_matches_golden_for_clip0007` — `plan(nitrogg_offer, clip0007)` == `golden/placement_plan_clip0007.json` (детерминированный байт-в-байт после канонической JSON-сериализации).
  - `test_input_hash_stable_across_runs` — два прогона → одинаковый `input_hash`.
  - `test_input_hash_changes_when_offer_changes` — другой оффер → другой hash.
  - `test_input_hash_changes_with_engine_version`.
  - `test_infeasible_banner_goes_to_dropped_with_reason` — баннер без слота → в `dropped[]`, НЕ в `placements[]`, НЕ на лице.
  - `test_placement_carries_resolved_obstacle_union` — `constraints_resolved.obstacle_union_in_window` заполнен.
  - `test_plan_pure_no_side_effects` — вход не мутирован после вызова.
- **Реализация:** `plan.py` — оркестрация чистых функций, каноническая JSON-сериализация (sorted keys, фикс float-формат) для стабильного хеша, `engine_version="1.0.0"`. Сгенерить golden-файл из первого зелёного прогона, заверить вручную (founder-ревью на чекпоинте D).
- **✅ Готово когда:** все тесты зелёные; golden зафиксирован; coverage `plan.py` ≥95%; детерминизм-гард (4.8) зелёный.
- **Commit:** `feat(p4): deterministic plan() producing PlacementPlan with input_hash and observable dropped[]`

🛑 **ЧЕКПОИНТ D:** founder ревьюит `golden/placement_plan_clip0007.json` — корректность слотов (не на caption/лице), частоты, fade, и `dropped[]` с причинами. Diffable-контракт: любое будущее изменение движка видно как diff golden-файла. Подтверждение golden = заверение поведения движка.

---

## Шаг 4.12 — FFmpeg codegen: PlacementPlan → filtergraph (injection-hardened)

- **Цель / DoD:** `docs/03` §3.7: кодоген обходит `placements[]`, эмитит **один `overlay`-узел на баннер** цепочкой, `[base]` от реврейма. Примитивы: `format=rgba,fade=t=in/out:alpha=1` на входе баннера; `overlay=x=..:y='<expr>':eval=frame:enable='between(t,a,b)'`. **Безопасность filtergraph (`docs/01` §6, `docs/03` §3.7):** все числа clamp/whitelist'нуты ДО интерполяции; граф пишется в `-filter_complex_script FILE`, **никогда** в shell/`-filter_complex`-арг; `asset_path` идёт отдельным `-i` argv. Snapshot-сравнение против `golden/plan_0007.filtergraph`.
- **Репозитории/команды:** сверка паттерна с `vendor/openshorts/hooks.py:add_hook_to_video` (не копируем).
- **Тесты СНАЧАЛА (pytest, `test_codegen_ffmpeg.py` + `test_injection.py`):**
  - `test_codegen_ffmpeg.py`:
    - `test_filtergraph_matches_golden` — snapshot против `plan_0007.filtergraph` (пример из §3.7).
    - `test_emits_one_overlay_per_placement` — N placements → N overlay-узлов, цепочка `[vout_k]`.
    - `test_enable_between_uses_window_bounds` — `enable='between(t,6.0,11.0)'` с правильными границами.
    - `test_eval_frame_present_when_position_animated` — анимированная позиция ⇒ `eval=frame`.
    - `test_fade_alpha_on_banner_input` — `fade=t=in:st=..:alpha=1` на входе баннера.
    - `test_argv_lists_each_banner_as_separate_input` — `-loop 1 -i <path>` per banner, индексы совпадают с `input_index`.
    - `test_slide_up_y_expression_matches_animation_offset` — y-expr использует те же числа, что 4.6.
  - **`test_injection.py` (CRITICAL — founder zero-bug):**
    - `test_malicious_headline_cannot_break_graph` — оффер с `headline="x,split:y=0[a]"` → текст НЕ попадает в граф (баннер — PNG; текст рендерится out-of-band), граф не содержит инжекта.
    - `test_asset_path_with_special_chars_stays_argv` — `asset_path` с `;,'` → передаётся как argv, не интерполируется в строку графа.
    - `test_numeric_fields_clamped_before_interpolation` — попытка `x="0,overlay"` → reject/clamp (parse-to-number).
    - `test_no_filter_complex_string_arg_used` — кодоген эмитит путь к `-filter_complex_script`, не inline-строку.
    - `test_fontfile_only_from_allowlist` — попытка задать произвольный `fontfile` отвергнута.
    - `test_reject_non_numeric_coordinate_raises`.
- **Реализация:** `codegen_ffmpeg.py` — `emit_filtergraph(plan) -> (graph_text, input_args)`, числовая интерполяция только после `int()/float()` + clamp, allowlist для anim-типов и шрифтов, запись графа в файл (caller отдаёт `-filter_complex_script`). Текст баннера — НЕ в граф (PNG-баннер). Сгенерить golden из первого прогона, сверить с §3.7-примером вручную.
- **✅ Готово когда:** все тесты (incl. все injection) зелёные; golden filtergraph зафиксирован; coverage ≥95%.
- **Commit:** `feat(p4): injection-hardened FFmpeg overlay codegen (script-only graph, argv inputs, clamped numerics)`

---

## Шаг 4.13 — MoviePy v2 фолбэк-кодоген (те же числа, два бэкенда)

- **Цель / DoD:** `docs/03` §3.7: MoviePy-путь для окружений без libfreetype-FFmpeg / сложной per-frame Python-логики. `ImageClip.with_position(pos)` где `pos(t)` использует **те же** offset-функции (4.6), `CrossFadeIn/Out(ramp)`, `CompositeVideoClip`. Инъекция схлопывается в обычную Python-валидацию — всё равно clamp координат/длительностей, allowlist путей.
- **Тесты СНАЧАЛА (pytest, `test_codegen_moviepy.py`):**
  - `test_position_callback_matches_ffmpeg_y_at_sampled_times` — `pos(t)` MoviePy == y-expr FFmpeg (4.12) на сэмплах τ∈{0, R/2, R, mid} (консистентность бэкендов).
  - `test_banner_start_and_duration_from_placement` — `with_start/with_duration` из плана.
  - `test_crossfade_uses_ramp_s`.
  - `test_paths_allowlisted_and_clamped` — тот же injection-гард на Python-уровне.
  - `test_composite_layers_base_plus_banners`.
- **Реализация:** `codegen_moviepy.py` — `build_clip(plan, base_path) -> CompositeVideoClip` (lazy, без рендера в этом тесте), переиспользует `animation.offset_for`. Рендер — в 4.14.
- **✅ Готово когда:** все тесты зелёные; консистентность с FFmpeg-бэкендом доказана; coverage ≥90%.
- **Commit:** `feat(p4): MoviePy v2 fallback codegen sharing animation numbers with ffmpeg backend`

---

## Шаг 4.14 — Render-assertion: баннерные пиксели в запланированных x/y и только в окне

- **Цель / DoD:** Реальный рендер тестклипа (4.1) обоими бэкендами и **попиксельная** проверка: баннер (magenta-паттерн) присутствует в кадрах внутри `[t_start,t_end]` в районе `rect.(x,y)`, и **отсутствует** вне окна. Ассертим не «ffmpeg отработал», а duration/dimensions/frame-hash/overlay-presence (`web/testing` §performance + промпт). Это финальное доказательство всего движка end-to-end.
- **Репозитории/команды:** реальный ffmpeg (P1-рантайм) + `imageio`/`numpy` для извлечения кадров.
- **Тесты СНАЧАЛА (pytest, `test_render_assertion.py`):**
  - `test_ffmpeg_render_output_dimensions_and_duration` — out.mp4 == 1080×1920, duration ≈ исходная, есть audio (`-c:a copy`).
  - `test_banner_pixels_present_at_planned_xy_during_window` — извлечь кадр на `t=(t_start+t_end)/2`, проверить, что в bbox `rect` доминирует magenta (баннер-паттерн) → присутствует в запланированном месте.
  - `test_banner_absent_before_appear_at` — кадр на `t < t_start` → в том же bbox НЕТ баннер-паттерна (окно `enable=between` уважается).
  - `test_banner_absent_after_window` — кадр на `t > t_end` → нет баннера.
  - `test_banner_never_covers_speaker_box_region` — в кадрах окна регион `speaker_box` НЕ содержит баннер-пиксели (доказательство collision-avoidance на реальном рендере).
  - `test_moviepy_backend_produces_equivalent_banner_position` — рендер MoviePy-бэкендом → баннер в том же bbox (бэкенды эквивалентны на пикселях, с допуском).
  - `test_render_idempotent_same_input_hash_same_output_hash` — два рендера одного плана → одинаковый frame-hash (детерминизм рендера).
- **Реализация:** `tests/render_helpers.py` — обёртки запуска ffmpeg с `-filter_complex_script` (из 4.12) и MoviePy-рендера (из 4.13), извлечение кадров по `t`, magenta-detection в bbox (numpy mask + порог доли пикселей). Маркер `@pytest.mark.render` (запускается в CI с ffmpeg, но отделим от unit-сюиты).
- **✅ Готово когда:** все render-тесты зелёные; баннер доказан в нужном x/y/времени и не на лице; оба бэкенда эквивалентны; рендер детерминирован.
- **Commit:** `test(p4): actual-render assertions proving banner pixels at planned x/y/time and off-face`

🛑 **ЧЕКПОИНТ E:** founder смотрит реально отрендеренный клип (артефакт из 4.14, оба бэкенда). Глазами проверяет: баннер в нужном слоте, появляется/исчезает в правильное время, не накрывает лицо/субтитры, fade плавный. Это финальная приёмка дифференциатора фазы. Можно отрегулировать дефолты анимации/маржи до закрытия фазы.

---

## Шаг 4.15 — Интеграционная сшивка: gate → plan → codegen → render (один проход)

- **Цель / DoD:** Тонкий оркестратор `process_clip_for_offer(clip, offer) -> result`, склеивающий фазу: brand-safety gate (4.7) → если eligible, берём safe-боксы как `speaker_box` → `plan()` (4.11) → `codegen` (4.12) → render. Если gate = REJECT/REVIEW или клип not eligible под оффер → **ранний выход «not eligible»**, движок размещения не запускается. Это контракт, который P1/BullMQ-flow (`banner`-стадия, `docs/01` §2/§5) будет вызывать.
- **Тесты СНАЧАЛА (pytest, `test_pipeline_integration.py`):**
  - `test_unsafe_clip_skips_placement_entirely` — gate REJECT → нет `PlacementPlan`, результат `not_eligible`, причина проброшена.
  - `test_forbidden_category_clip_not_eligible_for_offer` — клип-категория в `offer.forbiddenCategories` → not eligible, placement не запускался.
  - `test_safe_clip_produces_plan_and_filtergraph` — чистый клип → eligible → есть `PlacementPlan` + filtergraph.
  - `test_face_boxes_from_gate_feed_spatial_solver` — боксы лиц из gate (стадия 3) реально используются `solveSpatial` (баннер уклоняется от них).
  - `test_pipeline_deterministic_end_to_end` — одинаковый вход → одинаковый `input_hash` + filtergraph.
- **Реализация:** `offer_engine/pipeline.py` — `process_clip_for_offer`, чистая композиция (gate-результат инъектируется/мокается в тесте). Возвращает структурированный результат `{eligible, plan?, filtergraph_path?, reason?}`.
- **✅ Готово когда:** все интеграционные тесты зелёные; not-eligible-путь не трогает placement; coverage пайплайна ≥90%.
- **Commit:** `feat(p4): integrate brand-safety gate -> plan -> codegen pipeline (not-eligible short-circuit)`

---

## Шаг 4.16 — Фиксация coverage-гейтов и финальная проверка фазы

- **Цель / DoD:** Поднять per-module coverage-пороги в CI (offer_engine + brand_safety/gate ≥95%, web-форма ≥85%, остальное ≥80%), прогнать полный gate (Vitest + Playwright + pytest unit + pytest render), убедиться, что детерминизм-гард и все injection-тесты в обязательном CI-пути.
- **Тесты СНАЧАЛА:** не новые фичи — это gate-конфигурация. Добавить `--cov-fail-under` пер-пакет; CI-job, падающий если любой инвариант-тест (детерминизм, injection, fail-closed, render-presence) пропущен/скипнут без причины.
- **Реализация:** обновить `pyproject.toml`/`vitest.config.ts`/CI-workflow; пометить `heavy`/`render` маркеры явно; README-секция «как запускать P4-сюиту».
- **✅ Готово когда:** полный CI зелёный с поднятыми порогами; все 5 чекпоинтов закрыты founder'ом.
- **Commit:** `chore(p4): enforce per-module coverage gates and wire invariant tests into CI`

---

## Выход фазы (Phase exit criteria)

- [ ] **Схема оффера** (`advertiser-offer.v1.json`) валидирует валидные офферы и ловит невалидные с указанием поля; все `if/then`-правила (timing/payout/banner) покрыты тестами. *(4.2)*
- [ ] **Advertiser intake form** — 5-шаговый визард, поля мапятся на JSON-пути, `submit → status:in_review` пишет schema-valid оффер; e2e (Playwright) + a11y зелёные; визуал на oklch-токенах, не template. *(4.3–4.4)*
- [ ] **Brand-safety гейт fail-closed** — анализатор-падение/скор-за-порогом → REVIEW (не auto-list); NSFW/violence/toxicity → eligibility; face/region → per-frame `speaker_box`; forbiddenCategories/competitorTerms → not eligible. *(4.7)*
- [ ] **Rules-engine детерминирован** — `plan(offer, clip_meta)` без часов/RNG/сети (CI-гард), golden-`PlacementPlan` зафиксирован, `input_hash` стабилен и меняется на изменение входа, инфизибельные баннеры → `dropped[]` с причиной. *(4.5–4.6, 4.8–4.11)*
- [ ] **Коллизии исключены** — баннер НИКОГДА не поверх `caption_safe` или активного `speaker_box` (доказано unit-тестами solveSpatial И попиксельным render-assertion). *(4.10, 4.14)*
- [ ] **FFmpeg codegen injection-hardened** — граф только через `-filter_complex_script FILE`, числа clamp/whitelist'нуты, `asset_path`/`fontfile` argv/allowlist, malicious headline/path не ломает граф (injection-сюита зелёная). *(4.12)*
- [ ] **MoviePy-фолбэк** даёт ту же позицию/тайминг, что FFmpeg-бэкенд (консистентность бэкендов доказана). *(4.13)*
- [ ] **Render-assertion** — реальный рендер: баннерные пиксели в запланированных x/y и **только** во временном окне, не на лице; рендер детерминирован (frame-hash). *(4.14)*
- [ ] **Пайплайн сшит** — `gate → plan → codegen → render` с not-eligible short-circuit; контракт готов для BullMQ `banner`-стадии (P1/`docs/01` §5). *(4.15)*
- [ ] **Coverage-гейты** держатся: ядро ≥95%, форма ≥85%, остальное ≥80%; все инвариант-тесты (детерминизм/injection/fail-closed/render) — обязательная часть CI. *(4.16)*
- [ ] Все 5 чекпоинтов (A–E) пройдены и заверены founder'ом.
```
