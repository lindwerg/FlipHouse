# P1 — Веб-каркас: auth, биллинг, лендинг с hero-дропзоной

> Фаза 1 «продуктовой оболочки» FlipHouse. Форкаем `ixartz/SaaS-Boilerplate` (Next.js App Router + Clerk auth + Postgres/Drizzle); биллинг — за **vendor-нейтральной абстракцией `PaymentProvider`**, конкрет-реализация — **свой on-chain приёмник USDT TRC-20** (HD-кошелёк + свой TRON-узел/TronGrid + `tronweb`; без чужого процессора — никто не блокирует; Stripe/ЮKassa убраны). Монетизация — **PAYG ($0.25/мин, ~90% маржи) + подписка креатора** с лимитом минут (Старт $9/Актив $24/Студия $59, выверено против Opus Clip). Строим Lovable-style лендинг с центрированной hero-дропзоной (Kibo Dropzone + AI Elements PromptInput над shadergradient WebGL-mesh), добавляем два типа аккаунта (creator / advertiser), деплоим `web` + `Postgres` + `Redis` на Railway в приватной сети.
>
> Источники: `docs/00-MASTER-FlipHouse.md`, `docs/01-АРХИТЕКТУРА-И-RAILWAY.md` (§7 топология, §0 инварианты), `docs/02-ДИЗАЙН-И-МОУШЕН.md` (вся сборка hero/токены/моушен).

---

## Цель фазы

Поднять **полностью рабочую и задеплоенную** веб-оболочку, в которую в следующих фазах подключается клиппинг-пайплайн:

1. `web` (форк `ixartz/SaaS-Boilerplate`) с Clerk-auth, крипто-биллингом через `PaymentProvider` (USDT-баланс, PAYG+подписка) и Drizzle-миграциями, задеплоенный на Railway. (Организации убраны в P1.11 — роль creator/advertiser живёт в Clerk `publicMetadata`, биллинг-состояние — на пользователе.)
2. `Postgres` + `Redis` плагины Railway в приватной сети (`_PRIVATE_` URL, dual-stack bind на `::`/`0.0.0.0`).
3. Два типа аккаунта — **creator** и **advertiser** — как `accountType` на организации (`docs/01` §1), с разводящим онбордингом и RBAC-гейтом дашбордов.
4. Lovable-style **dark AI-tech** лендинг: центрированная hero-дропзона (drag&drop файла + paste-link + статусы `ready/submitted/streaming/error`) над анимированным shadergradient mesh, секции launch-ui, моушен через `motion` + Magic UI, scroll-сторителлинг (GSAP + Lenis).
5. `railway.json` config-as-code: healthcheck `/api/health`, миграции в `preDeployCommand`, 2 реплики `web`.

**Definition of Done фазы** — внизу файла, чек-лист «Выход фазы».

### Главный инвариант разработки (правило основателя №1)

**ZERO BUGS.** Каждый шаг — TDD-цикл: (1) пишем падающие тесты с точными именами и ассертами, (2) гоним → **RED**, (3) минимальная реализация, (4) гоним → **GREEN**, (5) рефактор, (6) commit. Шаг не «готов», пока его тесты не зелёные И не держится coverage-гейт (≥ 80% по `common/testing.md`). Один шаг = один атомарный commit.

---

## Зависимости (что должно быть сделано до P1)

- **P0 (Каркас и инфра)** — Railway-проект с окружениями `production` + `staging` (план Pro) должен существовать. Если P0 не выделена отдельной фазой, шаг **1.0** этой фазы создаёт проект и окружения. Здесь предполагается, что **Railway-аккаунт и CLI-доступ есть**, проект может быть пустым.
- Внешние аккаунты-песочницы: **Clerk**, **TRON testnet** (Nile/Shasta) + **TronGrid API-ключ** — выплаты не в P1, только депозит+списание. Секреты (`TRONGRID_API_KEY`, seed HD-кошелька и payout-hot-key — в KMS) кладутся в Railway env/секреты, никогда в код (`common/security.md`).
- Локально: Node 22 LTS, pnpm, Docker (для локального Postgres в e2e), `railway` CLI, `gh` CLI.

> **Разрешение конфликта доков:** `docs/01` §1 в таблице упоминает `nextjs/saas-starter` (custom JWT). `docs/00-MASTER` (стр. 22) и `docs/02` §2.1 предписывают **`ixartz/SaaS-Boilerplate` (Clerk)**. ТЗ P1 фиксирует именно `ixartz/SaaS-Boilerplate`. **Берём Clerk-вариант.** Расширение биллинга под per-clip/CPM (из `docs/01`) реализуем поверх абстракции `PaymentProvider` (свой TRON on-chain, USDT-баланс). Заметка: `ixartz/SaaS-Boilerplate` приходит со Stripe-биллингом — Stripe-код при форке **не переносится** (форк его срезал), вместо него — `PaymentProvider`.

---

## Репозитории, вендоренные/использованные в этой фазе

Всё клонируется в `vendor/` (lift конкретных файлов) либо ставится через CLI:

| Назначение | Команда | Режим |
|---|---|---|
| SaaS-каркас (база проекта) | `git clone https://github.com/ixartz/SaaS-Boilerplate vendor/saas-boilerplate` | Fork-as-base (копируем целиком в корень `web/`) |
| AI Elements PromptInput (оболочка hero-инпута) | `npx ai-elements@latest add prompt-input` | CLI add (copy-owned shadcn) |
| Kibo UI Dropzone (drop-поверхность) | `npx kibo-ui@latest add dropzone` | CLI add (copy-owned shadcn) |
| Magic UI (атмосфера: aurora/glow/border-beam) | `npx shadcn@latest add "https://magicui.design/r/border-beam.json"` (+ `aurora-text`, `shimmer-button`) | CLI add |
| Launch UI (секции лендинга) | `git clone https://github.com/launch-ui/launch-ui vendor/launch-ui` | Lift секций `components/sections/*` |
| shadergradient (WebGL mesh-фон) | `pnpm add @shadergradient/react @react-three/fiber three` | npm |
| motion (движок анимации) | `pnpm add motion` | npm |
| GSAP + ScrollTrigger | `pnpm add gsap` | npm (dynamic import) |
| Lenis (плавный скролл) | `pnpm add lenis` | npm |
| react-dropzone (движок под Kibo) | подтянется транзитивно Kibo; иначе `pnpm add react-dropzone` | npm |
| Style Dictionary (генератор токенов) | `pnpm add -D style-dictionary` | npm (dev) |

> Reference-only (НЕ копировать код, только изучать паттерны — `docs/02` §2.3): `adrianhajdin/*`, `olivierlarose/awwwards-landing-page`. **Избегать:** `whatamesh`, `origin-space/originui` (AGPL), `paper-design/shaders` (PolyForm).

