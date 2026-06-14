# P0 — Bootstrap: монорепо, CI, тест-харнесс, vendor-репозитории

> Фаза-фундамент. Делает возможной founder'скую цель №1 — **ZERO bugs**. Здесь нет продуктовой логики: мы поднимаем pnpm-монорепо, тулинг (TypeScript strict / ESLint / Prettier / Ruff / Black), **полный тест-харнесс up front** (Vitest + Playwright + pytest + coverage-гейты), CI-воркфлоу, который **БЛОКИРУЕТ мёрдж на красных тестах/недоборе покрытия**, и вендорим ВСЕ выбранные upstream-репозитории в `/vendor`, чтобы следующие фазы лифтили код из них. Каждый пакет получает один тривиальный проходящий тест — доказательство, что харнесс работает end-to-end.

---

## Цель фазы (Phase goal)

К концу P0:
1. `pnpm install` в корне поднимает workspace из 4 пакетов: `apps/web`, `apps/worker-node`, `services/ai-worker-python`, `packages/shared`.
2. Каждый пакет имеет **минимум один проходящий тест** на «родном» харнессе (Vitest для TS, pytest для Python, Playwright smoke для web).
3. Coverage-гейт настроен и **роняет** билд при недоборе порога (TS ≥ 80% statements/branches на `packages/shared`; Python ≥ 80% на `services/ai-worker-python`).
4. CI (GitHub Actions) гоняет lint + typecheck + unit + e2e + coverage на каждый PR и **блокирует мёрдж** при красном.
5. `/vendor` содержит склонированные upstream-репы (openshorts, SamurAIGPT-генератор как референс, captacity, LR-ASD, tusd, SaaS-Boilerplate, launch-ui, ai-elements, kibo, shadergradient, cliq), пин по конкретному коммиту, исключённые из своего git-индекса.
6. `STATE.md` и конвенция его обновления существуют; CI проверяет, что `STATE.md` обновлён в PR.

**Никакого бизнес-кода.** Любая нарезка/реврейм/ad-insertion/биллинг — это P1+. Здесь только леса и проверка, что леса держат.

---

## Зависимости (какие фазы должны быть готовы раньше)

- **Нет.** P0 — корневая фаза. Зависит только от установленного локально тулинга (проверено в окружении: `git 2.39`, `node v24`, `pnpm 10.33`, `python 3.11`). Все последующие фазы (P1 клиппинг, P2 ad-banner, P3 inpainting, P4 marketplace, P5 trust) **зависят от P0**.

---

## Репозитории, вендоримые в этой фазе

Все клонируются в `/vendor/<name>` через `git clone --depth 1`, затем пинятся по коммиту и исключаются из основного git (см. Шаг 0.9). URL'ы — ровно те, что выбраны в `docs/01..04`.

| vendor/<name> | URL | Лицензия | Режим | Что лифтим в P1+ |
|---|---|---|---|---|
| `openshorts` | https://github.com/mutonby/openshorts | MIT | lift+edit | `main.py` (engine `transcribe→get_viral_clips→cut→reframe`), `hooks.py:add_hook_to_video`, `fonts/`, `Dockerfile` |
| `samuraigpt-shorts` | https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator | **НЕТ (all rights reserved)** | **reference-only / clean-room** | НЕ копировать код. Только дизайн 8-сигнального virality-фреймворка (`highlights.py`) |
| `captacity` | https://github.com/unconv/captacity | MIT | lift+patch | word-timestamps → MoviePy burn-in; патч `position`/`text_y_offset` под safe-zone |
| `lr-asd` | https://github.com/Junhua-Liao/LR-ASD | проверить при лифте | wrap (не форкать) | `Columbia_test.py` → `tracks.pckl`/`scores.pckl`; пост-процессор `asd_frames.json` (CUDA → на GPU-провайдере) |
| `tusd` | https://github.com/tus/tusd | MIT | lift verbatim (ref) | S3-multipart в R2, `-hooks-http`; деплоится как контейнер в P1 |
| `saas-boilerplate` | https://github.com/ixartz/SaaS-Boilerplate | MIT | lift+extend | Clerk auth, multi-tenant, RBAC, i18n — каркас за лендингом |
| `launch-ui` | https://github.com/launch-ui/launch-ui | MIT | lift sections | `components/sections` (hero, pricing, stats, cta, faq, footer, navbar) |
| `ai-elements` | https://github.com/vercel/ai-elements | Other (commercial-safe) | lift PromptInput | оболочка hero-инпута (textarea + drag-drop + `PromptInputSubmit`) |
| `kibo` | https://github.com/shadcnblocks/kibo | MIT | lift Dropzone | drop-поверхность (`Dropzone`/`DropzoneEmptyState`/`DropzoneContent`) |
| `shadergradient` | https://github.com/ruucm/shadergradient | MIT | lift/ref | анимированный mesh-gradient hero-фон |
| `cliq` | https://github.com/org-quicko/cliq | **НЕТ (all rights reserved)** | **reference-only / clean-room** | НЕ копировать. Только модель Link→Conversion→Commission для P4 |

