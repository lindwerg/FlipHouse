# P2 — Загрузка + AI-нарезка MVP (openshorts + OpenRouter) на Railway

> Фаза 2 = ядро ценности продукта. На входе — длинное видео, на выходе — ранжированные вертикальные клипы 9:16, видимые в дашборде. Всё CPU-only на Railway; GPU-тяжёлые стадии (точный ASD/inpainting) заглушены и помечены флагами для Phase 3.
>
> Источники истины: `docs/01-АРХИТЕКТУРА-И-RAILWAY.md` (топология, Flow-DAG, content-hash, FFmpeg-рантайм, tusd→R2) и `docs/04-ИНТЕГРАЦИИ-PWA-AI-ПУБЛИКАЦИЯ.md` §2 (OpenRouter-адаптер, JSON-schema, роутинг моделей).

---

## ⭐ [FOUNDER EDIT · 2026-06-16 · RE-PLAN ДВИЖКА СКОРИНГА] — на ЧЕКПОИНТЕ A

> **Контекст.** На ЧЕКПОИНТЕ A (после P2.2-адаптера) founder затребовал реально лучший движок: «вирусность должна быть максимальной, движок должен вырезать реально крутые моменты». Поднята ultracode-разведка (11-агентный workflow + отдельный Gemini-агент + adversarial-верификатор). Вывод: **сегодняшний движок читает только ТЕКСТ-транскрипт и слеп+глух к ~половине сигналов вирусности** (мимика, движение, склейки, смех, энергия голоса, музыка, удар-после-паузы). Это корень «нарезает не то».
>
> **РЕШЕНИЕ FOUNDER'А:** (1) дефолт-тариф качества = **ИДЕАЛ** (`google/gemini-3.5-flash` — нативно смотрит видео + слышит звук, GA-стабильная, лучшее видео-понимание в классе); (2) архитектура = **каскад** (дёшево отобрать кандидатов по тексту → видео+звук пере-скоринг финалистов); (3) первый шаг — **eval-harness** (иначе «максимальная вирусность» недоказуема). **[FOUNDER EDIT-2 · 2026-06-16] ВСЁ ЧЕРЕЗ OpenRouter, ВЕЗДЕ Gemini** — без отдельной интеграции с Google. Stage A = `google/gemini-3.1-flash-lite`, Stage B = `google/gemini-3.5-flash`, оба через OpenRouter.
>
> **Тарифы качества (переключаемые конфигом, дефолт=Идеал), на креатора/300 мин-мес, всё через OpenRouter (default-res):** Бюджет (audio-only `gemini-3.1-flash-lite`) · Баланс (native A/V `gemini-3.1-flash-lite`) · **Идеал (native A/V `gemini-3.5-flash` ⭐дефолт, ~пара $/мес)**. Контекст: PAYG-выручка $75/мес, GPU-рендер ~$7.5/мес — даже Идеал = ~единицы % выручки. Узкое место — качество отбора, не деньги.
>
> **Верифицированные ограничения (учесть обязательно):** (а) **ВСЁ держим на OpenRouter — прямой Gemini API НЕ нужен.** В мультимодальную модель идут ТОЛЬКО короткие пре-нарезанные клипы (**≤ ~50 сек**, для Shorts это норма), а не 30-мин исходник → OpenRouter пропускает их в Gemini через base64 (лимит <100 МБ / ~1 мин — клипы влезают). Через OpenRouter недоступен knob `media_resolution=low` → платим default-res (~263 tok/s вместо ~100), но на масштабе коротких клипов это копейки. Целое видео в модель НЕ отправляем никогда. Прямой Gemini File API — опциональная оптимизация на потом (low-res-скидка), не блокер. (б) **`deepseek-chat` отвергает strict json_schema** — латентная мина, убрать из fallback-массива `SCORING`. (в) убрать `sort:"price"` из `SCORING` (может увести на провайдера без видео/без strict). (г) Stage B скорит ПРЕ-нарезанные клипы → таймкоды владеет ffmpeg-оркестратор, модель их НЕ генерит (анти-галлюцинация). (д) схему проверить на Gemini (subset JSON-Schema, риск `400 InvalidArgument` на сложных enum).
>
> **НОВАЯ ПОСЛЕДОВАТЕЛЬНОСТЬ ШАГОВ (заменяет текстовый план 2.3+ для части «скоринг»; 2.0/2.1/адаптер 2.2 остаются как есть):**
> - **P2-S1 — Eval-harness (gate, ПЕРВЫМ).** ~15-20 клипов с человеческими виральными рангами + метрики: Spearman vs human ≥ порог, std-dev score ≥ floor (анти-слипание), sub-scores расходятся. Scorer-agnostic, юнит-тестим на мок-оценках. Это catover-gate всех последующих шагов (doc 04 §2.8).
> - **P2-S2 — Reliability-фиксы адаптера/роутинга.** Подключить движок к `complete_json` (сейчас движок ходит мимо — через сырой `Callable[[str],str]`); убрать `deepseek-chat` и `sort:"price"` из `SCORING`; захват `model_used`/`raw_usage`. **Всё Gemini через OpenRouter:** `SCORING` (Stage A текст) → `google/gemini-3.1-flash-lite` (+ Gemini-fallback, напр. `gemini-2.5-flash-lite`); `SCORING_MULTIMODAL` (Stage B) → `google/gemini-3.5-flash`.
> - **P2-S3 — Новая рубрika + промпт + схема (ещё text-only).** Взвешенная рубрика (HOOK/payoff ×2), anchored bands + анти-clustering калибровка, `PER_CLIP_VIRALITY_SCHEMA` (под-оценки hook/emotion/payoff/visual/audio/pacing + confidence + modalities_used), sweet-spot длины 15-40с, temp=0.0. Прогон через eval-harness.
> - **P2-S4 — Расширить seam под медиа.** `Callable[[str],str]` → структурный запрос с content-parts (text + video_url/image_url) через `complete_json`; текстовый путь не ломается (regression-тест).
> - **P2-S5 — Stage 0 (ffmpeg DSP) + split Stage A (recall) / Stage B (per-clip).** Локальные сигналы (RMS-энергия, склейки, флаги смех/музыка); recall-цикл → per-clip структура (Stage B пока на тексте).
> - **P2-S6 — Stage B native A/V через OpenRouter (дефолт=Идеал `gemini-3.5-flash`).** Stage B шлёт нарезанные клипы (**≤ ~50 сек**, base64 `video_url`) в `gemini-3.5-flash` через OpenRouter `complete_json` — БЕЗ отдельной Gemini-интеграции. Gate eval-harness'ом: каскад бьёт text-only по Spearman. Параллелить per-clip вызовы. (Прямой Gemini File API + media_resolution=low — опциональная оптимизация стоимости на потом, не в этом шаге.)
> - **P2-S7 — Тарифы как config-knob + эскалация + наблюдаемость.** Бюджет/Баланс/Идеал переключаются; эскалация спорных (score∈[45,65] или confidence<0.6) на топ-проход; лог стоимости/модели на джобу; финальный eval-harness как catover-gate.
>
> Полный разбор (промпт целиком, схема, рубрика, код-диффы) — в результате workflow и моём сообщении founder'у от 2026-06-16. Старые шаги 2.3–2.13 ниже частично поглощаются/переупорядочиваются этим re-plan'ом (DAG/tusd/store/дашборд из них остаются актуальны).