---

## Чекпоинты (точки, где основатель ревьюит и может развернуть)

- 🛑 **ЧЕКПОИНТ A** (после 1.1) — базовый форк поднят локально, тесты репозитория зелёные.
- ✅ **ЧЕКПОИНТ B** (после 1.4) — визуальное направление утверждено: **«Swiss Pop»** (светлая база, paper/ink + vermillion/cobalt, эталон `docs/design-reference/swiss-pop.html`). Founder одобрил после 2 раундов дизайн-разведки. Шаги 1.5–1.8 ниже переопределены под Swiss Pop (вместо dark-mesh/glass).
- 🛑 **ЧЕКПОИНТ C** (после 1.7) — hero-дропзона со всеми состояниями: ключевой UX продукта.
- 🛑 **ЧЕКПОИНТ D** (после 1.9) — лендинг целиком (секции + scroll + моушен): маркетинг-поверхность.
- 🛑 **ЧЕКПОИНТ E** (после 1.11) — два типа аккаунта + онбординг-развод: продуктовая логика.
- 🛑 **ЧЕКПОИНТ F** (после 1.13) — крипто-биллинг (свой TRON on-chain): депозит USDT → watcher → баланс → PAYG/подписка: монетизационный путь.
- 🛑 **ЧЕКПОИНТ G** (после 1.16) — задеплоено на Railway, e2e зелёные на превью-домене: фаза закрыта.

---

# Шаги

---

### Шаг 1.0 — Railway-проект, окружения, приватные плагины Postgres/Redis

- **Цель / DoD:** существует Railway-проект FlipHouse с окружениями `production` + `staging`, в каждом подняты managed-плагины **Postgres** (+ volume) и **Redis**. Получены `DATABASE_PRIVATE_URL` и `REDIS_PRIVATE_URL`. Сервиса `web` пока нет — только инфра. (Инвариант `docs/01` §7: один проект, prod+staging, приватная сеть per-env.)
- **Репозитории/команды:** инфра-as-data, кода нет. Через Railway MCP / CLI:
  - создать проект `fliphouse`, окружения `production`, `staging`;
  - в каждом окружении добавить Postgres-плагин (с volume по шаблону) и Redis-плагин;
  - зафиксировать reference-переменные `${{Postgres.DATABASE_PRIVATE_URL}}`, `${{Redis.REDIS_PRIVATE_URL}}`.
- **Тесты СНАЧАЛА:** инфра не покрывается unit-тестами, но создаём **smoke-скрипт-проверку** `scripts/check-railway-infra.mjs` и тест к нему в Vitest (`tests/infra/railway-infra.test.ts`):
  - `test('railway project exposes Postgres and Redis private URLs')` — мок CLI-вывода (`railway variables --json`) → ассерт, что присутствуют ключи `DATABASE_PRIVATE_URL` и `REDIS_PRIVATE_URL` и оба матчат `^(postgresql|redis)://.*\.railway\.internal`.
  - `test('private URLs never reference public proxy domains')` — ассерт, что URL НЕ содержат `proxy.rlwy.net` / публичных хостов.
  - Гонка → RED (скрипта нет).
- **Реализация:** написать `scripts/check-railway-infra.mjs` (парсит `railway variables --json`, валидирует regex), создать проект/плагины через MCP `mcp__railway__create_project` / `create_environment` / `deploy_template` (Postgres, Redis). Записать фактические значения в `web/.env.railway.example` (без секретов, только имена переменных).
- **✅ Готово когда:** тесты GREEN; `railway list` показывает проект с 2 окружениями и 2 плагинами в каждом; приватные URL получены и валидны.
- **Commit:** `chore: provision railway project, environments and private postgres/redis plugins`

---

### Шаг 1.1 — Форк `ixartz/SaaS-Boilerplate` как база `web/`