> Правовая дисциплина (из `docs/00`/`01`): `samuraigpt-shorts` и `cliq` — **без лицензии** → код вендорим как референс, в прод не лифтим, реимплементируем clean-room. Остальные — permissive, лифтим. `magicui`/`motion-primitives` и т.п. подтягиваются через `shadcn`/`npm` в P-фазах дизайна, не клонируются здесь (Шаг 0.10 фиксирует это решение).

---

## Чеклист чекпоинтов фазы

- 🛑 **ЧЕКПОИНТ A** (после Шаг 0.2) — структура монорепо и корневой тулинг-контракт.
- 🛑 **ЧЕКПОИНТ B** (после Шаг 0.5) — `packages/shared` зелёный на Vitest + coverage-гейт реально роняет билд.
- 🛑 **ЧЕКПОИНТ C** (после Шаг 0.7) — Python ai-worker зелёный на pytest + golden-fixture контракт для будущего рендера.
- 🛑 **ЧЕКПОИНТ D** (после Шаг 0.8) — web Playwright smoke зелёный, worker-node Vitest зелёный.
- 🛑 **ЧЕКПОИНТ E** (после Шаг 0.9) — `/vendor` со всеми репами, пины зафиксированы, vendor исключён из git.
- 🛑 **ЧЕКПОИНТ F** (после Шаг 0.11) — CI блокирует красный PR; gate проверен на заведомо падающем коммите.

---

## Глобальные правила фазы (применяются к КАЖДОМУ шагу)