---

## Цель фазы (Phase goal)

Поднять полный путь **resumable-загрузка → R2 → post-finish hook → BullMQ Flow-DAG (`validate → transcode → asr → score → clip → store`) → ранжированные клипы 9:16 в дашборде**. Движок нарезки вендорится из `mutonby/openshorts` (`main.py`), Gemini-вызов выбора хайлайтов свопается на OpenRouter (OpenAI-совместимый адаптер, `response_format: json_schema strict`, роутинг моделей по doc 04 §2.3). Транскрипция — `faster-whisper` (`base`, `device=cpu`, `compute_type=int8`) — это «degraded CPU»-путь из doc 01 §3, осознанно выбранный как MVP-baseline. GPU-плечо (LR-ASD / DiffuEraser / SAM2) **не реализуется** — стадии `score`-reframe вызывают CPU-fallback (MediaPipe/blur-pad из openshorts) и помечены `# PHASE3-GPU` для выноса на Replicate/Modal/fal.

**Definition of Done фазы:** залитое через tusd видео автоматически проходит DAG, в Postgres появляется `upload_ledger` строка со `status=done` и `result_url`, в дашборде `web` показываются N клипов с корректными **длительностью, разрешением 1080×1920 и порядком ранжирования по score**. Повторная загрузка тех же байтов — no-op (идемпотентность по content-hash). Все тесты зелёные, покрытие ≥ 80% на новом коде.

---

## Зависимости (какие фазы должны быть готовы)

- **P0 — Каркас и инфра** (ОБЯЗАТЕЛЬНО): Railway-проект `production`+`staging`, сервис `web` (форк `nextjs/saas-starter` + лендинг), `Postgres` (+volume), `Redis`, приватная сеть через `_PRIVATE_`-URL, healthcheck `/api/health`. Без этого негде запускать hook-receiver/воркеры и некуда писать леджер.
- **P1 — (если выделена отдельно)**: в этом роадмапе P1-объём (вендоринг openshorts, swap, базовый воркер) **поглощён в P2** как атомарные шаги ниже. Если P1 уже сделана частично — переиспользовать `vendor/openshorts` и пропустить шаг 2.1.