- **Цель / DoD:** репозиторий-форк поднят как `web/` в монорепо FlipHouse, ставится, собирается, родные тесты репозитория зелёные локально на PGlite (DATABASE_URL опционален — см. context7). Это «нулевая точка» — дальше только наши изменения.
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/ixartz/SaaS-Boilerplate vendor/saas-boilerplate
  mkdir -p web && cp -R vendor/saas-boilerplate/. web/ && rm -rf web/.git
  cd web && pnpm install && npx playwright install
  ```
- **Тесты СНАЧАЛА:** не пишем новых — **запускаем родной набор** как baseline-gate:
  - `pnpm test` (Vitest unit) — должен пройти из коробки.
  - `pnpm test:e2e` (Playwright) — smoke родных e2e на PGlite.
  - Фиксируем зелёный baseline ДО любых правок. Если родной набор красный — чиним совместимость версий (Next 16 / React 19) ПЕРЕД продолжением.
- **Реализация:** скопировать структуру, добавить корневой `package.json` workspace (`pnpm-workspace.yaml` с `web`), `.gitignore`, `README` с указанием источника форка и лицензии (MIT). Зафиксировать `engines.node`.
- **✅ Готово когда:** `pnpm --filter web build` собирается; `pnpm --filter web test` и `test:e2e` зелёные; `pnpm --filter web dev` поднимает страницу на `localhost:3000`.
- **Commit:** `feat: fork ixartz/SaaS-Boilerplate as web/ base`

🛑 **ЧЕКПОИНТ A:** основатель проверяет, что база поднята, тесты форка зелёные, версии Next 16 / React 19 совместимы. Может сменить базовый форк до того, как мы начнём строить поверх.

---

### Шаг 1.2 — `/api/health` healthcheck + dual-stack bind

- **Цель / DoD:** есть эндпоинт `GET /api/health`, который Railway будет дёргать как healthcheck (`docs/01` §7). Возвращает `200 {status:'ok', db:'up'|'down', redis:'up'|'down'}`. Сервер биндится на `::`/`0.0.0.0` (инвариант dual-stack).
- **Тесты СНАЧАЛА** (Vitest, `src/app/api/health/route.test.ts`):
  - `test('GET /api/health returns 200 with status ok when db and redis reachable')` — мок Drizzle-пинга и Redis-пинга → `expect(res.status).toBe(200)` и `body.status==='ok'`.
  - `test('GET /api/health returns 503 when db ping fails')` — мок отказа БД → `expect(res.status).toBe(503)` и `body.db==='down'`.
  - `test('health check does not require auth')` — без Clerk-сессии всё равно 200.
  - Гонка → RED.
- **Реализация:** `src/app/api/health/route.ts` — `runtime='nodejs'`, лёгкий `SELECT 1` через Drizzle + `redis.ping()` с таймаутом 1s. Bind-настройка в `package.json` start-скрипте (`-H ::`). Healthcheck НЕ требует Clerk (добавить путь в `publicRoutes` middleware).
- **✅ Готово когда:** 3 теста GREEN; `curl localhost:3000/api/health` → `{status:'ok'}`; coverage по новому файлу ≥ 80%.
- **Commit:** `feat: add /api/health healthcheck with db+redis probes and dual-stack bind`

---

### Шаг 1.3 — Redis-клиент (ioredis) на `REDIS_PRIVATE_URL` + Env-валидация

- **Цель / DoD:** в проект добавлен singleton Redis-клиент (понадобится в P2 под BullMQ pub/sub, в P1 — для health и rate-limit), читающий `REDIS_PRIVATE_URL` через T3 Env. Отсутствие переменной валит старт с понятной ошибкой (`docs/01` §7, `common/coding-style.md` — fail fast).
- **Репозитории/команды:** `pnpm --filter web add ioredis`
- **Тесты СНАЧАЛА** (Vitest, `src/libs/Redis.test.ts`):
  - `test('Redis client connects using REDIS_PRIVATE_URL')` — мок env → ассерт, что конструктор ioredis вызван с приватным URL.
  - `test('throws at startup when REDIS_PRIVATE_URL is missing')` — пустой env → ожидаем брошенную ошибку валидации Zod с сообщением про REDIS_PRIVATE_URL.
  - `test('returns the same singleton on repeated import')` — два импорта → один инстанс.
  - RED.
- **Реализация:** расширить `src/libs/Env.ts` (Zod: `REDIS_PRIVATE_URL: z.string().url()`), `src/libs/Redis.ts` (lazy singleton, `maxRetriesPerRequest:null`, ленивый connect). Обновить `/api/health` на реальный `Redis.ping()`.
- **✅ Готово когда:** 3 теста GREEN; health показывает реальный redis-статус; старт без переменной даёт явный crash.
- **Commit:** `feat: add ioredis singleton on REDIS_PRIVATE_URL with env validation`

---

### Шаг 1.4 — Дизайн-токены oklch через Style Dictionary

> **[FOUNDER EDIT · 2026-06-15 · ЧП B] НАПРАВЛЕНИЕ = «SWISS POP».** Founder отверг dark-AI-tech (violet/cyan),
> затем 1-й раунд (Vibrant Pop, phone-карточки) как «поверхностно/иишно». Во 2-м раунде из 6 reference-grade
> концептов (без device-моков) выбран **«Swiss Pop»** (светлая база, эталон `docs/design-reference/swiss-pop.html`):
> off-white paper + ink, hairline-сетка, ОДИН vermillion-сигнал `oklch(63% 0.244 26)` + cobalt `oklch(48% 0.210 258)`,
> Archivo + IBM Plex Mono, продукт = ранкед-таблица клипов (без phone-моков). Тесты/значения ниже обновлены.
> См. `docs/02` (банер-решение наверху) и заметки исполнителя P1.4 в `STATE.md`. Эталон — РЕФЕРЕНС языка; блоки/контент переделываются при реализации.
> **[CONFLICT → флаг]** Шаг **1.5 (shadergradient WebGL mesh-фон)** и hero-сборка (`docs/02` §3/§5)
> предполагали dark-mesh; со Swiss Pop фон = бумажная сетка + hairline-rules + ранкед-лист + vermillion-акцент
> (без WebGL-mesh). Адаптация 1.5+ — на аппруве founder'а после ЧП B.

- **Цель / DoD:** палитра `docs/02` §1.2/§4 (Swiss Pop) реализована как **генерируемый** `src/styles/tokens.css` из `tokens/*.json` (SOURCE OF TRUTH). `tokens.css` и `COLORS.md` — build-артефакты, руками не правятся (`docs/02` §4, immutability). Tailwind v4 потребляет через `@theme inline`. Светлая база (без форсированной dark-темы).
- **Репозитории/команды:** `pnpm --filter web add -D style-dictionary`
- **Тесты СНАЧАЛА** (Vitest, `tokens/tokens.test.ts`):
  - `test('generated tokens.css contains all semantic shadcn and signal tokens')` — после `pnpm tokens` файл содержит `--background`, `--foreground`, `--primary`, `--ring`, `--card`, `--border`, `--muted`, `--pop`, `--cobalt`, `--rule-strong`.
  - `test('primary equals vermillion accent oklch(63% 0.244 26)')` — точное значение из `docs/02` §4.2.
  - `test('cobalt signal equals oklch(48% 0.210 258)')`.
  - `test('non-color tokens include --text-hero clamp and --ease-out-expo')` — `docs/02` §4.3 (`clamp(3.4rem, 1.2rem + 8.6vw, 10.5rem)`).
  - `test('tokens.css is regenerable and deterministic')` — два прогона дают идентичный файл (нет рандома).
  - RED (генератора и JSON нет).
- **Реализация:** `tokens/primitives.json` (paper/ink-нейтрали + signal-рампы pop/pop-press/cobalt), `tokens/semantic.light.json` (shadcn-имена + raw-сигналы `--pop/--cobalt/--ink-soft/--ink-faint/--rule/--rule-strong` под имена эталона), `tokens/non-color.json`; `style-dictionary.config.mjs` с кастомным no-header CSS-форматом (oklch verbatim, без color-transform); npm-скрипт `tokens` → `src/styles/tokens.css` + `COLORS.md`. Подключить в `global.css` через `@import` + `@theme inline`. Светлая `:root`-база (без `<html class="dark">`).
- **✅ Готово когда:** все 5 тестов GREEN; `pnpm tokens` детерминирован; приложение рендерится в Swiss-Pop (paper + ink + vermillion/cobalt) с читаемым контрастом на цветных блоках; coverage держится.
- **Commit:** `feat: oklch design tokens via Style Dictionary with dark theme default`

✅ **ЧЕКПОИНТ B — ОДОБРЕН (2026-06-15).** Founder утвердил направление **«Swiss Pop»** (светлая, paper/ink + vermillion `oklch(63% 0.244 26)` + cobalt) после 2 раундов дизайн-разведки и сказал «го». Эталон языка: `docs/design-reference/swiss-pop.html`. Шаги 1.5–1.9 ниже переопределены под Swiss Pop.

---

### Шаг 1.5 — Swiss-каркас: шрифты (next/font) + jsdom/RTL + базовый layout-shell

> **[FOUNDER EDIT · ЧП B] ПЕРЕОПРЕДЕЛЕНО под Swiss Pop.** shadergradient WebGL-mesh ВЫКИНУТ (не вписывается в светлую Swiss-эстетику). Вместо него — типографика эталона + тест-апаратура для UI + базовый каркас страницы (бумажная сетка, hairline-rules, семантический header/nav). Эталон: `docs/design-reference/swiss-pop.html`.

- **Цель / DoD:** в проект заведены шрифты эталона через `next/font/google` (**Archivo**, **Archivo Narrow**, **IBM Plex Mono**) с экспортом в CSS-переменные (`--font-grotesk/--font-narrow/--font-mono`), подключены в `@theme inline`; заведён jsdom/RTL-vitest-проект для `*.test.tsx` (UI-шаги 1.5–1.8); собран базовый Swiss layout-shell: семантический `header`/`nav` (mono-лейблы, hairline `--rule-strong` низ), контейнер-сетка (`--space-margin`/`--space-gutter`), утилиты eyebrow/rule-heading. Светлый `paper`-фон, ink-текст.
- **Репозитории/команды:** `pnpm --filter web add -D jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event` (next/font встроен).
- **Тесты СНАЧАЛА** (Vitest jsdom, `*.test.tsx`):
  - `src/components/layout/SiteHeader.test.tsx`: `test('site header exposes nav with aria-label and sign-in link')`; `test('header renders the FlipHouse wordmark as a home link')`.
  - `src/components/layout/Eyebrow.test.tsx`: `test('eyebrow renders a mono kicker label with its text')`.
  - (font wiring проверяется рендером — переменные на `<body>`/контейнере).
  - RED (компонентов/jsdom-проекта нет).
- **Реализация:** `src/styles/fonts.ts` (next/font, `variable`-экспорт); подключить переменные в `layout.tsx` + `@theme inline` (`--font-sans → --font-grotesk` и т.д.); `vitest.config.ts` — добавить второй проект `environment:'jsdom'` для `src/**/*.test.tsx` (+ setup с `@testing-library/jest-dom`); `src/components/layout/SiteHeader.tsx`, `Eyebrow.tsx`, контейнер/сетка-утилиты. Без device-моков, без WebGL.
- **✅ Готово когда:** tsx-тесты GREEN; шрифты грузятся; header рендерится в Swiss-стиле; `pnpm test`/`coverage` зелёные.
- **Commit:** `feat: swiss-pop typography (next/font) + jsdom/rtl test setup + base layout shell`

---

### Шаг 1.6 — Dropzone-примитив (drop-поверхность) в Swiss-стиле

> **[FOUNDER EDIT · ЧП B] Swiss-адаптация.** Без glass/BorderBeam/AI-Elements-prompt-box. Drop-поверхность — bordered (`--rule-strong`) b-w-поле в стиле эталона (mono-лейбл «drop a video / paste a link», vermillion-CTA). Можно взять Kibo Dropzone (MIT) как движок и перестилить под Swiss, либо тонкий кастом над `react-dropzone`. Полная детализация теста/реализации — на этом шаге.

- **Цель / DoD:** в проект добавлена copy-owned drop-поверхность (Kibo Dropzone, перестиленная под Swiss, ИЛИ кастом над react-dropzone) — без бизнес-логики FlipHouse, просто рендерится в Swiss-эстетике.
- **Репозитории/команды:**
  ```bash
  cd web
  npx ai-elements@latest add prompt-input
  npx kibo-ui@latest add dropzone
  ```
- **Тесты СНАЧАЛА** (Vitest, `src/components/hero/dropzone-primitives.test.tsx`):
  - `test('PromptInput renders a textarea and submit button')`.
  - `test('Dropzone renders empty state copy with max files and size')` — `<DropzoneEmptyState/>` показывает «Upload up to N… up to X MB».
  - `test('Dropzone applies drag-active styles when isDragActive')` — симуляция drag-enter → класс/атрибут active.
  - RED.
- **Реализация:** прогнать CLI-add, поправить импорты под структуру `web/src/components/ui`. Тонкая обёртка-демо `HeroInputShell` для теста рендера. Сохранить attribution в `NOTICE`.
- **✅ Готово когда:** 3 теста GREEN; компоненты импортируются без ошибок; drag-active визуально срабатывает.
- **Commit:** `feat: add AI Elements PromptInput and Kibo Dropzone primitives`

---

### Шаг 1.7 — Hero-дропзона: drop + paste-link + состояния `ready/submitted/streaming/error`

> **[FOUNDER EDIT · ЧП B] Swiss-адаптация.** Логика состояний/валидации/`onFlip` сохраняется; визуал — Swiss (bordered поле + hairline-rules + vermillion submit + ранкед-тизер результата), БЕЗ glass/BorderBeam/glow/mesh. Эталон: `docs/design-reference/swiss-pop.html`.

- **Цель / DoD:** ключевой UX-кусок (`docs/02` §3.2): один бокс принимает **видео-файл (drag&drop/globalDrop)** ИЛИ **вставленную видео-ссылку**, ведёт `status: ready|submitted|streaming|error`, валидирует вход и отдаёт `onFlip({file?, url?})`. Swiss-поле (border `--rule-strong`, vermillion submit) — без glass/mesh.
- **Тесты СНАЧАЛА** (Vitest + Testing Library, `src/components/hero/HeroDropzone.test.tsx`) — это **главный component-test набор фазы**:
  - `test('initial status is ready and submit is enabled')`.
  - `test('dropping a video file shows a file chip and keeps status ready')` — drop `new File([], 'v.mp4', {type:'video/mp4'})` → чип с именем.
  - `test('rejects non-video file and sets status error')` — drop `image/png` → `status==='error'`, видимое сообщение.
  - `test('rejects file over maxSize 500MB and sets status error')`.
  - `test('pasting a valid video URL shows a link chip alongside file chip')` — paste `https://youtu.be/...` → link-чип сосуществует с file-чипом (`docs/02` §3.2 п.3).
  - `test('pasting a non-URL string does not create a link chip')`.
  - `test('submit with neither file nor valid url sets status error and does not call onFlip')`.
  - `test('submit with a file transitions ready→submitted→streaming and calls onFlip with the file')` — ассерт последовательности статусов и аргумента.
  - `test('submit with a link calls onFlip with {url}')`.
  - `test('globalDrop on the hero region routes the file into the box')` (`docs/02` §3.2 п.5).
  - `test('PromptInputSubmit icon reflects current status')` — иконка стрелка→спиннер→ошибка по статусу (`docs/02` §3.1/§5.1).
  - `test('respects prefers-reduced-motion: no entrance animation when reduced')`.
  - RED (компонента нет).