- **TDD обязателен** (правило founder'а №1). Каждый шаг: (1) написать падающий тест с точным именем и assertion'ом → (2) запустить → **RED** → (3) минимальная реализация → (4) запустить → **GREEN** → (5) рефактор → (6) **один git-commit**. Шаг не «done», пока тесты не зелёные И coverage-гейт держится.
- **Один шаг = один атомарный коммит.** Формат коммита: `<type>: <message>` (feat/chore/test/ci/docs).
- **Иммутабельность и мелкие файлы** (см. coding-style): 200–400 строк типично, 800 max.
- **STATE.md** обновляется в КАЖДОМ шаге (Шаг 0.0 заводит конвенцию).
- Все команды запускать из корня репо `/Users/mishanikhinkirtill/Desktop/FlipHouse`, если не сказано иное.

---

## Шаг 0.0 — Инициализация git-репо и STATE.md-конвенция

- **Цель / DoD:** В корне есть git-репо, `STATE.md` с разделами и явной конвенцией обновления, и `scripts/check-state-updated.sh`, который в CI убедится, что PR трогает `STATE.md`. Конвенция: каждый завершённый шаг дописывает строку в таблицу «Журнал шагов» (`phase.step | commit-type | дата | что сделано | тесты зелёные?`).
- **Репозитории/команды:**
  ```bash
  cd /Users/mishanikhinkirtill/Desktop/FlipHouse
  git init -b main
  ```
- **Тесты СНАЧАЛА (харнесс: bash + node):**
  - Создать `scripts/__tests__/check-state-updated.test.mjs` (node:test):
    - `test('check-state-updated exits 0 when STATE.md is among changed files')` — вызвать скрипт с подменённым списком файлов, содержащим `STATE.md`, assert exit code `0`.
    - `test('check-state-updated exits 1 when STATE.md missing from changed files')` — список без `STATE.md`, assert exit code `1` и stderr содержит `STATE.md not updated`.
  - Запустить `node --test scripts/__tests__/check-state-updated.test.mjs` → **RED** (скрипта нет).
- **Реализация:**
  - `STATE.md` с разделами: `## Текущая фаза`, `## Журнал шагов` (таблица), `## Открытые риски`, `## Следующий шаг`. Описать конвенцию обновления в шапке.
  - `scripts/check-state-updated.sh`: принимает список изменённых файлов из аргумента/`$CHANGED_FILES`, grep по `^STATE.md$`, exit `0`/`1` с понятным stderr.
  - `.gitignore` (node_modules, .venv, dist, .next, coverage, vendor/* кроме pin-файла — финализируется в Шаг 0.9).
- **✅ Готово когда:** оба node-теста зелёные; `STATE.md` существует с заполненным первым рядом журнала; ручная проверка `bash scripts/check-state-updated.sh "STATE.md\nfoo.ts"` → exit 0, `bash scripts/check-state-updated.sh "foo.ts"` → exit 1.
- **Commit:** `chore: init git repo + STATE.md convention with CI guard test`

---

## Шаг 0.1 — Каркас pnpm workspace + корневой package.json

- **Цель / DoD:** `pnpm-workspace.yaml` объявляет `apps/*`, `services/*`, `packages/*`. Корневой `package.json` с pinned `packageManager: "pnpm@10.33.2"`, `engines.node >=24`, и npm-скриптами-агрегаторами (`lint`, `typecheck`, `test`, `test:e2e`, `coverage`) через `pnpm -r`. `pnpm install` проходит с пустыми пакетами-плейсхолдерами.
- **Репозитории/команды:** нет клонов; только `pnpm`.
- **Тесты СНАЧАЛА (харнесс: node:test):**
  - `scripts/__tests__/workspace-shape.test.mjs`:
    - `test('pnpm-workspace.yaml lists apps, services, packages globs')` — распарсить yaml, assert массив `packages` включает `apps/*`, `services/*`, `packages/*`.
    - `test('root package.json pins pnpm and node engine')` — assert `packageManager` начинается с `pnpm@` и `engines.node` присутствует.
    - `test('root package.json exposes aggregate scripts')` — assert наличие ключей `lint`,`typecheck`,`test`,`test:e2e`,`coverage`.
  - Запустить → **RED**.
- **Реализация:** `pnpm-workspace.yaml`, корневой `package.json` (private), 4 пустых директории с минимальным `package.json` (`apps/web`, `apps/worker-node`, `services/ai-worker-python` — здесь только маркер, реальный python-тулинг в 0.6, `packages/shared`).
- **✅ Готово когда:** 3 теста зелёные; `pnpm install` без ошибок; `pnpm -r exec true` проходит по всем пакетам.
- **Commit:** `chore: scaffold pnpm workspace with aggregate scripts`

---

## Шаг 0.2 — Корневой TypeScript strict + ESLint + Prettier

- **Цель / DoD:** Базовый `tsconfig.base.json` (strict-набор: `strict`, `noUncheckedIndexedAccess`, `noImplicitOverride`, `exactOptionalPropertyTypes`, `verbatimModuleSyntax`), корневой ESLint flat-config (`typescript-eslint`, import-order), Prettier-конфиг. `pnpm typecheck`/`pnpm lint` работают и **ловят** заведомо плохой код.
- **Репозитории/команды:**
  ```bash
  pnpm add -Dw typescript @types/node eslint @eslint/js typescript-eslint prettier eslint-config-prettier eslint-plugin-import vitest @vitest/coverage-v8
  ```
- **Тесты СНАЧАЛА (харнесс: Vitest + фикстуры-файлы):**
  - `tooling/__tests__/lint-config.test.ts`:
    - `test('eslint flags an unused variable in a fixture file')` — прогнать ESLint API по фикстуре `tooling/__fixtures__/bad-unused.ts`, assert ≥1 ошибка с `ruleId` содержащим `no-unused-vars`.
    - `test('tsconfig.base enables strict and noUncheckedIndexedAccess')` — прочитать JSON, assert `compilerOptions.strict===true` и `noUncheckedIndexedAccess===true`.
  - Запустить `pnpm vitest run tooling` → **RED**.
- **Реализация:** `tsconfig.base.json`, `eslint.config.mjs`, `.prettierrc.json`, `vitest.config.ts` (корневой, projects-aware). Фикстура `bad-unused.ts` намеренно с unused var, помечена в eslintignore-исключении только для тестового прогона через API (не глобальный lint).
- **✅ Готово когда:** оба теста зелёные; `pnpm lint` чистый на реальном коде; ручная проверка: добавить `const x: number = "s"` во временный файл → `pnpm typecheck` падает → откатить.
- 🛑 **ЧЕКПОИНТ A:** Founder ревьюит структуру монорепо (`apps/web`, `apps/worker-node`, `services/ai-worker-python`, `packages/shared`), строгость TS, набор корневых скриптов. Может изменить имена пакетов/строгость до того, как на это лягут все остальные шаги.
- **Commit:** `chore: root TS strict + ESLint flat + Prettier with config guard tests`

---

## Шаг 0.3 — `packages/shared`: пакет + первый Vitest-юнит-тест

- **Цель / DoD:** `packages/shared` — публикуемый внутренний TS-пакет (`@fliphouse/shared`) с реальной чистой утилитой, которая понадобится всем (content-hash helper — он же PK/jobId в архитектуре, см. `docs/01 §5`). Vitest-юнит зелёный.
- **Репозитории/команды:** нет клонов.
- **Тесты СНАЧАЛА (харнесс: Vitest):**
  - `packages/shared/src/hash/content-hash.test.ts`:
    - `test('sha256Hex returns deterministic 64-char lowercase hex for given bytes')` — вход `Uint8Array` из `"fliphouse"`, assert длина 64, `/^[0-9a-f]{64}$/`, и стабильность между двумя вызовами.
    - `test('sha256Hex differs for different inputs')` — два разных буфера → разные хеши.
    - `test('jobIdFromHash prefixes hash with flow:')` — assert `jobIdFromHash(h) === "flow:" + h` (контракт из `docs/01 §5`).
  - Запустить `pnpm --filter @fliphouse/shared test` → **RED**.
- **Реализация:** `packages/shared/package.json` (`type: module`, exports map, build через `tsc`), `tsconfig.json` extends base, `src/hash/content-hash.ts` (`sha256Hex`, `jobIdFromHash`) на `node:crypto`, `src/index.ts` реэкспорт.
- **✅ Готово когда:** 3 теста зелёные; `pnpm --filter @fliphouse/shared build` собирает `dist`; ручная проверка хеша против `printf fliphouse | shasum -a 256`.
- **Commit:** `feat(shared): content-hash + jobId helpers with unit tests`

---

## Шаг 0.4 — Coverage-гейт на `packages/shared` (порог 80%, должен РОНЯТЬ билд)

- **Цель / DoD:** Vitest coverage (v8) настроен с `thresholds` (statements/branches/functions/lines = 80) на `packages/shared`. Доказать, что недобор реально роняет процесс (exit ≠ 0), а не просто печатает варнинг.
- **Репозитории/команды:** уже установлен `@vitest/coverage-v8`.
- **Тесты СНАЧАЛА (харнесс: Vitest + sub-process assertion):**
  - `packages/shared/src/__meta__/coverage-gate.test.ts`:
    - `test('coverage run fails when an uncovered exported function is added')` — спавнить `pnpm --filter @fliphouse/shared coverage` в фикстуре с временным экспортом `uncovered()` (без теста), assert exit code ≠ 0 и stdout содержит `ERROR: Coverage` / `threshold`. Чистить фикстуру в `afterEach`.
  - `test('coverage run passes on the real fully-tested module')` — без фикстуры, assert exit 0.
  - Запустить → **RED** (нет конфигурации thresholds).
- **Реализация:** добавить в `packages/shared/vitest.config.ts` блок `test.coverage` с `provider: 'v8'`, `thresholds`, `include: ['src/**']`, `exclude` для `**/*.test.ts` и `__meta__`. Скрипт `coverage` в `package.json` пакета.
- **✅ Готово когда:** оба теста зелёные; «падающий» прогон действительно exit≠0; ручная проверка: удалить один из тестов хеша → `coverage` падает → вернуть тест.
- 🛑 **ЧЕКПОИНТ B:** Founder убеждается, что **тест-харнесс работает end-to-end и gate реально блокирует** на недоборе покрытия (видит exit-code-доказательство). Может скорректировать порог (80 → 85/90) до распространения паттерна на остальные пакеты.
- **Commit:** `test(shared): enforce 80% coverage gate with proof-of-failure test`

---

## Шаг 0.5 — Корневой aggregate `pnpm test`/`coverage` через Vitest projects

- **Цель / DoD:** Корневой `pnpm test` гоняет все TS-пакеты одной командой (Vitest workspace/projects), `pnpm coverage` агрегирует. Добавление нового TS-пакета авто-подхватывается.
- **Тесты СНАЧАЛА (харнесс: node:test над выводом Vitest):**
  - `scripts/__tests__/aggregate-test.test.mjs`:
    - `test('root pnpm test discovers and runs shared package tests')` — спавнить `pnpm test`, assert stdout упоминает `content-hash` и `0 failed`.
    - `test('vitest projects config includes packages and apps globs')` — распарсить корневой `vitest.config.ts`/`vitest.workspace.ts`, assert наличие globs `packages/*` и `apps/*`.
  - Запустить → **RED**.
- **Реализация:** `vitest.workspace.ts` (или `test.projects` в корневом конфиге) со списком `['packages/*', 'apps/*/vitest.config.ts']`. Корневые скрипты `test`/`coverage` → `vitest run`.
- **✅ Готово когда:** оба теста зелёные; `pnpm test` из корня прогоняет shared; `pnpm coverage` печатает агрегат и держит гейт.
- **Commit:** `chore: aggregate vitest projects at workspace root`

---

## Шаг 0.6 — `services/ai-worker-python`: окружение + Ruff/Black + pytest-каркас

- **Цель / DoD:** Python-пакет с `pyproject.toml` (PEP 621), `.venv`, Ruff (lint+isort) и Black настроены, pytest + `pytest-cov` с порогом 80%. Один реальный юнит-тест на чистую утилиту, которая нужна рендер-пайплайну (safe-zone инвариант из `docs/01 §2`: `caption_band ⊂ content_safe` и `caption_band ∩ banner = ∅`).
- **Репозитории/команды:**
  ```bash
  cd services/ai-worker-python
  python3 -m venv .venv && . .venv/bin/activate
  pip install -U pip
  pip install pytest pytest-cov ruff black
  pip freeze > requirements-dev.txt
  ```
- **Тесты СНАЧАЛА (харнесс: pytest):**
  - `services/ai-worker-python/tests/test_safe_zones.py`:
    - `test_caption_band_within_content_safe()` — `validate_safe_zones(content_safe=(0,1080,0,1920), caption_band=(0,1080,1180,1600), banner=(0,1080,1640,1920))` → `True`.
    - `test_caption_band_overlapping_banner_is_rejected()` — `caption_band` пересекает `banner` → `ValueError`/`False` (инвариант `1180+420=1600 ≤ 1640`).
    - `test_caption_band_outside_content_safe_is_rejected()` — band вне content_safe → reject.
  - Запустить `pytest` → **RED**.
- **Реализация:** `pyproject.toml` (`[tool.ruff]`, `[tool.black]`, `[tool.pytest.ini_options]` с `--cov=fliphouse_worker --cov-fail-under=80`), пакет `fliphouse_worker/safe_zones.py` с `validate_safe_zones(...)`, `fliphouse_worker/__init__.py`.
- **✅ Готово когда:** 3 теста зелёные; `ruff check .` и `black --check .` чистые; `pytest` печатает coverage ≥80%; ручная проверка: убрать тест → `--cov-fail-under` роняет pytest.
- **Commit:** `feat(ai-worker): python env + safe-zone validator with pytest coverage gate`

---

## Шаг 0.7 — Golden-fixture контракт для будущего рендер-пайплайна (FFmpeg-aware)

- **Цель / DoD:** Завести в Python-воркере **контракт ассертов на выходное видео** (длительность/размеры/частота кадров/хеш кадра/наличие оверлея), чтобы P1/P2 проверяли рендер, а не «отработало без ошибок» (требование founder'а). В P0 пайплайна нет — поэтому генерим крошечный детерминированный клип через FFmpeg `lavfi` и проверяем сам **харнесс ассертов** на нём.
- **Репозитории/команды:**
  - Требуется `ffmpeg`/`ffprobe` в PATH (P1 заменит на собранный LGPL-образ из `docs/01 §6`; в P0 — системный для проверки харнесса). Если нет — `brew install ffmpeg`.
  ```bash
  cd services/ai-worker-python && . .venv/bin/activate
  pip install imagehash pillow && pip freeze > requirements-dev.txt
  ```
- **Тесты СНАЧАЛА (харнесс: pytest + ffmpeg-генерация фикстуры):**
  - `services/ai-worker-python/tests/test_video_asserts.py` (фикстура `make_test_clip` генерит `testsrc=size=1080x1920:rate=24:duration=1` в `tmp_path`):
    - `test_assert_dimensions_matches_vertical_1080x1920()` — `probe_dimensions(clip) == (1080, 1920)`.
    - `test_assert_duration_within_tolerance()` — `assert_duration(clip, expected=1.0, tol=0.05)` не кидает.
    - `test_assert_fps_is_24()` — `probe_fps(clip) == 24`.
    - `test_frame_phash_is_stable_across_two_extractions()` — `frame_phash(clip, t=0.5)` детерминирован между двумя вызовами (perceptual hash, расстояние 0).
    - `test_detects_overlay_presence_via_pixel_region()` — наложить через ffmpeg белый бокс в banner-зоне, `region_has_content(clip, region=banner)` → `True`; на чистом клипе → `False`.
  - Запустить `pytest tests/test_video_asserts.py` → **RED**.
- **Реализация:** `fliphouse_worker/video_asserts.py` — обёртки над `ffprobe` (JSON-парс) и `PIL`/`imagehash` для кадра; `probe_dimensions`, `probe_fps`, `assert_duration`, `frame_phash`, `region_has_content`. Фикстура-генератор в `tests/conftest.py`.
- **✅ Готово когда:** все 5 тестов зелёные; coverage держится ≥80%; ручная проверка: `ffprobe` фикстуры подтверждает 1080x1920@24.
- 🛑 **ЧЕКПОИНТ C:** Founder ревьюит **golden-video контракт** — именно на нём P1/P2 будут гарантировать «нулевые баги» рендера (реврейм даёт 9:16, ad-banner реально в кадре, субтитры присутствуют). Может расширить набор ассертов (audio-track, bitrate, keyframe-interval) до начала P1.
- **Commit:** `test(ai-worker): golden-file video assertion harness (dims/duration/fps/phash/overlay)`

---

## Шаг 0.8 — `apps/web` (Next.js skeleton) + Playwright smoke; `apps/worker-node` + Vitest

- **Цель / DoD:** Минимальный `apps/web` (Next.js 16 / React 19, как в `docs/02`) с `/api/health` (healthcheck из `docs/01 §7`) и тривиальной главной. Playwright e2e smoke зелёный. Минимальный `apps/worker-node` (будущий BullMQ-оркестратор) с Vitest-юнитом на чистую утилиту (queue-name резолвер из `docs/01 §5`).
- **Репозитории/команды:**
  ```bash
  pnpm --filter web add next@latest react@latest react-dom@latest
  pnpm --filter web add -D @playwright/test
  pnpm --filter web exec playwright install --with-deps chromium
  pnpm --filter @fliphouse/worker-node add bullmq ioredis
  ```
- **Тесты СНАЧАЛА:**
  - **web (Playwright e2e):** `apps/web/e2e/smoke.spec.ts`:
    - `test('landing page renders an h1')` — `page.goto('/')`, `expect(page.locator('h1')).toBeVisible()` (форма из web/testing.md).
    - `test('GET /api/health returns 200 with status ok')` — `request.get('/api/health')`, assert `status()===200` и JSON `{status:'ok'}`.
  - **web (Vitest unit, опц. но желательно):** `apps/web/src/lib/health.test.ts` — `buildHealthPayload()` возвращает `{status:'ok', service:'web'}`.
  - **worker-node (Vitest):** `apps/worker-node/src/queues/queue-name.test.ts`:
    - `test('resolveQueue maps transcode stage to cpu queue')` и `test('resolveQueue maps asr stage to gpu-asr queue')` — по таблице очередей `docs/01 §5`.
  - Запустить Playwright + Vitest → **RED**.
- **Реализация:** `apps/web` App Router (`app/page.tsx` с `<h1>FlipHouse</h1>`, `app/api/health/route.ts`), `playwright.config.ts` (webServer: `next dev`/`next start`, baseURL). `apps/worker-node/src/queues/queue-name.ts` (`resolveQueue(stage)`), его `package.json` + `tsconfig` + `vitest.config.ts`.
- **✅ Готово когда:** Playwright smoke зелёный (оба теста), worker-node Vitest зелёный, web Vitest зелёный; `pnpm --filter web build` проходит; coverage worker-node ≥80%.
- 🛑 **ЧЕКПОИНТ D:** Founder проверяет, что **все три TS-харнесса** работают: web Playwright e2e, web unit, worker-node unit. Может поменять Next-версию/структуру `app/`, имена очередей до того, как P1 начнёт лить BullMQ-флоу.
- **Commit:** `feat(web,worker-node): next skeleton + health route + playwright smoke + queue resolver`

---

## Шаг 0.9 — Вендоринг ВСЕХ upstream-репозиториев в `/vendor` + пины

- **Цель / DoD:** `/vendor` содержит все 11 репозиториев, каждый запинен по конкретному коммиту в `vendor/PINS.lock` (имя → URL → SHA → лицензия → режим). `vendor/**` исключён из git основного репо (мы не форкаем их историю), но `vendor/PINS.lock` и `vendor/README.md` — коммитятся. Тест проверяет, что каждый ожидаемый репо реально склонирован и пины валидны.
- **Репозитории/команды (точные, runnable):**
  ```bash
  cd /Users/mishanikhinkirtill/Desktop/FlipHouse
  mkdir -p vendor

  # --- Python clipping/render engine (lift+edit) ---
  git clone --depth 1 https://github.com/mutonby/openshorts.git vendor/openshorts
  # --- Virality framework (REFERENCE-ONLY, no license, clean-room) ---
  git clone --depth 1 https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator.git vendor/samuraigpt-shorts
  # --- Karaoke captions (lift+patch) ---
  git clone --depth 1 https://github.com/unconv/captacity.git vendor/captacity
  # --- Active Speaker Detection (wrap, CUDA → GPU provider) ---
  git clone --depth 1 https://github.com/Junhua-Liao/LR-ASD.git vendor/lr-asd
  # --- Resumable upload edge (lift verbatim / ref) ---
  git clone --depth 1 https://github.com/tus/tusd.git vendor/tusd
  # --- SaaS skeleton behind landing (lift+extend) ---
  git clone --depth 1 https://github.com/ixartz/SaaS-Boilerplate.git vendor/saas-boilerplate
  # --- Landing shell sections (lift sections) ---
  git clone --depth 1 https://github.com/launch-ui/launch-ui.git vendor/launch-ui
  # --- Hero prompt-input wrapper (lift PromptInput) ---
  git clone --depth 1 https://github.com/vercel/ai-elements.git vendor/ai-elements
  # --- Dropzone surface (lift Dropzone) ---
  git clone --depth 1 https://github.com/shadcnblocks/kibo.git vendor/kibo
  # --- WebGL mesh-gradient hero bg (lift/ref) ---
  git clone --depth 1 https://github.com/ruucm/shadergradient.git vendor/shadergradient
  # --- Marketplace attribution model (REFERENCE-ONLY, no license, clean-room) ---
  git clone --depth 1 https://github.com/org-quicko/cliq.git vendor/cliq

  # Записать пины (SHA каждого HEAD) — генерится скриптом scripts/write-vendor-pins.mjs
  node scripts/write-vendor-pins.mjs > vendor/PINS.lock
  ```
- **Тесты СНАЧАЛА (харнесс: node:test):**
  - `scripts/__tests__/vendor-pins.test.mjs`:
    - `test('all 11 expected vendor repos are present as directories')` — массив ожидаемых имён (`openshorts`,`samuraigpt-shorts`,`captacity`,`lr-asd`,`tusd`,`saas-boilerplate`,`launch-ui`,`ai-elements`,`kibo`,`shadergradient`,`cliq`), assert каждая `vendor/<name>/.git` существует.
    - `test('PINS.lock has a 40-hex SHA, url and license for every vendor')` — распарсить `vendor/PINS.lock`, assert каждая запись `/^[0-9a-f]{40}$/` SHA + непустой url + поле license.
    - `test('no-license vendors are marked reference-only')` — assert `samuraigpt-shorts` и `cliq` имеют `mode=reference-only` и `license=NONE`.
  - Запустить → **RED**.
- **Реализация:** `scripts/write-vendor-pins.mjs` (читает каждый `vendor/<name>`, `git rev-parse HEAD`, мапит URL/лицензию/режим из таблицы), `vendor/README.md` (правовая дисциплина: что лифтим verbatim, что clean-room). Финализировать `.gitignore`: `vendor/*` + `!vendor/PINS.lock` + `!vendor/README.md`.
- **✅ Готово когда:** 3 теста зелёные; `git status` показывает, что только `vendor/PINS.lock`/`vendor/README.md` трекаются (не сами клоны); ручная проверка: `cat vendor/PINS.lock` — 11 строк с SHA.
- 🛑 **ЧЕКПОИНТ E:** Founder ревьюит `vendor/PINS.lock` и `vendor/README.md` — **полнота набора репозиториев и правовая разметка** (verbatim vs reference-only). Может добавить/убрать репо или сменить пин до того, как P1 начнёт лифтить `openshorts/main.py`.
- **Commit:** `chore: vendor all upstream repos into /vendor with pinned SHAs and license map`

---

## Шаг 0.10 — Зафиксировать решение по npm/shadcn-вендорингу (ADR + проверочный тест)

- **Цель / DoD:** Дизайн-либы, которые ставятся не через `git clone`, а через пакет/CLI (`magicui`, `motion`/`motion-primitives`, `aceternity`, `lenis`, `gsap`, `style-dictionary`, `serwist`), зафиксированы в ADR-документе с **точными командами установки** из `docs/02`/`docs/04`, чтобы P-фазы дизайна не выдумывали источник заново. Тест валидирует, что ADR содержит ожидаемые команды.
- **Репозитории/команды (документируются, не выполняются в P0):**
  ```bash
  # из docs/02 §3.1 — hero/atmosphere
  npx ai-elements add prompt-input
  npx kibo-ui add dropzone
  npm i @shadergradient/react @react-three/fiber three
  npm i motion
  # из docs/02 §6 — motion/scroll/tokens
  npm i lenis gsap
  npm i -D style-dictionary
  # из docs/04 §1.4 — PWA
  npm i @serwist/next web-push && npm i -D serwist @types/web-push
  ```
- **Тесты СНАЧАЛА (харнесс: node:test):**
  - `docs/adr/__tests__/adr-design-deps.test.mjs`:
    - `test('ADR-0001 lists ai-elements, kibo, shadergradient, motion install commands')` — grep по `docs/adr/0001-design-dependency-sources.md`, assert наличие каждой из строк команд.
    - `test('ADR-0001 marks paper-design/shaders and whatamesh as avoided')` — assert упоминание «avoid»/«избегать» для `paper-design/shaders` (PolyForm) и `whatamesh` (no license), как в `docs/02 §2.4`.
  - Запустить → **RED**.
- **Реализация:** `docs/adr/0001-design-dependency-sources.md` — таблица «как ставим» (git clone в vendor vs npm/CLI), список avoided-репов с причиной.
- **✅ Готово когда:** оба теста зелёные; ADR читается и однозначно говорит, откуда берётся каждая дизайн-зависимость.
- **Commit:** `docs: ADR-0001 design dependency sources + avoidance list`

---

## Шаг 0.11 — CI-воркфлоу (GitHub Actions), БЛОКИРУЮЩИЙ красные тесты/покрытие

- **Цель / DoD:** `.github/workflows/ci.yml` гоняет на каждый PR/`push`: install → lint (ESLint+Ruff+Black) → typecheck → `pnpm test` + coverage-гейт → pytest + cov-гейт → Playwright e2e → проверку `STATE.md` (Шаг 0.0). Job помечен required (через branch protection — документируется). Доказать, что заведомо красный коммит **роняет** workflow локально через `act` или через скрипт-симулятор пайплайна.
- **Репозитории/команды:**
  ```bash
  # локальная симуляция CI без облака:
  pnpm install --frozen-lockfile
  pnpm lint && pnpm typecheck && pnpm coverage
  pnpm --filter web exec playwright test
  ( cd services/ai-worker-python && . .venv/bin/activate && ruff check . && black --check . && pytest )
  ```
- **Тесты СНАЧАЛА (харнесс: node:test над скриптом-оркестратором CI):**
  - Вынести пайплайн в `scripts/ci-local.sh` (последовательность шагов, `set -e`).
  - `scripts/__tests__/ci-pipeline.test.mjs`:
    - `test('ci-local.sh runs lint, typecheck, coverage, pytest, e2e and state-check in order')` — распарсить скрипт, assert наличие и порядок ключевых шагов.
    - `test('ci fails fast when a TS test is red')` — во временной ветке/фикстуре сломать один shared-тест, спавнить `scripts/ci-local.sh`, assert exit≠0 и что Playwright-шаг НЕ достигнут (fail-fast). Восстановить.
    - `test('workflow yaml triggers on pull_request and runs ci-local steps')` — распарсить `.github/workflows/ci.yml`, assert `on.pull_request` присутствует и job вызывает те же шаги.
  - Запустить → **RED**.
- **Реализация:** `scripts/ci-local.sh` (single source of truth для шагов), `.github/workflows/ci.yml` (matrix: node-job + python-job; кэш pnpm/pip; `playwright install`; вызывает те же команды что `ci-local.sh`; финальный шаг — `scripts/check-state-updated.sh` на `git diff --name-only origin/main...HEAD`). `docs/ci/branch-protection.md` — инструкция сделать job required.
- **✅ Готово когда:** все 3 теста зелёные; `bash scripts/ci-local.sh` зелёный на чистом дереве; ручная проверка: сломать тест → `ci-local.sh` exit≠0 до e2e → откатить; `act -j ci` (если установлен) повторяет результат.
- 🛑 **ЧЕКПОИНТ F:** Founder подтверждает, что **CI блокирует красный PR** (видит fail-fast-доказательство и yaml), и включает branch protection (job required) на `main`. Это финальный гейт «нулевых багов»: с этого момента ничего красное не вливается.
- **Commit:** `ci: blocking PR workflow (lint+typecheck+coverage+pytest+e2e+state) with fail-fast proof`

---

## Шаг 0.12 — README + onboarding-скрипт `setup.sh` + финальная сверка STATE.md

- **Цель / DoD:** Корневой `README.md` (как поднять монорепо с нуля), `scripts/setup.sh` (idempotent: `pnpm install` + python venv + `playwright install` + клон vendor если отсутствует), и `STATE.md` отражает завершение P0 и «Следующий шаг → P1 клиппинг-движок».
- **Тесты СНАЧАЛА (харнесс: node:test):**
  - `scripts/__tests__/setup-idempotent.test.mjs`:
    - `test('setup.sh is idempotent — second run does not re-clone existing vendor repos')` — мокнуть наличие `vendor/openshorts`, прогнать `setup.sh --dry-run`, assert вывод содержит `skip` для существующих репо.
    - `test('STATE.md marks P0 complete and points to P1')` — assert `STATE.md` содержит `P0` со статусом complete и `Следующий шаг` упоминает `P1`.
  - Запустить → **RED**.
- **Реализация:** `scripts/setup.sh` (с `--dry-run`), `README.md` (quickstart, структура, как гонять тесты), финальный апдейт `STATE.md`.
- **✅ Готово когда:** оба теста зелёные; `bash scripts/setup.sh --dry-run` на чистой машине печатает корректный план; полный `pnpm test` + pytest + e2e зелёные из коробки после `setup.sh`.
- **Commit:** `docs: onboarding README + idempotent setup.sh + finalize P0 STATE`

---

## Выход фазы (Phase exit criteria)

Чеклист — всё ДОЛЖНО быть отмечено, иначе P1 не стартует:

- [ ] `pnpm install` из корня поднимает workspace из 4 пакетов без ошибок.
- [ ] `packages/shared` — Vitest зелёный, coverage-гейт ≥80% **роняет** билд при недоборе (доказано тестом в 0.4).
- [ ] `services/ai-worker-python` — pytest зелёный, `--cov-fail-under=80` активен, Ruff+Black чистые.
- [ ] Golden-video assertion-харнесс (dims/duration/fps/phash/overlay) зелёный — контракт для P1/P2 рендера готов.
- [ ] `apps/web` — Playwright e2e smoke зелёный (`h1` + `/api/health` 200), `next build` проходит.
- [ ] `apps/worker-node` — Vitest зелёный (queue-resolver), coverage ≥80%.
- [ ] Корневой `pnpm test`/`pnpm coverage` агрегируют все TS-пакеты.
- [ ] `/vendor` содержит все 11 репозиториев; `vendor/PINS.lock` с 40-hex SHA + лицензией + режимом на каждый; `samuraigpt-shorts` и `cliq` помечены `reference-only/NONE`; сами клоны исключены из git.
- [ ] ADR-0001 фиксирует источники дизайн-зависимостей (npm/shadcn vs vendor) и avoided-репозитории.
- [ ] CI (`.github/workflows/ci.yml`) гоняет lint+typecheck+coverage+pytest+e2e+state-check на PR и **блокирует** красный (доказано fail-fast тестом в 0.11); branch protection включён.
- [ ] `STATE.md` обновлялся на каждом шаге; CI-гард `check-state-updated.sh` активен; финал отмечает P0 complete → P1 next.
- [ ] `scripts/setup.sh --dry-run` idempotent; `README.md` описывает quickstart.

**Итог:** леса стоят, харнесс держит, vendor-код на месте — фундамент для «нулевых багов» в P1+.