**Внешние предусловия (готовятся параллельно P0, проверяются в шаге 2.0):**
- Cloudflare R2 bucket `fliphouse-media` + S3-API креды (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION=auto`, `R2_ENDPOINT`).
- `OPENROUTER_API_KEY` (можно dev `:free`-тир для тестов; в тестах — мок).

---

## Репозитории, клонируемые/используемые в этой фазе

Все клоны идут в `vendor/` (git-игнорируемый снаружи сборки, файлы lift'ятся в `services/*`):

```bash
git clone https://github.com/mutonby/openshorts.git              vendor/openshorts
git clone https://github.com/tus/tusd.git                        vendor/tusd          # деплоится как готовый образ tusproject/tusd; клон — для референса hook-контракта
git clone https://github.com/taskforcesh/bullmq.git              vendor/bullmq         # референс Flow API; сам пакет ставится через pnpm
git clone https://github.com/felixmosh/bull-board.git           vendor/bull-board     # референс дашборда; ставится через pnpm
```

NPM/PyPI-зависимости (ставятся, не клонируются):

```bash
# Node (hook-receiver, orchestrator, cpu-worker-оркестрация, web)
pnpm add bullmq @bull-board/api @bull-board/express @aws-sdk/client-s3 @aws-sdk/s3-request-presigner ioredis pg
pnpm add -D vitest @vitest/coverage-v8 @playwright/test testcontainers

# Python (ai-worker-python: движок нарезки + OpenRouter-адаптер + faster-whisper)
pip install openai faster-whisper mediapipe pyscenedetect opencv-python-headless numpy pydantic
pip install --dev pytest pytest-cov pytest-mock respx httpx
```

> Lift-карта (что именно достаём из `vendor/openshorts` в `services/ai-worker-python`): `main.py` (движок `transcribe → get_viral_clips → cut → process_video_to_vertical`), `hooks.py` (`add_hook_to_video` — референс баннера, в P2 не вставляем, оставляем заглушку), `fonts/`. **Discard:** `editor.py`, `saasshorts.py`, `thumbnail.py`, `app.py` (Gemini File API / image-gen — не нужны и несовместимы с OpenRouter, см. doc 01 §1).

---

## Чекпоинты фазы (founder review)

1. 🛑 **ЧЕКПОИНТ A** (после 2.2) — OpenRouter-адаптер: правильные ли модели/роуты, формат JSON-схемы, поведение fallback.
2. 🛑 **ЧЕКПОИНТ B** (после 2.4) — Python-движок нарезки: на фикстуре-видео реально выдаёт клипы нужной длительности/размера, ранжирование осмысленное.
3. 🛑 **ЧЕКПОИНТ C** (после 2.7) — Flow-DAG: джоба проходит все стадии, идемпотентна по content-hash, failure-семантика верна.
4. 🛑 **ЧЕКПОИНТ D** (после 2.9) — tusd→R2→hook: реальная загрузка триггерит DAG, леджер заполняется.
5. 🛑 **ЧЕКПОИНТ E** (после 2.11) — E2E в дашборде: видео в → ранжированные клипы 9:16 видны и играются.

---

## Соглашения по тестам (общие для всех шагов)

- **TS** (`services/hook-receiver`, `services/orchestrator`, `web`): **Vitest** (unit/integration) + **Playwright** (e2e). Интеграционные тесты с Redis/Postgres — через `testcontainers` (поднимают эфемерные контейнеры, не моки), чтобы BullMQ Flow и `ON CONFLICT`-идемпотентность проверялись на настоящем брокере.
- **Python** (`services/ai-worker-python`): **pytest** + `pytest-cov`; HTTP к OpenRouter мокается через `respx`. Рендер-пайплайн проверяется на **golden-фикстуре** — реальный короткий тестовый клип `tests/fixtures/sample_30s.mp4` (синтетический, 30с, говорящая голова + смена сцены), ассерты — на **выходных файлах** (длительность через `ffprobe`, размеры кадра, число клипов, монотонность score), а не на «скрипт отработал».
- **Покрытие:** gate ≥ 80% на изменённых файлах. Шаг не «готов», пока тесты не зелёные И gate не держится.
- **Каждый шаг = один git-commit.** Формат `<type>: <message>` (feat/fix/test/refactor/chore).

---

# Шаги

### Шаг 2.0 — Скелет монорепо + проверка внешних предусловий

- **Цель / DoD:** в репозитории появляется структура `services/{ai-worker-python,hook-receiver,orchestrator,cpu-worker}` + `infra/`, настроены Vitest/pytest-раннеры, есть smoke-тест «инфра доступна» (R2 ping, Redis ping, Postgres ping) — проходит против testcontainers/локальных эмуляторов. Никакой бизнес-логики.
- **Репозитории/команды:**
  ```bash
  mkdir -p services/ai-worker-python services/hook-receiver services/orchestrator services/cpu-worker infra tests/fixtures vendor
  pnpm init && pnpm add -D vitest @vitest/coverage-v8 testcontainers
  python -m venv services/ai-worker-python/.venv && pip install pytest pytest-cov
  printf 'vendor/\n.venv/\nnode_modules/\n*.mp4\n!tests/fixtures/*.mp4\n' > .gitignore
  ```
- **Тесты СНАЧАЛА:**
  - `services/hook-receiver/test/infra.smoke.test.ts` → `test('redis is reachable', ...)` поднимает Redis-контейнер, `PING` → `PONG`; `test('postgres accepts a connection', ...)` поднимает Postgres-контейнер, `SELECT 1`.
  - `services/ai-worker-python/tests/test_smoke.py` → `def test_ffprobe_available()` ассертит `shutil.which("ffprobe") is not None`; `def test_import_engine_deps()` импортирует `faster_whisper`, `openai`, `mediapipe` без ошибок.
  - Harness: Vitest + testcontainers; pytest.
- **Реализация:** `vitest.config.ts` (coverage v8, threshold 80), `pyproject.toml` (`[tool.pytest.ini_options]` + `--cov-fail-under=80`), `services/*/package.json` со скриптами `test`. Dockerfile-заглушки для каждого сервиса (наполним позже).
- **✅ Готово когда:** оба smoke-сьюта зелёные локально; `pnpm test` и `pytest` запускаются из корня; manual: `ffprobe -version` есть в окружении воркера.
- **Commit:** `chore: scaffold P2 monorepo services + test runners`

---

### Шаг 2.1 — Вендоринг openshorts + lift движка, discard несовместимого

- **Цель / DoD:** `vendor/openshorts` склонирован; в `services/ai-worker-python/engine/` лежат только нужные файлы (`main.py` как `engine.py`, `fonts/`); несовместимые модули НЕ перенесены; модуль импортируется и его публичные функции (`transcribe`, `get_viral_clips`, `process_video_to_vertical`) видимы. Gemini-вызов пока на месте (свопаем в 2.3) но изолирован за инъекцией `llm_fn`.
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/mutonby/openshorts.git vendor/openshorts
  cp vendor/openshorts/main.py   services/ai-worker-python/engine/engine.py
  cp -r vendor/openshorts/fonts  services/ai-worker-python/engine/fonts
  cp vendor/openshorts/hooks.py  services/ai-worker-python/engine/hooks.py   # референс баннера (P2 не вставляет)
  # НЕ копировать: editor.py, saasshorts.py, thumbnail.py, app.py (Gemini File API / image-gen — discard, doc 01 §1)
  ```
- **Тесты СНАЧАЛА:**
  - `tests/test_engine_imports.py`:
    - `test_engine_exposes_pipeline_functions()` — `hasattr(engine, "transcribe")`, `"process_video_to_vertical")`, и точка выбора хайлайтов (`get_viral_clips`) существует.
    - `test_no_discarded_modules_present()` — ассертит, что в `engine/` НЕТ `editor.py`/`saasshorts.py`/`thumbnail.py` (защита от случайного копирования Gemini-зависимостей).
    - `test_highlight_selector_accepts_injected_llm()` — рефактор-страховка: функция выбора клипов принимает инъекцию `llm_fn` (а не хардкод Gemini-клиента).
- **Реализация:** скопировать файлы; минимальный рефактор `engine.py` — выделить сигнатуру `get_viral_clips(transcript, *, llm_fn)` (или адаптер-обёртку `select_highlights(transcript, llm_fn)`), вырезать hardcoded CTA из системного промпта (doc 01 §1 + MASTER Phase 1: `main.py:55`). НЕ менять провайдера ещё — только сделать его инъектируемым.
- **✅ Готово когда:** 3 теста зелёные; `python -c "from engine import engine"` без сетевых вызовов; manual-diff показывает, что CTA-строка удалена.
- **Commit:** `feat: vendor openshorts engine, lift pipeline, inject llm_fn seam`

---

### Шаг 2.2 — OpenRouter-адаптер (Python) + JSON-schema контракт

- **Цель / DoD:** реализован `services/ai-worker-python/llm/openrouter_adapter.py` по doc 04 §2.6: OpenAI-совместимый клиент (`base_url=https://openrouter.ai/api/v1`), профили `SCORING`/`OFFER_MATCH` с роут-конфигами (модели + `provider.require_parameters:true`), `complete_json(...)` с `response_format=json_schema strict`, retry/backoff на 429/5xx, 402→fatal. Всё с мокнутыми ответами — реальная сеть не дёргается в тестах.
- **Репозитории/команды:** `pip install openai respx httpx` (адаптер — наш код, doc 04 даёт готовый sketch).
- **Тесты СНАЧАЛА** (`tests/llm/test_openrouter_adapter.py`, harness pytest + respx):
  - `test_scoring_profile_routes_to_cheap_models_in_order()` — мок перехватывает body, ассертит `extra_body["models"] == ["google/gemini-2.5-flash","openai/gpt-5-mini","deepseek/deepseek-chat"]` и `provider == {"sort":"price","require_parameters":True}`.
  - `test_offer_match_profile_uses_strong_models()` — ассертит strong-роут `["anthropic/claude-sonnet-4.5","openai/gpt-5","google/gemini-2.5-pro"]`.
  - `test_sends_json_schema_strict_response_format()` — ассертит `response_format.type=="json_schema"`, `json_schema.strict is True`, имя схемы прокинуто.
  - `test_attribution_headers_present()` — `HTTP-Referer: https://fliphouse.app`, `X-OpenRouter-Title: FlipHouse`.
  - `test_parses_valid_json_response()` — мок возвращает валидный JSON по схеме → `LLMResult.data` распарсен, `model_used` заполнен.
  - `test_raises_on_non_json_despite_strict()` — мок возвращает свободный текст → `ValueError("Non-JSON despite strict schema...")`.
  - `test_retries_on_429_then_succeeds()` — первый ответ 429, второй 200 → ровно 2 вызова, успех; backoff замокан (no real sleep).
  - `test_402_is_fatal_no_retry()` — 402 → `RuntimeError("...credits exhausted...")`, один вызов.
  - **Контракт-тест** `test_score_schema_matches_doc04_contract()` — JSON-schema `virality_score` (properties `score`,`hook_strength`,`tags`,`reason`, `required`, `additionalProperties:false`) совпадает с doc 04 §2.4 байт-в-байт (защита от дрейфа схемы).
- **Реализация:** перенести sketch из doc 04 §2.6 в `llm/openrouter_adapter.py`; `llm/schemas.py` с константами JSON-схем (`VIRALITY_SCORE_SCHEMA`, `OFFER_MATCH_SCHEMA`); модели/роуты — в `llm/routes.py` (пиннинг слагов на «build-time», не в call-site, doc 04 §2.3). Backoff обернуть так, чтобы тест подменял `time.sleep`.
- **✅ Готово когда:** все 9 тестов зелёные; покрытие адаптера ≥ 80%; manual: `complete_json` с реальным `:free`-ключом (вне CI) возвращает валидный JSON.
- **Commit:** `feat: OpenRouter adapter with json_schema strict + model routing`

🛑 **ЧЕКПОИНТ A:** founder ревьюит выбор моделей по профилям (scoring дёшево / offer_match сильно), формат JSON-схемы scoring, политику fallback/backoff и заголовки атрибуции. Может поменять слаги моделей в `llm/routes.py` и пороги retry до продолжения.

---

### Шаг 2.3 — Swap Gemini → OpenRouter в выборе хайлайтов

- **Цель / DoD:** функция выбора клипов в `engine.py` использует `OpenRouterAdapter.complete_json(profile=SCORING, ...)` вместо Gemini. Транскрипт → строгий JSON `{shorts:[{start,end,title,hook,score}], ...}` (контракт стадии (E) из doc 01 §2). Никаких остаточных импортов `google.generativeai`.
- **Репозитории/команды:** наш код (адаптер из 2.2).
- **Тесты СНАЧАЛА** (`tests/test_highlight_swap.py`):
  - `test_select_highlights_calls_scoring_profile()` — мокнутый `llm_fn`/адаптер вызван с `profile=Profile.SCORING` и JSON-схемой выбора клипов.
  - `test_returns_ranked_clips_sorted_by_score_desc()` — на фиктивном транскрипте адаптер возвращает 3 клипа со score `[40,90,70]` → результат отсортирован `[90,70,40]`.
  - `test_clip_bounds_within_source_duration()` — все `start<end` и `end<=source_duration`; клипы за границей видео отброшены.
  - `test_no_gemini_imports_remain()` — `import ast`-скан `engine.py`: нет `google.generativeai`/`genai`.
  - `test_empty_transcript_yields_no_clips()` — пустой транскрипт → `[]`, без падения.
- **Реализация:** в `engine.py` заменить тело выбора клипов на вызов адаптера со схемой `HIGHLIGHTS_SCHEMA` (`shorts[]` с `start,end,title,hook,score`); сортировка по `score` desc; clamp границ к длительности. Удалить Gemini-клиент и импорты.
- **✅ Готово когда:** 5 тестов зелёные; `grep -r genai services/ai-worker-python/engine` пусто; покрытие изменённого кода ≥ 80%.
- **Commit:** `feat: swap highlight selection from Gemini to OpenRouter scoring`

---

### Шаг 2.4 — CPU-транскрипция (faster-whisper) + golden-фикстура рендера

- **Цель / DoD:** `engine.transcribe()` использует `faster-whisper` (`base`, `device=cpu`, `compute_type=int8`) и отдаёт контракт `word_segments.json` (`[{start,end,words:[{word,start,end}]}]`, doc 01 §2 — **с ведущим пробелом в каждом word** для будущего captacity). Полный CPU-проход `видео → клипы 9:16` отрабатывает на golden-фикстуре. GPU-точный ASD — заглушен (`# PHASE3-GPU`, fallback на MediaPipe/blur-pad из openshorts).
- **Репозитории/команды:** `pip install faster-whisper`; сгенерировать фикстуру (детерминированно, в репо):
  ```bash
  ffmpeg -f lavfi -i testsrc=size=1280x720:rate=25:duration=30 \
         -f lavfi -i sine=frequency=440:duration=30 \
         -c:v libopenh264 -c:a aac -shortest tests/fixtures/sample_30s.mp4
  ```
- **Тесты СНАЧАЛА** (`tests/test_pipeline_golden.py`, harness pytest + ffprobe):
  - `test_transcribe_returns_word_segments_shape()` — на короткой аудио-фикстуре результат соответствует схеме контракта (есть `start/end/words`, каждый `word` начинается с пробела).
  - `test_transcribe_uses_cpu_int8_config()` — `faster_whisper.WhisperModel` сконструирован с `device="cpu", compute_type="int8"` (мок конструктора).
  - `test_pipeline_produces_expected_clip_count()` — полный проход на `sample_30s.mp4` (LLM-выбор замокан → 2 клипа) → ровно 2 выходных файла.
  - `test_clips_are_vertical_1080x1920()` — `ffprobe` каждого выходного клипа → `width==1080 and height==1920`.
  - `test_clip_durations_within_bounds()` — длительность каждого клипа в `[start,end]±0.5с` и `<=180с` (требование Shorts, doc 04 §3.2).
  - `test_clips_ranked_by_score_in_manifest()` — выходной `manifest.json` перечисляет клипы в порядке убывания score (ранжирование сохранено до выхода).
  - `test_asd_gpu_path_is_flagged_not_called()` — путь точного ASD не вызывается в CPU-режиме; помечен флагом `PHASE3_GPU_ASD=False` → используется MediaPipe-fallback.
- **Реализация:** `engine/transcribe.py` (faster-whisper wrapper, ведущий пробел в word), интеграция в `engine.py`; `process_video_to_vertical` оставить openshorts-CPU-путь (MediaPipe FaceDetection + blur-pad), GPU-ветку обернуть `if PHASE3_GPU_ASD:` и оставить `raise NotImplementedError("PHASE3: route to Modal/Replicate")`. Выход — `manifest.json` (ранжированный список клипов + метаданные) + файлы клипов.
- **✅ Готово когда:** 7 тестов зелёные на фикстуре; `ffprobe` подтверждает 1080×1920; manifest ранжирован; покрытие ≥ 80%; manual: глазами проверить один клип проигрывается.
- **Commit:** `feat: faster-whisper CPU transcription + golden vertical-clip pipeline`

🛑 **ЧЕКПОИНТ B:** founder смотрит реальные выходные клипы на фикстуре — длительность, кроп 9:16, качество реврейма, осмысленность ранжирования. Может отрегулировать модель whisper (`base`→`small`), пороги длительности клипа, число клипов до продолжения.

---

### Шаг 2.5 — Python job-runner: контракт стадий + content-hash + Postgres-леджер

- **Цель / DoD:** `services/ai-worker-python/runner.py` — CLI/функция, принимающая JSON-стадию (`{stage, jobId, contentHash, input_uri, ...}`) и выполняющая ОДНУ стадию (`validate|transcode|asr|score|clip|store`), возвращая artifact-ref для следующей. Идемпотентность по `content_hash`: повторный вызов той же стадии с тем же хешем переиспользует результат (через таблицу `pipeline_artifacts`). Это «исполнитель», которого дёргает Node-оркестратор.
- **Репозитории/команды:** `pip install pydantic pg8000` (или psycopg). Схема `upload_ledger` из doc 01 §5.
- **Тесты СНАЧАЛА** (`tests/test_runner_stages.py`, harness pytest + testcontainers Postgres):
  - `test_validate_rejects_non_video()` — мусорный файл → стадия `validate` фейлит с понятной ошибкой (валидация на границе, не «ран»).
  - `test_validate_accepts_fixture()` — `sample_30s.mp4` проходит validate (codec/duration в норме).
  - `test_each_stage_emits_artifact_ref()` — каждая стадия возвращает `{stage, status:"ok", artifact_uri}`.
  - `test_stage_is_idempotent_on_content_hash()` — двойной запуск `asr` с тем же `content_hash` → второй раз НЕ пересчитывает (artifact переиспользован из `pipeline_artifacts`), один и тот же `artifact_uri`.
  - `test_ledger_insert_on_conflict_do_nothing()` — `INSERT ... ON CONFLICT (content_hash) DO NOTHING RETURNING` — повторный content-hash не плодит строк (doc 01 §5).
  - `test_stage_failure_sets_ledger_status_failed()` — упавшая стадия → `upload_ledger.status='failed'`, ошибка залогирована, не проглочена.
- **Реализация:** `runner.py` с диспатчем по `stage`; `ledger.py` (upload_ledger + pipeline_artifacts, миграция в `infra/migrations/`); стадии — тонкие обёртки над `engine.py` функциями; артефакты пишутся в R2 (мок S3 в тестах через `moto`/локальный endpoint) с детерминированным ключом `intermediate/{contentHash}/{stage}.json|.mp4`.
- **✅ Готово когда:** 6 тестов зелёные; идемпотентность доказана; покрытие ≥ 80%.
- **Commit:** `feat: python stage runner with content-hash idempotency + ledger`

---

### Шаг 2.6 — BullMQ Flow-DAG в orchestrator (TS)

- **Цель / DoD:** `services/orchestrator` строит Flow-DAG `validate → transcode → asr → score → clip → store` через `FlowProducer` (children-run-first, doc 01 §5). `jobId = flow:${contentHash}` (дедуп). Воркеры стадий вызывают Python-runner (стадия 2.5) и продвигают состояние. GPU-стадии (`asr`/`score` в продовой топологии) в P2 идут CPU-путём, но уже на отдельных очередях `gpu-asr`/`gpu-score` с `setGlobalConcurrency(2)` + `concurrency:1` (клапан готов для Phase 3).
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/taskforcesh/bullmq.git vendor/bullmq   # референс Flow API
  pnpm add bullmq ioredis
  ```
- **Тесты СНАЧАЛА** (`services/orchestrator/test/flow.int.test.ts`, harness Vitest + testcontainers Redis):
  - `test('flow runs stages in dependency order validate→...→store')` — фейковые-стадии-воркеры пишут timestamp; ассерт порядка: `validate < transcode < asr < score < clip < store`.
  - `test('store waits for clip via waiting-children')` — `store` не стартует, пока `clip` не зарезолвился; `getChildrenValues()` отдаёт artifact-ref.
  - `test('jobId is flow:contentHash and dedupes')` — добавление того же `flow:${hash}` дважды → один flow исполняется (idempotent enqueue).
  - `test('failParentOnFailure aborts flow when transcode fails')` — стадия `transcode` бросает → родитель и `store` НЕ исполняются (doc 01 §5 failure-семантика).
  - `test('gpu queues enforce global concurrency 2')` — на `gpu-asr` поставлено 5 джоб, одновременно активно ≤2 (Redis-enforced потолок).
  - `test('worker invokes python runner per stage')` — мок child-process: воркер `asr` зовёт `runner.py --stage asr` с правильным `contentHash`.
- **Реализация:** `orchestrator/flow.ts` (FlowProducer DAG-сборка), `orchestrator/workers/*.ts` (по воркеру на очередь `transcode|gpu-asr|gpu-score|cpu`), `orchestrator/runnerBridge.ts` (spawn Python-runner, парс stdout-artifact). Очереди и гарды по таблице doc 01 §5. `failParentOnFailure:true` на критичных стадиях.
- **✅ Готово когда:** 6 интеграционных тестов зелёные против реального Redis; порядок/идемпотентность/concurrency-cap доказаны; покрытие ≥ 80%.
- **Commit:** `feat: BullMQ Flow DAG orchestrator (validate→...→store) with gpu concurrency valve`

---

### Шаг 2.7 — SSE-прогресс + Redis pub/sub по jobId

- **Цель / DoD:** воркеры эмитят `job.updateProgress(pct)` и публикуют в Redis pub/sub-канал `progress:${jobId}`; `web` отдаёт SSE-эндпоинт `/api/jobs/[jobId]/stream`, подписанный на канал (а не in-memory EventEmitter — несколько реплик, doc 01 §5). Прогресс джобы виден клиенту в реальном времени.
- **Репозитории/команды:** наш код; `ioredis` (есть).
- **Тесты СНАЧАЛА:**
  - `services/orchestrator/test/progress.int.test.ts` → `test('worker publishes progress to redis channel')` — воркер обновил прогресс на 50 → сообщение `{jobId,pct:50}` пришло в `progress:${jobId}`.
  - `web/test/sse.int.test.ts` → `test('SSE endpoint streams progress events to client')` — публикуем в канал → SSE-ответ содержит `data: {"pct":50}`; `test('SSE works across replicas via pubsub')` — публикация из «другого» соединения доходит (доказывает, что не in-memory).
- **Реализация:** `orchestrator/progress.ts` (publish-обёртка вокруг `updateProgress`), `web/app/api/jobs/[jobId]/stream/route.ts` (SSE + Redis subscribe). Heartbeat-комменты против таймаута прокси.
- **✅ Готово когда:** 3 теста зелёные; pub/sub-кросс-реплика доказан; покрытие ≥ 80%.
- **Commit:** `feat: SSE progress via redis pubsub per jobId`

🛑 **ЧЕКПОИНТ C:** founder проверяет полный DAG end-to-end на фикстуре (без tusd ещё): порядок стадий, идемпотентность по content-hash, прерывание flow при падении стадии, видимый прогресс. Может изменить набор/порядок стадий, retry/attempts на стадию, пороги concurrency до продолжения.

---

### Шаг 2.8 — hook-receiver: tusd post-finish → FlowProducer + идемпотентность

- **Цель / DoD:** `services/hook-receiver` — приватный HTTP-сервис, владеющий `FlowProducer`. На `POST /tusd-hooks` с типом `post-finish` извлекает `Upload-Metadata` (включая `sha256` content-hash, doc 01 §5), делает `INSERT INTO upload_ledger ... ON CONFLICT DO NOTHING RETURNING` и **только если строка создана** — энкьюит `flow:${hash}`; иначе возвращает существующий `result_url` (no-op). tusd hooks не энкьюят BullMQ нативно — этот посредник и есть мост (doc 01 §5).
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/tus/tusd.git vendor/tusd   # референс hook-payload контракта
  pnpm add express
  ```
- **Тесты СНАЧАЛА** (`services/hook-receiver/test/hooks.int.test.ts`, Vitest + testcontainers Redis+Postgres):
  - `test('post-finish hook enqueues flow with content-hash jobId')` — валидный post-finish payload → `flow:${sha256}` появился в очереди `orchestrate`.
  - `test('non post-finish hook types are ignored')` — `pre-create`/`post-receive` → 200, ничего не энкьюится.
  - `test('duplicate content-hash is a no-op (ON CONFLICT)')` — два одинаковых post-finish → один flow, второй ответ содержит existing `result_url`, новых строк леджера нет.
  - `test('missing sha256 metadata triggers server-side hash job')` — payload без `sha256` → энкьюится тонкая `hash`-стадия (стрим R2-объекта), не падение (doc 01 §5).
  - `test('malformed payload returns 400 not 500')` — валидация границы, понятная ошибка.
- **Реализация:** `hook-receiver/server.ts` (express + парс tus hook payload), `hook-receiver/idempotency.ts` (`ON CONFLICT (content_hash) DO NOTHING RETURNING`), `hook-receiver/enqueue.ts` (`flowProducer.add(buildDag(hash))`, реюз 2.6). Привязка приватного домена `:8080/tusd-hooks` (doc 01 §7).
- **✅ Готово когда:** 5 тестов зелёные; идемпотентность по content-hash на уровне HTTP доказана; покрытие ≥ 80%.
- **Commit:** `feat: tusd post-finish hook-receiver → Flow enqueue (content-hash idempotent)`

---

### Шаг 2.9 — tusd-сервис → R2 (resumable multipart)

- **Цель / DoD:** `tusd` развёрнут как сервис, пишет S3-multipart прямо в R2 (`fliphouse-media/ingest/{uploadId}/`), `-hooks-http` указывает на `hook-receiver`. Критично: `-s3-min-part-size == -s3-part-size` (R2-требование, doc 01 §4), подняты до 64 MiB. Реальная resumable-загрузка дробится на части и докачивается после разрыва.
- **Репозитории/команды:** деплой готового образа `tusproject/tusd` (Railway-сервис); конфиг:
  ```bash
  tusd -s3-bucket fliphouse-media -s3-endpoint "$R2_ENDPOINT" \
       -s3-part-size 67108864 -s3-min-part-size 67108864 \
       -hooks-http "http://hook-receiver.railway.internal:8080/tusd-hooks" \
       -hooks-http-forward-headers Upload-Metadata
  ```
- **Тесты СНАЧАЛА** (`infra/test/tusd_upload.int.test.ts`, Vitest + tusd-контейнер + MinIO/локальный S3 как R2-стенд):
  - `test('resumable upload completes and lands object in ingest prefix')` — tus-клиент льёт `sample_30s.mp4` → объект появляется в `ingest/{id}/`.
  - `test('interrupted upload resumes from offset')` — оборвать на 50%, возобновить → финальный объект байт-в-байт равен исходнику (resumability доказана, не «запустилось»).
  - `test('part size equals min part size (R2 invariant)')` — multipart-части (кроме последней) одинакового размера = 64 MiB.
  - `test('post-finish hook fired to receiver on completion')` — по завершении hook-receiver получил `post-finish` с `Upload-Metadata`.
  - `test('Upload-Metadata sha256 is forwarded to hook')` — заголовок проброшен (нужно для идемпотентности 2.8).
- **Реализация:** `infra/tusd/` (Railway config-as-code: env, healthcheck `/metrics`, `replicas:1-3`), wiring приватной сети `tusd → hook-receiver` (doc 01 §7). Тесты гоняют против локального MinIO (R2 S3-совместим).
- **✅ Готово когда:** 5 тестов зелёные; resume и part-size-инвариант доказаны; manual: загрузка через браузерный tus-клиент видна в R2.
- **Commit:** `feat: tusd resumable upload service → R2 with hook forwarding`

🛑 **ЧЕКПОИНТ D:** founder делает реальную загрузку через tusd на staging → проверяет: объект в R2 `ingest/`, hook сработал, `upload_ledger` строка создана, flow заэнкьюен, повторная загрузка тех же байтов = no-op. Может изменить part-size, lifecycle-правила bucket, hook-forwarding до продолжения.

---

### Шаг 2.10 — store-стадия: финальные клипы в R2 + запись в дашборд-модель

- **Цель / DoD:** стадия `store` берёт ранжированные клипы из `clip`, грузит в R2 `clips/{clipId}/` (master.mp4 + poster.jpg), пишет строки в Postgres-таблицу `clips` (jobId, rank, score, duration, width, height, r2_key, poster_key) и проставляет `upload_ledger.status='done'` + `result_url`. Дашборд-API читает эти строки.
- **Репозитории/команды:** `@aws-sdk/client-s3`, `@aws-sdk/s3-request-presigner` (есть).
- **Тесты СНАЧАЛА:**
  - `services/orchestrator/test/store.int.test.ts` → `test('store uploads each clip + poster to clips prefix')`; `test('store writes ranked clip rows to postgres')` — N клипов → N строк, `rank` монотонно растёт при убывании score; `test('store marks ledger done with result_url')`.
  - `web/test/clips-api.int.test.ts` → `test('GET /api/clips/[jobId] returns clips ordered by rank')`; `test('clip rows expose presigned playback url with TTL')` — presigned GET, TTL ~15 мин (doc 01 §4).
- **Реализация:** `orchestrator/workers/store.ts`, миграция `clips`-таблицы, `web/app/api/clips/[jobId]/route.ts` (читает clips, генерит presigned URL server-side). Poster — ffmpeg single-frame extract.
- **✅ Готово когда:** все тесты зелёные; presigned URL играется; ранжирование сохранено до API; покрытие ≥ 80%.
- **Commit:** `feat: store stage uploads ranked clips to R2 + dashboard clips API`

---

### Шаг 2.11 — Дашборд: загрузка → прогресс → ранжированные клипы (web + e2e)

- **Цель / DoD:** в `web` страница `/clips`: tus-аплоадер (uppy/tus-js-client) → SSE-прогресс (2.7) → по `done` рендерит сетку ранжированных клипов 9:16 с превью и плеером (presigned URL из 2.10). Полный продуктовый цикл «видео в → ранжированные клипы 9:16 в дашборде» виден и кликабелен.
- **Репозитории/команды:** `pnpm add tus-js-client @uppy/core @uppy/tus`; e2e — Playwright (есть).
- **Тесты СНАЧАЛА:**
  - Component/unit (Vitest): `test('ClipGrid renders clips sorted by rank')`; `test('progress bar reflects SSE pct')`; `test('clip card shows duration + 9:16 aspect')`.
  - **E2E (Playwright)** `web/e2e/upload-to-clips.spec.ts`:
    - `test('upload sample video yields ranked vertical clips in dashboard')` — загрузить `sample_30s.mp4` через UI → дождаться `done` (детерминированный wait на SSE/статус, не `sleep`) → ассерт: ≥1 клип-карта видима, `data-aspect="9:16"`, клипы в порядке rank.
    - `test('clip player plays a stored clip')` — клик по клипу → `<video>` грузит presigned URL, `readyState>=2`.
    - `test('duplicate upload reuses existing job (no reprocess)')` — повторная загрузка тех же байтов → сразу показывает существующие клипы (идемпотентность видна в UI).
  - Скриншоты breakpoints 320/768/1024/1440 (web testing-rules: visual regression на hero/дашборд).
- **Реализация:** `web/app/(app)/clips/page.tsx`, `web/components/clips/{Uploader,ClipGrid,ClipCard}.tsx`, хук `useJobProgress` (SSE). Семантический HTML, состояния hover/focus, дизайн по doc 02 (не дефолтный шаблон).
- **✅ Готово когда:** unit + 3 e2e зелёные; визуальные скриншоты сняты; manual: реальная загрузка на staging доходит до клипов; покрытие ≥ 80%.
- **Commit:** `feat: clips dashboard — upload, live progress, ranked 9:16 clip grid`

🛑 **ЧЕКПОИНТ E:** founder проходит полный путь руками на staging: загружает реальное длинное видео → видит прогресс → получает ранжированные клипы 9:16, играет их, проверяет идемпотентность повторной загрузки. Это финальная приёмка ядра ценности P2 — может затребовать правки UX/ранжирования/качества клипов перед закрытием фазы.

---

### Шаг 2.12 — bull-board дашборд очередей + наблюдаемость (за auth)

- **Цель / DoD:** `services/bull-board` — read-only дашборд всех очередей (`transcode|gpu-asr|gpu-score|cpu|orchestrate|publish`) за basic-auth (doc 01 §7). Видны активные/упавшие/застрявшие джобы — операционная видимость DAG для отладки P3.
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/felixmosh/bull-board.git vendor/bull-board   # референс
  pnpm add @bull-board/api @bull-board/express
  ```
- **Тесты СНАЧАЛА** (`services/bull-board/test/board.int.test.ts`):
  - `test('board lists all six queues')` — все очереди зарегистрированы.
  - `test('board requires auth (401 without creds)')` — без креды 401 (security-rule: дашборд за auth).
  - `test('failed job is visible in board api')` — упавшая джоба отражена.
- **Реализация:** `bull-board/server.ts` (express + BullMQAdapter на каждую очередь + basic-auth middleware из env). Публичный домен за auth.
- **✅ Готово когда:** 3 теста зелёные; auth-гейт работает; manual: открыть дашборд, увидеть джобы.
- **Commit:** `feat: bull-board read-only queue dashboard behind auth`

---

### Шаг 2.13 — Сквозной интеграционный прогон + coverage-gate фазы

- **Цель / DoD:** один интеграционный тест-оркестратор поднимает весь стек (tusd+MinIO, Redis, Postgres, hook-receiver, orchestrator, ai-worker-python) через testcontainers и гоняет реальную загрузку → клипы. Покрытие по всем новым сервисам ≥ 80%. CI-инвариант safe-zone (doc 01 §2: `1180+420 ≤ 1640`) добавлен как unit-guard на будущий баннер.
- **Репозитории/команды:** наш код; CI-конфиг (`.github/workflows/p2-ci.yml` или Railway-CI).
- **Тесты СНАЧАЛА** (`tests/e2e/full_pipeline.int.test.ts`):
  - `test('end-to-end: tus upload → DAG → ranked clips in db')` — оркеструет реальный стек, ассертит `upload_ledger.status=done` + N строк `clips` ранжированы.
  - `test('idempotent end-to-end: same bytes reuse result_url')`.
  - `test('pipeline fails cleanly on corrupt upload (ledger=failed)')`.
  - `test('safe-zone invariant holds (caption_band ∩ banner = ∅)')` — guard-unit `1180+420==1600 ≤ 1640`.
  - Coverage-aggregator: `pnpm test --coverage` + `pytest --cov` → объединённый отчёт ≥ 80%.
- **Реализация:** `tests/e2e/harness.ts` (compose стека), CI-workflow с gate на coverage и на все сьюты. Документировать запуск в `services/README.md`.
- **✅ Готово когда:** сквозной тест зелёный, идемпотентность и failure покрыты, агрегированное покрытие ≥ 80%, CI настроен и зелёный.
- **Commit:** `test: end-to-end pipeline integration + phase coverage gate`

---

## Выход фазы (Phase exit criteria)

- [ ] **Полный путь работает:** tusd resumable upload → R2 `ingest/` → post-finish hook → BullMQ Flow-DAG `validate→transcode→asr→score→clip→store` → R2 `clips/` → дашборд.
- [ ] **Продуктовый результат виден:** длинное видео на входе → ранжированные вертикальные клипы **1080×1920** на выходе, играются в `/clips`, порядок по score сохранён до UI.
- [ ] **OpenRouter swap завершён:** выбор хайлайтов идёт через `OpenRouterAdapter` (`json_schema strict`, роутинг моделей по doc 04 §2.3); ни одного импорта Gemini/`genai` не осталось; контракт JSON-схемы покрыт тестом.
- [ ] **CPU-транскрипция:** `faster-whisper base/cpu/int8` отдаёт `word_segments` нужной формы (ведущий пробел в word).
- [ ] **Идемпотентность по content-hash:** повторная загрузка тех же байтов = no-op на всех уровнях (HTTP hook `ON CONFLICT`, `jobId=flow:${hash}`, переиспользование артефактов, UI показывает существующие клипы).
- [ ] **GPU-стадии заглушены и помечены:** точный ASD/reframe/inpainting под `# PHASE3-GPU`-флагом (`NotImplementedError` → Modal/Replicate/fal); CPU-fallback (MediaPipe/blur-pad) активен; очереди `gpu-asr`/`gpu-score` уже имеют `setGlobalConcurrency(2)`+`concurrency:1`-клапан.
- [ ] **Failure-семантика:** `failParentOnFailure` валит flow на критичных стадиях; `upload_ledger.status='failed'` при ошибке; ошибки логируются, не проглатываются.
- [ ] **Наблюдаемость:** SSE-прогресс (Redis pub/sub, кросс-реплика) + bull-board за auth.
- [ ] **FFmpeg LGPL-инвариант:** рендер на `libopenh264` (не x264), выход H.264/AAC, `-movflags +faststart` (doc 01 §6) — проверено на golden-фикстуре.
- [ ] **Все 5 чекпоинтов (A–E) пройдены и приняты founder'ом.**
- [ ] **Тесты:** все Vitest/pytest/Playwright-сьюты зелёные; агрегированное покрытие нового кода ≥ 80%; сквозной интеграционный прогон зелёный; CI настроен.
- [ ] **Безопасность:** R2/OpenRouter-креды только в Railway env (не в коде); bull-board за auth; presigned URL server-side с TTL; baseline filtergraph-injection guard (clamp числовых входов) заложен на будущий баннер.