- **Реализация:** `src/components/hero/HeroDropzone.tsx` — состояние `{files, link, status}`; `<Dropzone accept={{'video/*':[]}} maxFiles={1} maxSize={500*1024*1024} onDrop onError>`; контролируемый `PromptInputTextarea` для paste-link с URL-regex и проверкой видео-хоста (`src/lib/url.ts: isVideoUrl`); `<PromptInputSubmit status={status}/>`; `globalDrop`; стеклянная панель + `BorderBeam` (Magic UI). Утилита-валидатор `src/lib/url.ts` с отдельными unit-тестами (`url.test.ts`: `isVideoUrl` для youtube/youtu.be/vimeo/прямого `.mp4`, отказ для не-URL).
- **✅ Готово когда:** все ~12 тестов GREEN + `url.test.ts` GREEN; ручная проверка drag&drop и paste в браузере; coverage по `hero/` и `lib/url.ts` ≥ 80%.
- **Commit:** `feat: hero dropzone with drag-drop, paste-link and ready/submitted/streaming/error states`

🛑 **ЧЕКПОИНТ C:** основатель щупает живую hero-дропзону (все состояния, drag&drop, paste-link, ошибки). Это центральный UX продукта — он может переразвести взаимодействие/копирайт до того, как мы обвесим её лендингом.

---

### Шаг 1.8 — Секции лендинга в Swiss-стиле (ранкед-таблица + процесс 01–04 + marketplace)

> **[FOUNDER EDIT · ЧП B] ПЕРЕОПРЕДЕЛЕНО под Swiss Pop.** Вместо lift из launch-ui — собрать секции по эталону `docs/design-reference/swiss-pop.html`: ранкед-таблица «The output is a ranked list» (clip/length/format/viral-score), «Four passes» 01–04, marketplace (creators/advertisers, in-clip native banner + payout), receipts (большие числа), CTA. Огромный H1 `--text-hero`, нумерованные секции, hairline-rules, vermillion-акцент.

- **Цель / DoD:** собран полноценный Swiss-лендинг вокруг hero: ранкед-таблица клипов, процесс 01–04, marketplace-секция, receipts, CTA, footer — по эталону. Семантический HTML (`header/main/section/footer`, `aria-labelledby`), единственный H1.
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/launch-ui/launch-ui vendor/launch-ui
  # lift конкретных секций:
  cp vendor/launch-ui/src/components/sections/{logos,stats,faq,cta,footer,navbar}.tsx web/src/components/sections/
  ```
- **Тесты СНАЧАЛА** (Vitest, `src/app/(landing)/page.test.tsx`):
  - `test('landing renders a single h1 inside hero section')`.
  - `test('landing exposes semantic landmarks header/main/footer')`.
  - `test('navbar has aria-label Main navigation and links to sign-in')`.
  - `test('each section has an aria-labelledby pointing to a real heading id')`.
  - `test('AnimatedHeading splits text into word spans for reveal')`.
  - RED.
- **Реализация:** `src/app/(landing)/page.tsx` компонует `Navbar → Hero(HeroDropzone) → Logos → Stats → Faq → Cta → Footer`. `src/components/ui/AnimatedHeading.tsx` (motion word-split, compositor-only `transform/opacity`). Адаптировать lifted-секции под наши токены (никаких немодифицированных дефолтов — `docs/02` §1.3 анти-шаблон).
- **✅ Готово когда:** 5 тестов GREEN; страница связно собрана; единственный H1; лендинг не выглядит как голый shadcn-стартер.
- **Commit:** `feat: assemble landing sections from launch-ui with animated hero heading`

---

### Шаг 1.9 — Scroll-ревилы (IntersectionObserver, compositor-only)

> **[FOUNDER EDIT · ЧП B] Swiss-адаптация.** Эталон использует лёгкие IntersectionObserver-ревилы (fade/translate на `transform/opacity`), а не тяжёлый GSAP+Lenis pin/scrub. По умолчанию — IO-ревилы (меньше JS, лучше бюджет лендинга); GSAP/Lenis — опционально, только если потребуется pin/scrub-сторителлинг (решим при реализации). `prefers-reduced-motion` → ревилы off.

- **Цель / DoD:** scroll-driven раскрытие секций через IntersectionObserver: появление на `transform/opacity/clip-path` (compositor-only), стаггер по секциям, `prefers-reduced-motion` отключает. Без тяжёлых зависимостей в критическом пути.
- **Репозитории/команды:** `pnpm --filter web add gsap lenis`
- **Тесты СНАЧАЛА:**
  - Vitest (`src/hooks/useSmoothScroll.test.ts`): `test('initializes Lenis and registers gsap ticker sync')` — мок gsap/lenis → ассерт вызова `gsap.ticker.add` и `lenis.on('scroll', ...)`; `test('does not initialize Lenis when reduced motion preferred')`; `test('cleans up ticker and lenis on unmount')` (нет утечек).
  - Vitest (`src/lib/scroll-reveal.test.ts`): `test('reveal animations only touch transform/opacity/clip-path')` — статический разбор конфигов анимаций, ассерт что ни одно свойство не из banned-списка (`width/height/top/left/margin/padding/border/font-size`, `web/coding-style.md`).
  - RED.
- **Реализация:** `src/hooks/useSmoothScroll.ts` (Lenis + gsap.ticker, `await import('gsap')` / `gsap/ScrollTrigger`, reduced-motion гейт); `src/lib/scroll-reveal.ts` (декларативные конфиги reveal только на compositor-friendly свойствах); подключить pin/clip-path к секциям лендинга.
- **✅ Готово когда:** тесты GREEN; скролл плавный, секции раскрываются; reduced-motion отключает scrub; GSAP не в initial bundle (проверка в 1.16).
- **Commit:** `feat: scroll-driven storytelling with gsap scrolltrigger and lenis`

🛑 **ЧЕКПОИНТ D:** основатель смотрит лендинг целиком — секции, моушен, scroll-сторителлинг, ощущение «реального продукта». Может переставить секции/моушен до перехода к продуктовой логике аккаунтов.

---

### Шаг 1.10 — Тип аккаунта `accountType` (creator | advertiser) в Drizzle-схеме

- **Цель / DoD:** в схему добавлено поле `accountType` на организацию (`docs/01` §1 — «`accountType` на teams»), enum `'creator' | 'advertiser'`, с миграцией. Drizzle-миграция авто-применяется на старте (context7), для prod — через `db:migrate`.
- **Тесты СНАЧАЛА** (Vitest integration на PGlite, `src/models/account-type.test.ts`):
  - `test('organization schema has accountType enum column')` — интроспекция схемы → колонка `account_type` типа enum.
  - `test('accountType defaults to null until onboarding sets it')` — insert без типа → `null`.
  - `test('persists and reads back accountType=creator')` — round-trip.
  - `test('rejects invalid accountType value')` — insert `'admin'` → ошибка.
  - `test('migration is idempotent (re-run is a no-op)')`.
  - RED.
- **Реализация:** расширить `src/models/Schema.ts` (`pgEnum('account_type', ['creator','advertiser'])`, колонка на `organizationSchema`); `pnpm --filter web db:generate` → `migrations/000X_account-type.sql`; helper `src/models/queries/accountType.ts` (`getAccountType`, `setAccountType`).
- **✅ Готово когда:** 5 тестов GREEN на PGlite; миграция сгенерирована и применяется; coverage держится.
- **Commit:** `feat: add accountType (creator|advertiser) to organization schema`

---

### Шаг 1.11 — Онбординг-развод creator/advertiser + RBAC-гейт дашбордов

- **Цель / DoD:** после регистрации (Clerk) и создания организации пользователь выбирает тип (creator/advertiser); выбор пишется в `accountType`; дашборды разведены: `/dashboard/creator` и `/dashboard/advertiser`, доступ гейтится по `accountType` (чужой тип → redirect). Без выбора → форс на `/onboarding`.
- **Тесты СНАЧАЛА:**
  - Vitest (`src/app/onboarding/actions.test.ts`): `test('selectAccountType writes creator to org and redirects to /dashboard/creator')`; `test('selectAccountType writes advertiser and redirects to /dashboard/advertiser')`; `test('selectAccountType rejects when org already has a type')` (immutable после установки).
  - Vitest (`src/lib/rbac.test.ts`): `test('requireAccountType allows matching type')`; `test('requireAccountType redirects creator away from advertiser dashboard')`; `test('redirects to /onboarding when accountType is null')`.
  - Playwright (`tests/e2e/onboarding.spec.ts`): `test('new user picks creator and lands on creator dashboard')` — детерминированный signup (Clerk test-mode/testing token) → выбор creator → URL `/dashboard/creator`, виден creator-заголовок.
  - RED.
- **Реализация:** `src/app/onboarding/page.tsx` (выбор типа, две карточки), server action `selectAccountType` (immutable set), `src/lib/rbac.ts` (`requireAccountType(type)` — читает org accountType, redirect), middleware-гейт `dashboard/*`, страницы `dashboard/creator/page.tsx` и `dashboard/advertiser/page.tsx`.
- **✅ Готово когда:** unit + rbac GREEN, e2e онбординга GREEN; ручная проверка обоих путей; coverage держится.
- **Commit:** `feat: creator/advertiser onboarding split with rbac-gated dashboards`

🛑 **ЧЕКПОИНТ E:** основатель проходит оба онбординг-пути (creator и advertiser), проверяет разводку дашбордов и RBAC. Может изменить продуктовую модель типов/прав до подключения денег.

---

### Шаг 1.12 — Крипто-биллинг через `PaymentProvider`: депозит USDT → баланс → PAYG + подписка

> **[FOUNDER EDIT · 2026-06-15] ВСЁ НА КРИПТЕ. ЮKassa УБРАНА. УРОВЕНЬ 3 — СВОЙ ON-CHAIN, БЕЗ ЧУЖОГО ПРОЦЕССОРА.**
> Креаторам выплачивают в крипте → и за использование платят криптой. Биллинг — за vendor-нейтральной абстракцией
> `PaymentProvider` (как `PublishProvider` в P6); **конкрет-реализация — наш собственный on-chain приёмник
> USDT TRC-20** (`provider/tron.ts`): HD-кошелёк (per-user deposit-адрес) + свой TRON-узел / TronGrid + `tronweb`
> для подписи выплат. **Никакого стороннего PSP** — никто не может заморозить на уровне процессора (риск остаётся
> только у эмитента Tether: лечится чистым AML + ротацией адресов + быстрым офф-рампом). Биллинг-состояние — на
> **пользователе** (`userId`), НЕ на организации (удалены в P1.11).
>
> **Безопасность ключей (критично, `common/security.md`):** seed HD-кошелька и ключ горячего payout-кошелька —
> только в KMS/секретах, никогда в коде/БД. Hot/cold-split: на горячем — минимум под выплаты, основной баланс
> на cold. TRON energy/bandwidth — заранее (stake TRX), чтобы выплаты не падали на комиссии.
>
> **В крипте НЕТ сохранённой карты/автосписания** → модель = **предоплаченный баланс в стейблкоине**. Юзер
> пополняет баланс USDT (перевод на свой deposit-адрес) → внутренний ledger (off-chain кредиты). Списания:
> - **PAYG (разовое, ~90% маржи):** **$0.25/мин** исходника списывается с баланса за каждую нарезку.
> - **Подписка (списание с баланса раз в месяц):** дешевле за минуту, для активных. Не хватило баланса при продлении → откат на PAYG/free.
>
> Тариф ограничивает **минуты исходного видео/мес** (главный драйвер себес — GPU reframe/ASD, ~$0.025/мин). Сетка в USDT (выверена против Opus Clip — их Pro = 300 мин/$29):
>
> | План | $/мес (USDT) | Лимит мин/мес | $/мин | Особое |
> |---|---|---|---|---|
> | `free` | 0 | 30 | — | watermark, 720p |
> | `start` | 9 | 150 | 0.06 | без watermark, 1080p |
> | `active` | 24 | 300 | 0.08 | + авто-постинг |
> | `studio` | 59 | 1000 | 0.059 | + приоритет очереди |
> | `payg` | — | по балансу | **0.25** | разовое, ~90% маржи |
>
> Пополнения баланса: $10 / $25 / $50 / $100 USDT (на $100 бонус +10%); мин. депозит $10 (газ). Цены/лимиты — в конфиге (`BILLING_PLAN_ENV`), не в call-site.

- **Цель / DoD:** юзер пополняет крипто-баланс (USDT TRC-20) и платит за нарезки. Состояние (`plan`, `balanceUsdt`,
  `depositAddress`, `subscriptionStatus`, `currentPeriodEnd`, `minutesUsedThisPeriod`) — по `userId` в Drizzle-таблице
  `subscription` (PK = Clerk `userId`) + ledger `balance_entries` (пополнения/списания, идемпотентны). Кнопка
  «Пополнить» из дашборда показывает персональный TRC-20 deposit-адрес/QR (детерминированно выведенный из HD-кошелька
  по `userId`). Лимит минут И достаточность баланса проверяются ПЕРЕД постановкой клиппинг-джобы.
- **Абстракция:** `src/features/billing/PaymentProvider.ts` — интерфейс: `getDepositAddress(userId)` →
  per-user TRC-20 адрес (HD-derive); `getBalance(userId)`, `debit(userId, amountUsdt, reason)` (off-chain ledger,
  идемпотентно); `createPayout(toAddress, amountUsdt)` (подпись+бродкаст TRC-20 transfer). Конкрет-реализация
  `provider/tron.ts` (свой on-chain, `tronweb` + TRON-узел/TronGrid) регистрируется фабрикой по env (`PAYMENT_PROVIDER=tron`).
  Тесты гоняют **мок `PaymentProvider`** — реальная сеть TRON/ключи не нужны для юнит-тестов.
- **Тесты СНАЧАЛА** (Vitest, `src/features/billing/{deposit,balance,plans}.test.ts`):
  - `test('getDepositAddress derives a deterministic per-user TRC-20 address (HD path)')` — один и тот же `userId` → тот же адрес.
  - `test('PAYG debit charges $0.25 per source-minute from balance')` — себес-маржа закреплена тестом.
  - `test('clipping is blocked when balance < cost (PAYG) or minute cap exceeded (subscription)')` — гейт баланса/лимита ПЕРЕД джобой.
  - `test('debit is idempotent per job (retry does not double-charge)')` — unique по `(userId, jobId)`.
  - `test('plan minute caps + prices match config (free 30 / start 9·150 / active 24·300 / studio 59·1000 / payg 0.25)')`.
  - `test('subscription monthly charge debits balance; insufficient balance → downgrade to payg/free')`.
  - RED.
- **Реализация:** `src/features/billing/` — `plans.ts` (конфиг из `BILLING_PLAN_ENV`); `balance.ts` (ledger пополнений/списаний); `usageGate.ts` (баланс + остаток минут по `userId`); кнопка «Пополнить» (deposit-адрес/QR) в дашборде креатора; `provider/tron.ts` — HD-derive адреса + `tronweb` для выплат, seed/hot-key из KMS, заполняется к ЧЕКПОИНТУ F.
- **✅ Готово когда:** тесты GREEN (на моках провайдера); coverage держится. Живой прогон на TRON testnet (Nile/Shasta) — на ЧЕКПОИНТЕ F.
- **Commit:** `feat: crypto prepaid-balance billing via own TRON PaymentProvider (PAYG + subscription)`

---

### Шаг 1.13 — On-chain watcher TRON: подтверждение депозита → идемпотентное зачисление баланса

- **Цель / DoD:** свой **watcher** следит за TRON-сетью и зачисляет USDT TRC-20-депозиты на баланс `userId`,
  когда перевод на его deposit-адрес подтверждён (≥ N блоков). Чужого PSP/webhook НЕТ — источник истины — сама
  цепочка. Покрыт **интеграционными тестами** на фикстурах TRON-транзакций (`common/testing.md`).
- **Как следим (свой on-chain, не PSP):** отдельный сервис/воркер `payments-watcher` опрашивает TRON через свой
  узел / TronGrid: TRC-20 `Transfer`-события USDT-контракта на наши deposit-адреса. Зачисляем **только при ≥ N
  подтверждениях** (pending/недосыл не зачисляем). Идемпотентность — по **`txid`** (on-chain tx уникален).
  Это паттерн «submit-and-park»-родственник GPU-watcher'а из `docs/01` §5 (отдельный сервис, не блокирует воркеры).
- **Тесты СНАЧАЛА** (Vitest integration, `src/payments/watcher/*.test.ts`) на PGlite + фикстурах TRON-tx:
  - `test('credits balanceUsdt when a confirmed USDT TRC-20 transfer to a user deposit address is seen')`.
  - `test('does NOT credit on < N confirmations (pending) or wrong token contract')`.
  - `test('duplicate txid is idempotent (credited once)')` — повтор той же tx → одно зачисление (ledger dedupe по `txid`).
  - `test('credits the correct userId by mapping deposit address → user')`.
  - `test('underpaid/overpaid amount credits the actual on-chain amount, not the invoice')`.
  - `test('subscription renewal: monthly debit from balance flips status active/past_due')`.
  - RED.
- **Реализация:** `src/payments/watcher/` — поллер TronGrid/узла (TRC-20 `Transfer` фильтр по USDT-контракту +
  нашим адресам), confirmations-гейт, зачисление в `balance_entries` (unique `txid`) / апдейт `subscription` по
  `userId`, курсор последнего обработанного блока в Redis/PG. Реальные TRON-вызовы — за `PaymentProvider`, в тестах замоканы.
- **✅ Готово когда:** интеграционные тесты GREEN (на фикстурах tx); coverage держится. Реальный депозит на TRON testnet (Nile/Shasta) → баланс — на ЧЕКПОИНТЕ F.
- **Commit:** `feat: own TRON on-chain deposit watcher with confirmations + idempotent balance credit`

🛑 **ЧЕКПОИНТ F:** основатель прогоняет полный путь (депозит USDT TRC-20 на свой адрес → watcher подтверждает → баланс → PAYG-нарезка / подписка → выплата) на TRON testnet и проверяет идемпотентность (по `txid`), безопасность ключей (KMS, hot/cold), confirmations-гейт, лимиты минут. Может скорректировать тарифы/PAYG/число подтверждений до деплоя.

---

### Шаг 1.14 — `railway.json` config-as-code: healthcheck, миграции, 2 реплики

- **Цель / DoD:** деплой `web` декларативен (`docs/00` Phase 0, `docs/01` §7): healthcheck `/api/health`, миграции в `preDeployCommand`, `replicas: 2`, bind на `::`. Билд воспроизводим.
- **Тесты СНАЧАЛА** (Vitest, `tests/infra/railway-config.test.ts`):
  - `test('railway.json sets healthcheckPath to /api/health')`.
  - `test('railway.json runs drizzle migrate in preDeployCommand')` — `deploy.preDeployCommand` содержит `db:migrate`.
  - `test('web service requests 2 replicas')`.
  - `test('start command binds to dual-stack (::)')`.
  - RED.
- **Реализация:** `web/railway.json` (`build.builder`, `deploy.startCommand`, `deploy.healthcheckPath:'/api/health'`, `deploy.preDeployCommand:'pnpm db:migrate'`, `deploy.numReplicas:2`, `restartPolicyType:'ON_FAILURE'`). Привязать reference-переменные `${{Postgres.DATABASE_PRIVATE_URL}}`, `${{Redis.REDIS_PRIVATE_URL}}`.
- **✅ Готово когда:** 4 теста GREEN; `railway up --detach` стартует с применением миграций и healthcheck зелёным.
- **Commit:** `chore: railway.json config-as-code (healthcheck, predeploy migrate, 2 replicas)`

---

### Шаг 1.15 — Деплой `web` на Railway (staging) с приватной сетью

- **Цель / DoD:** сервис `web` (+ `payments-watcher`) создан в окружении `staging`, подключён к Postgres/Redis по `_PRIVATE_` URL, секреты Clerk/`TRONGRID_API_KEY`/KMS-ключи кошелька в env (не в коде, `common/security.md`), сгенерирован домен, healthcheck зелёный, миграции применились в preDeploy.
- **Репозитории/команды:** через Railway MCP: `mcp__railway__create_service` (`web`, root `web/`), `mcp__railway__set_variables` (Clerk/`TRONGRID_API_KEY`/KMS/`DATABASE_PRIVATE_URL`/`REDIS_PRIVATE_URL` через reference), `mcp__railway__generate_domain`, `mcp__railway__deploy`.
- **Тесты СНАЧАЛА** (Playwright против превью-домена, `tests/e2e/deploy-smoke.spec.ts`):
  - `test('staging /api/health returns 200 ok over https')`.
  - `test('staging landing renders h1 and hero dropzone')`.
  - `test('no public env leakage: page source has no sk_/whsec_ secrets')` — ассерт отсутствия серверных секретов в HTML.
  - RED (до деплоя).
- **Реализация:** создать сервис, проставить переменные, задеплоить; убедиться bind `::`, приватные ссылки на БД/Redis (нулевой egress).
- **✅ Готово когда:** деплой зелёный; healthcheck 200; 3 smoke-теста GREEN на staging-домене; в HTML нет секретов.
- **Commit:** `chore: deploy web to railway staging with private postgres/redis wiring`

---

### Шаг 1.16 — Сквозные e2e + визуальная регрессия + Lighthouse-гейт

- **Цель / DoD:** закрываем фазу обязательным e2e (`web/testing.md`): полный путь **signup → subscribe → land-on-dashboard**, hero-drop-интеракция, визуальная регрессия на брейкпоинтах, Lighthouse-бюджет лендинга (`docs/02` §5.3 / `web/performance.md`).
- **Тесты СНАЧАЛА:**
  - Playwright (`tests/e2e/signup-subscribe-dashboard.spec.ts`) — **главный e2e фазы**: `test('signup → top up balance → lands on creator dashboard with funded balance / active plan')` — Clerk test-mode signup → onboarding=creator → депозит USDT на deposit-адрес (TRON testnet или замоканная подтверждённая tx в CI) → watcher зачисляет баланс → дашборд показывает баланс/active-план. Детерминированные waits, без timeout-флака.
  - Playwright (`tests/e2e/hero-drop.spec.ts`): `test('dropping a video file into hero shows file chip and enables flip')` — `browser_file_upload`/`setInputFiles` mp4-фикстура; `test('pasting a video link shows link chip')`; `test('non-video drop shows error state')`.
  - Playwright visual (`tests/e2e/visual.spec.ts`): `test('landing matches snapshot at 320/768/1024/1440')` — скриншоты брейкпоинтов (`web/testing.md`), без overflow.
  - Lighthouse-гейт (`tests/perf/lighthouse.test.ts` через `playwright` + `lighthouse`): `test('landing meets CWV budget: LCP<2.5s, CLS<0.1, TBT<200ms, JS<150kb')`.
  - RED (часть путей ещё не покрыта end-to-end).
- **Реализация:** дописать недостающие data-testid, mp4-фикстуру `tests/fixtures/sample.mp4` (маленький валидный клип), настроить CI-джоб с фикстурой подтверждённой TRON-tx для watcher'а в e2e, baseline-скриншоты, Lighthouse-конфиг с бюджетами.
- **✅ Готово когда:** все e2e GREEN на staging; визуальные снапшоты зафиксированы; Lighthouse в бюджете; полный coverage-гейт фазы ≥ 80% (unit+integration+e2e).
- **Commit:** `test: e2e signup→subscribe→dashboard, hero drop, visual regression and lighthouse budget`

🛑 **ЧЕКПОИНТ G:** основатель видит задеплоенный лендинг + дашборды на staging-домене, прогоняет signup→subscribe→dashboard вживую, смотрит визуальные снапшоты и Lighthouse-отчёт. Точка решения «промоутить staging→production» и закрыть фазу.

---

## Выход фазы (Phase exit criteria)

- [ ] Railway-проект `fliphouse` с окружениями `production` + `staging`; в каждом — managed Postgres (+volume) и Redis, связь по `_PRIVATE_` URL, нулевой egress (1.0).
- [ ] `web` — форк `ixartz/SaaS-Boilerplate`, родные тесты зелёные как baseline (1.1).
- [ ] `/api/health` отдаёт реальный статус db+redis, не требует auth, bind на `::`/`0.0.0.0` (1.2, 1.3).
- [ ] oklch-токены генерируются Style Dictionary из `tokens/*.json`, dark AI-tech тема (1.4).
- [ ] Hero-дропзона: drag&drop файла + globalDrop + paste-link, состояния `ready/submitted/streaming/error`, валидация типа/размера — все component-тесты зелёные (1.5–1.7).
- [ ] Лендинг: секции launch-ui, анимированный H1, scroll-сторителлинг (GSAP+Lenis, dynamic import), reduced-motion, только compositor-friendly свойства (1.8, 1.9).
- [ ] Два типа аккаунта `creator`/`advertiser` в Drizzle-схеме, онбординг-развод, RBAC-гейт дашбордов (1.10, 1.11).
- [ ] Крипто-биллинг через `PaymentProvider` (свой TRON on-chain): депозит USDT TRC-20 → on-chain watcher (confirmations, идемпотентно по `txid`) → баланс + PAYG ($0.25/мин) + подписка с лимитом минут (1.12, 1.13).
- [ ] `railway.json`: healthcheck `/api/health`, миграции в `preDeployCommand`, 2 реплики, dual-stack (1.14).
- [ ] `web` задеплоен на staging, секреты только в env, healthcheck зелёный (1.15).
- [ ] e2e зелёные: **signup→subscribe→dashboard** + hero-drop; визуальная регрессия 320/768/1024/1440; Lighthouse в бюджете (LCP<2.5s, CLS<0.1, TBT<200ms, JS<150kb) (1.16).
- [ ] **Coverage ≥ 80%** (unit + integration + e2e) по всему `web/`. Каждый шаг закоммичен атомарно, все тесты зелёные. **ZERO known bugs.**
- [ ] Пройдены все 7 чекпоинтов (A–G) с явным апрувом основателя.

> Дальше — **P2 (Клиппинг-движок MVP)**: вендоринг `mutonby/openshorts` `main.py`, tusd→R2, BullMQ-оркестрация, `ai-render-worker`. P1 даёт оболочку, в которую P2 подключает пайплайн (hero `onFlip` → tusd-upload → Flow-DAG).
