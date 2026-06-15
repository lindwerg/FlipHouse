# FlipHouse — STATE.md (Трекер прогресса)

> **СЕЙЧАС / Следующий шаг → P1.5** (Swiss Pop hero — переопределён, см. ниже). ✅ ЧЕКПОИНТ B ОДОБРЕН founder'ом («го»): направление **«Swiss Pop»** (эталон `docs/design-reference/swiss-pop.html`). Путь выбора: dark-AI-tech (violet/cyan) — отвергнут → 1-й раунд (12 направлений) → Vibrant Pop выбран, затем отвергнут как «поверхностно/иишно» → 2-й раунд (6 reference-grade, без device-моков) → **Swiss Pop**. ✅ P1.4 — oklch дизайн-токены через Style Dictionary под Swiss Pop: светлая `:root`-база (paper `oklch(97.5% 0.004 95)` + ink `oklch(17% 0.012 270)`), primary/pop vermillion `oklch(63% 0.244 26)`, cobalt `oklch(48% 0.210 258)`, raw-сигналы (`--pop/--cobalt/--ink-soft/--rule/--rule-strong`) под имена эталона; `src/styles/tokens.css` + `COLORS.md` из `tokens/*.json`. **P1.5–P1.8 переопределены под Swiss Pop** (shadergradient WebGL-mesh выкинут; вместо — Archivo/Plex-Mono шрифты, бумажная сетка, hero с дропзоной + ранкед-таблица, секции 01–04, IntersectionObserver-ревилы) — см. `roadmap/P1`. ✅ P1.1 (форк SaaS-Boilerplate, **PR #1 смержен в `main`**, merge `4b023b0`), ✅ P1.2 (`/api/health`: db+redis пробы, 200/503, публичный) и ✅ P1.3 (ioredis-синглтон на `REDIS_PRIVATE_URL` + Zod env-валидация, реальный `probeRedis` ping) закрыты; чекпоинт A одобрен founder'ом. Все гейты зелёные. P0 ЗАВЕРШЁН ✅.
> ЧП F закрыт: CI зелёный на GitHub Actions + branch protection включён (job `ci` required на `main`, strict;
> `enforce_admins=false`, чтобы per-step прямой push не блокировался). Founder авторизовал включение
> («сделай всё сам»). Фаза P0 (леса + тест-харнесс + vendor + CI-гейт) готова — фундамент под ZERO bugs стоит.

> **Заметки исполнителя (2026-06-15):**
> - `[BACKFILL]` Шаг P0.5 был ошибочно помечен ✅ без реализации и без коммита. Доделан по TDD этой
>   сессией (vitest `test.projects` аггрегат + `scripts/__tests__/aggregate-test.test.mjs`,
>   корневые `test`/`coverage` → `vitest run`). Порядок шагов восстановлен.
> - `[FIX SHA]` Записанные ранее SHA шагов P0.1–P0.4 не совпадали с реальной историей git —
>   исправлены на фактические (`654ca13`, `cd45a5d`, `fd9c2f5`, `d485bc2`) по решению founder'а.
> - `[ЧП C — РАСШИРЕНИЕ]` Founder на чекпоинте C расширил golden-контракт: добавлены ассерты
>   `probe_video_codec` (H.264), `probe_pixel_format` (yuv420p), `has_audio` — отдельным коммитом
>   поверх P0.7. Закрывает немой клип и отклонение платформой; фикстура кодирует целевой формат.
> - `[P0.8 — РЕШЕНИЕ FOUNDER'А]` `resolveQueue` реализован по ПОЛНОЙ таблице docs/01 §5
>   (transcode→transcode, asr→gpu-asr, score→gpu-score, reframe/caption/banner/store→cpu, publish→publish),
>   а не по ошибочному примеру-имени роадмапа (transcode→cpu). Тест transcode переименован правдиво.
> - `[P0.8 — ТЕХ-ЗАМЕТКА]` Внутри Next-бандла (Turbopack) относительные импорты на TS-исходники идут БЕЗ
>   `.js`-суффикса — через alias `@/*` (Turbopack не резолвит `.js`→`.ts`, в отличие от Node ESM/vitest;
>   см. [[esm-js-extensions]]). vitest-конфиг и `*.test.ts` исключены из Next-typecheck (тулинг, не Next-исходники).
> - `[P0.8 — FIX SHA]` Строка P0.8 исправлена `9f75a7c`→`3fb1ef6` (реальный запушенный HEAD; `9f75a7c` —
>   pre-amend twin, осиротевший после `--amend`-вписывания sha).
> - `[P0.9 — ФАКТ-ЧЕК ЛИЦЕНЗИЙ]` Лицензии в `PINS.lock` сверены с реальными LICENSE-файлами клонов, а не с
>   таблицей роадмапа: `ai-elements` = **Apache-2.0** (роадмап говорил «Other»), `lr-asd` = **MIT** (роадмап:
>   «проверить при лифте»). `samuraigpt-shorts` и `cliq` — LICENSE-файла нет → `NONE` (reference-only). Пины —
>   HEAD shallow-клонов на 2026-06-15; смена upstream HEAD не влияет (запинено в `PINS.lock`).
> - `[P0.11 — БАГ pytest ПОЙМАН]` В этом окружении `fliphouse_worker` НЕ установлен (no editable install), и
>   bare `pytest` не кладёт CWD в `sys.path` → `ModuleNotFoundError`. `ci-local.sh` использует **`python -m pytest`**
>   (добавляет CWD). Протокол §1.3/роадмап показывают `pytest` — на лифте P2 учесть (или добавить `pip install -e .`).
> - `[P0.11 — CI РАСХОЖДЕНИЕ ПОЙМАНО]` Первый CI-ран на GitHub упал: vendor-клоны gitignored → в CI-checkout
>   их нет, а `vendor-pins.test.mjs` требовал наличия директорий. Фикс: проверка наличия 11 директорий
>   скипается при `process.env.CI` (локально работает; коммиченный `PINS.lock` валидируется и в CI). Гоняю CI
>   до зелёного ПЕРЕД включением branch protection (нельзя делать required красный check на main).
> - `[P0.12 — CI FIX-2]` `setup-idempotent.test.mjs` тоже падал в CI (vendor-клонов нет → setup.sh печатал
>   `would: git clone openshorts`, а не `skip`). Фикс по роадмапу («мокнуть наличие vendor/openshorts»): тест сам
>   создаёт фейковый `vendor/openshorts/.git` если его нет, проверяет `skip`, и удаляет ТОЛЬКО созданное (реальный
>   клон не трогает). Работает локально и в CI. Проверено обе ветки (клон есть / отсутствует).

> **Заметки исполнителя — P1.1 (2026-06-15):**
> - `[ФОРК]` `apps/web` пересоздан как форк ixartz/SaaS-Boilerplate (pinned `2fb2014`, MIT); P0-каркас заменён. Стек: Next 16 / React 19 / @clerk/nextjs 7 / @clerk/shared / Drizzle / next-intl / Tailwind v4 / PGlite.
> - `[РЕШЕНИЕ FOUNDER'А — Clerk]` Clerk-приложение `app_3F95DjSclyWOw7eHFfF8Af5XrNH` (founder прислал снэппет из дашборда Clerk). `clerk init` НЕ запускали — база уже содержит Clerk целиком; линкуемся через env. `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` в коммиченном `.env` (несекретный; пока тестовый pk — founder подменит на pk_ своего app); `CLERK_SECRET_KEY` → только `.env.local` (gitignored), founder вставляет сам.
> - `[РЕШЕНИЕ FOUNDER'А — инфра/БД]` Railway-инфра (роадмап Шаг 1.0) ОТЛОЖЕНА; стартовали с форка. БД — НЕ Supabase/облако: локально PGlite, прод — self-hosted Railway Postgres (приватная сеть, deploy-шаги 1.14–1.15).
> - `[ПРИМИРЕНИЕ ТУЛИНГА]` Корневой harness — источник истины гейтов. `apps/web` вынесен из корневого `eslint .` (линтится своим тулчейном); корневой vitest-аггрегат подхватывает headless **node**-конфиг `apps/web` (browser/Storybook-проекты НЕ включены — иначе падал бы `aggregate-test`, требующий exit 0). Срезаны Sentry / Storybook / semantic-release / checkly / crowdin / commitlint / lefthook / knip / bundle-analyzer (периферия, YAGNI для P1).
> - `[ПОРТ БД]` Эфемерная PGlite на `127.0.0.1:54329` (хост-Postgres держит 5432, Docker — 5433; в CI порт свободен). Прод-DATABASE_URL отдельный (Railway).
> - `[ОТЛОЖЕНО]` browser/component-тесты boilerplate (`*.test.tsx`, hook-тесты) и тяжёлые auth/visual e2e НЕ перенесены — вернутся с RTL/jsdom на UI-шагах 1.5–1.7 и e2e на 1.16. `pnpm --filter web check:types` зелёный, но web-lint/typecheck в CI-гейт пока НЕ добавлены (гейтим: корневые lint/typecheck/test/coverage + мета-тесты + web build + web e2e-smoke).
> - `[НУМЕРАЦИЯ]` STATE «Шаг P1.1» ≙ роадмап Шаг 1.1 (форк). Роадмап Шаг 1.0 (Railway) — отложен, отдельной строкой в STATE не нумеруется.
> - `[CLERK LIVE — 2026-06-15]` Привязали проект к dev-инстансу FlipHouse через Clerk CLI (`npx clerk auth login` — founder подтвердил в браузере → `clerk link --app app_3F95…` → `clerk env pull`). Реальные dev-ключи (`pk_test…` + `CLERK_SECRET_KEY`) лежат ТОЛЬКО в `apps/web/.env.local` (gitignored). `clerk doctor` зелёный; e2e-smoke поднимается с реальными ключами. Линк хранится в CLI-конфиге по git-remote, не в репо. Воспроизведение на свежем клоне: `clerk auth login && clerk link --app app_3F95… && clerk env pull` из `apps/web`.
> - `[SECURITY — 2026-06-15]` `clerk env pull` по умолчанию пишет в `.env` (трекаемый!), занеся реальный `CLERK_SECRET_KEY`. Поймано ДО коммита: ключи перенесены в `.env.local`, `.env` возвращён к плейсхолдеру, remote чист (коммит `387a786` сделан раньше). Рекомендация founder'у: при желании ротировать dev `sk_test_…` в Clerk-дашборде (значение мелькало в локальном выводе сессии; на GitHub не попадало).
>
> **Заметки исполнителя — P1.2 (2026-06-15):**
> - `[/api/health]` `src/app/api/health/route.ts` (runtime nodejs, force-dynamic) + чистый агрегатор `src/libs/health.ts` (`probeDb` Drizzle `select 1` с таймаутом 1s, `probeRedis`, `buildHealth`). db down → HTTP 503; redis НЕ роняет статус в P1 (только репортится). Живой ответ: `{"status":"ok","db":"up","redis":"down"}`.
> - `[REDIS ОТЛОЖЕН → 1.3]` `probeRedis` пока возвращает `'down'` (реальный ioredis-`Redis.ping()` на `REDIS_PRIVATE_URL` придёт в P1.3, тогда `probeRedis` перепишется). Тесты мокают пробники.
> - `[PROXY]` `src/proxy.ts` matcher теперь исключает `api` (`/((?!_next|_vercel|monitoring|api|.*\\..*).*)`), чтобы `/api/*` не уходил в next-intl-локаль-роутинг/Clerk — healthcheck публичный, без auth.
>
> **Заметки исполнителя — P1.3 (2026-06-15):**
> - `[REDIS SINGLETON]` `src/libs/Redis.ts` — lazy ioredis-синглтон по паттерну `src/libs/DB.ts` (global-cache в dev, `maxRetriesPerRequest:null` для BullMQ-совместимости P2, `lazyConnect:true` чтобы импорт не блокировал boot/LCP, `error`-листенер → `logger.error` против «Unhandled error event»). `ioredis@^5.11.1` добавлен в `apps/web` (та же версия, что в `apps/worker-node`).
> - `[ENV FAIL-FAST]` `REDIS_PRIVATE_URL: z.string().url()` добавлен в `server` T3 Env. Дефолтный `onValidationError` t3-env (v0.13.11) бросает дженерик `"Invalid environment variables"` БЕЗ имени переменной — добавлен кастомный `onValidationError`, перечисляющий проблемные переменные (`issue.path`), чтобы старт без `REDIS_PRIVATE_URL` падал с явным именем. Улучшает fail-fast DX для всех переменных, не только redis.
> - `[probeRedis РЕАЛЬНЫЙ]` `src/libs/health.ts::probeRedis` переписан с заглушки `'down'` на реальный `redis.ping()` под тем же `withTimeout(1s)`, что и `probeDb`. `buildHealth`/route не тронуты — redis по-прежнему НЕ роняет HTTP-статус в P1 (только репортится). Устаревший тест-заглушка в `health.test.ts` заменён на up/down ping-тесты.
> - `[TEST ENV]` `REDIS_PRIVATE_URL` добавлен в `TEST_ENV_DEFAULTS` (`vitest.config.ts`) — иначе новая required-переменная уронила бы ВСЕ web-юнит-тесты на import-time валидации Env. Плейсхолдер `redis://127.0.0.1:6379` добавлен в коммиченный `apps/web/.env` (несекретный; прод — `${{Redis.REDIS_PRIVATE_URL}}` в Railway, P1.14–1.15).
> - `[МОК ioredis]` В `Redis.test.ts` мок ioredis — класс внутри фабрики `vi.mock` (не arrow): ioredis вызывается через `new`, а arrow-функция не конструируется (`Reflect.construct`).
>
> **Заметки исполнителя — P1.4 (2026-06-15):**
> - `[SOURCE OF TRUTH]` Палитра `docs/02` §4 заведена как `apps/web/tokens/{primitives,semantic.dark,non-color}.json` (DTCG `$value`). `style-dictionary@^5.4.4` (dev) генерит `src/styles/tokens.css` + `tokens/COLORS.md` через `apps/web/style-dictionary.config.mjs` (скрипт `pnpm tokens`). Артефакты коммитятся (нужны web-билду через `@import`), но не правятся руками.
> - `[ДЕТЕРМИНИЗМ]` Кастомный CSS-формат `fliphouse/css` БЕЗ timestamp-хедера + `transforms:['name/kebab']` (только имя, без color-transform) → oklch-строки эмитятся verbatim (`--primary: oklch(68% 0.20 280)` посимвольно). Тест `tokens/tokens.test.ts::regenerable and deterministic` гоняет генератор дважды и сверяет байт-в-байт.
> - `[ГРУППИРОВКА БЕЗ filePath]` JSON неймспейснут (`semantic`/`nonColor`/`primitive` = path[0]); имя CSS-переменной = `--${path.slice(1).join('-')}` (напр. `semantic.color.glass`→`--color-glass`). `:root` = dark-палитра + non-color, `.dark` зеркалит цвета (явный класс — belt-and-suspenders). primitives в CSS не эмитятся (только как алиасы). Не завишу от SD-`filePath`.
> - `[DTCG VALUE]` В SD v5 резолвнутое значение DTCG-токена лежит в `token.$value` (не `token.value` — тот `undefined`). Формат читает `token.$value ?? token.value`.
> - `[VITEST INCLUDE]` Тест живёт в `tokens/` (dev-тулинг, вне `src/`); `apps/web/vitest.config.ts` `include` расширен до `['src/**/*.test.ts','tokens/**/*.test.ts']`, иначе корневой агрегат его не подхватит. Генератор вне `src/` → вне `coverage.include` (порог держится тривиально).
> - `[GLOBAL.CSS]` Инлайновые `:root`/`.dark` boilerplate'а удалены, добавлен `@import './tokens.css'`; блок `@theme inline` (маппинг `--color-*`→`var(--*)`) нетронут. tokens.css сохраняет ВСЕ переменные, на которые ссылается `@theme inline` (incl. `--radius`, `--chart-1..5`, `secondary/popover/input/accent/destructive`), чтобы Tailwind-утилиты не сломались.
> - `[ESLINT IGNORE]` `src/styles/tokens.css` и `tokens/COLORS.md` добавлены в `apps/web/eslint.config.mjs` ignores — иначе prettier/better-tailwindcss переформатировали бы генерируемые артефакты и ломали детерминизм.
> - `[BUILD «ЗАВИС»]` `pnpm --filter web build` (pglite-обёртка) после успешной сборки оставляет висеть `pglite-socket`-сервер, не отдавая управление (лог буферизуется и теряется). Проверено прямым `next build`: `✓ Compiled successfully in 2.5s`, статика 10/10, `@import tokens.css` резолвится. Это особенность враппера, не нашего кода; на лифте деплоя (1.14–1.15) учесть graceful-shutdown pglite.
> - `[FIX SHA]` Записанный SHA P1.4 = реальный HEAD ветки `p1.4-design-tokens` на момент закрытия шага. Из-за sha-amend (вписывание SHA в сам коммит математически невозможно) точный HEAD см. `git log -1`; зафиксированный хеш — pre-amend twin того же коммита (паттерн как в P0). Реальный HEAD будет сверен при push после аппрува founder'а.
> - `[PUSH ОТЛОЖЕН]` `git push` упал из-за недоступности github.com:443 (сетевая проблема окружения, не код). Коммит лежит локально на ветке `p1.4-design-tokens`; push повторить, когда сеть вернётся / на аппруве чекпоинта B. (Сеть вернулась, ветка запушена.)
>
> **Заметки исполнителя — P1.4 СМЕНА НАПРАВЛЕНИЯ (2026-06-15 · ЧП B):**
> - `[FOUNDER EDIT — НАПРАВЛЕНИЕ]` На чекпоинте B founder отверг dark-AI-tech (violet/cyan) как «похожее на AI». Через `ultracode`-workflow (24 агента, 12 направлений + adversarial harden) сгенерированы 12 живых HTML-превью в `design-explorations/` (+ `GALLERY.html`). Founder выбрал **«Vibrant Pop / Maximalist»**. Эталон-референс: `design-explorations/vibrant-pop-maximal/index.html`.
> - `[ТОКЕНЫ ПЕРЕГЕНЕРИРОВАНЫ]` `tokens/*.json` переписаны под Vibrant Pop: cream-paper bg + ink, primary hot-pink `oklch(72% 0.21 0)`, ring electric-blue `oklch(64% 0.20 255)`, secondary lime, accent tangerine, grape; `--brand-{pink,lime,blue,tang,grape}` для цветоблокинга; `--shadow-hard`/`-lg` (жёсткие offset-тени). `semantic.dark.json` → `semantic.light.json`. Тип-шкала/радиусы из эталона. Тесты обновлены под новые значения (RED→GREEN). Все гейты зелёные.
> - `[СВЕТЛАЯ БАЗА]` Направление светлое: генератор эмитит только `:root` (без `.dark`); убран `<html class="dark">` из `layout.tsx`. Контраст проверен скриншотом (`design-explorations/_app-recolored.jpeg`): тёмный ink-текст на cream/pink читается (закрывает прошлую претензию founder'а про нечитаемый текст на цветном блоке).
> - `[CONFLICT — P1.5+]` Шаг 1.5 (shadergradient WebGL mesh) и hero-сборка `docs/02` §3/§5 проектировались под dark-mesh — КОНФЛИКТУЮТ с Vibrant Pop (фон героя = cream + наклонённые phone-карточки + цветоблокинг, без WebGL). Помечено `[FOUNDER EDIT]`/`[CONFLICT]` в `roadmap/P1` и банером-решением наверху `docs/02`. Адаптацию 1.5+ НЕ делаю молча — жду решения founder'а на ЧП B.
> - `[ОЧИСТКА]` `design-explorations/` (12 превью + скриншоты + GALLERY) оставлены как референс-материал направления; решить позже, коммитить ли их в репо или держать вне VCS.
>
> **Заметки исполнителя — P1.4 ВТОРОЙ РАЗВОРОТ → Swiss Pop (2026-06-15 · ЧП B):**
> - `[FOUNDER EDIT — НАПРАВЛЕНИЕ #2]` Founder отверг Vibrant Pop как «слишком поверхностно/иишно» + «карточки телефонов не нужны». 2-й раунд: 6 reference-grade концептов (Awwwards/Linear/Stripe-уровень, БЕЗ device-моков, продукт через ранкед-лист/таблицу/тикер) → `design-explorations/round2/` + `GALLERY-v2.html`. Founder выбрал **«Swiss Pop»**. Эталон → `docs/design-reference/swiss-pop.html` (заменил vibrant-pop.html).
> - `[ТОКЕНЫ #2]` `tokens/*.json` переписаны под Swiss Pop: paper `oklch(97.5% 0.004 95)` + ink `oklch(17% 0.012 270)`, primary/pop vermillion `oklch(63% 0.244 26)` (primary-foreground = on-pop-solid `oklch(16% 0.03 26)`, AA на vermillion), secondary cobalt `oklch(48% 0.210 258)`, hairline `--rule` / heavy `--rule-strong`. Добавлены raw-сигналы с именами как в эталоне (`--pop/--cobalt/--ink-soft/--ink-faint/--rule/--rule-strong`) — чтобы P1.5 портировался напрямую. Тесты обновлены RED→GREEN (primary=vermillion, cobalt-сигнал, text-hero `clamp(3.4rem, 1.2rem + 8.6vw, 10.5rem)`). Все гейты зелёные (lint/typecheck 0, test 33/33, coverage 89%).
> - `[ШРИФТЫ — НА P1.5]` Эталон использует Archivo + Archivo Narrow + IBM Plex Mono. Подключение через next/font — в P1.5 (layout-шаг), не в токенах.
> - `[РЕФЕРЕНС = ЯЗЫК, НЕ КОД]` Founder подтвердил: HTML-эталон — пример визуального языка; реальные блоки/секции/контент собираются и переделываются под FlipHouse в P1.5–1.8.

Этот файл — единый источник правды о прогрессе. Исполнитель (ultracode) читает его в начале каждого запуска и обновляет в конце каждого шага. Не удаляй историю — только дописывай статусы.

## Легенда статусов

- ⬜ не начато
- 🟨 в работе
- ✅ готово (тесты зелёные)
- 🛑 ждёт ревью на чекпоинте
- ⛔ заблокировано

## Правило обновления

1. После КАЖДОГО шага исполнитель ставит ✅ + хеш коммита + дату (формат: `✅ <short-sha> · YYYY-MM-DD`).
2. На ЧЕКПОИНТЕ исполнитель ставит 🛑 и **ОСТАНАВЛИВАЕТСЯ — ЖДЁТ ревью**. Не продолжать дальше чекпоинта без явного аппрува.
3. Поле «СЕЙЧАС» наверху всегда указывает на текущий `<phase.step>`.
4. Если шаг заблокирован — ставь ⛔ + одну строку причины и переходи к разблокировке, не молча.
5. Статус фазы = минимальный по всем её шагам и чекпоинтам (всё ✅ → фаза ✅).

---

## P0 — Bootstrap: монорепо, CI, тест-харнесс, vendor-репозитории ✅

**Цель:** Поднять pnpm-монорепо (apps/web, apps/worker-node, services/ai-worker-python, packages/shared), весь тулинг (TypeScript strict / ESLint / Prettier / Ruff / Black) и ПОЛНЫЙ тест-харнесс up front (Vitest + Playwright + pytest + coverage-гейты ≥80%, роняющие билд), CI на GitHub Actions, БЛОКИРУЮЩИЙ красные тесты/покрытие, и завендорить все 11 upstream-репозиториев в /vendor с пинами по SHA — фундамент для founder'ской цели ZERO bugs. Бизнес-кода нет: только леса + один тривиальный проходящий тест на пакет, доказывающий, что харнесс работает end-to-end.

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P0-bootstrap-test-harness.md`
**Зависит от:** —

### Шаги

- ✅ Шаг P0.1 · 654ca13 · 2026-06-15
- ✅ Шаг P0.2 · cd45a5d · 2026-06-15
- ✅ Шаг P0.3 · fd9c2f5 · 2026-06-15
- ✅ Шаг P0.4 · d485bc2 · 2026-06-15
- ✅ Шаг P0.5 · 271b7a8 · 2026-06-15
- ✅ Шаг P0.6 · 794d70f · 2026-06-15
- ✅ Шаг P0.7 · 481bb4f · 2026-06-15 [🛑 ЧЕКПОИНТ C]
- ✅ Шаг P0.8 · 3fb1ef6 · 2026-06-15 [🛑 ЧЕКПОИНТ D]
- ✅ Шаг P0.9 · 10d75c8 · 2026-06-15 [🛑 ЧЕКПОИНТ E]
- ✅ Шаг P0.10 · 08b0b8a · 2026-06-15
- ✅ Шаг P0.11 · 9fdc134 · 2026-06-15 [🛑 ЧЕКПОИНТ F]
- ✅ Шаг P0.12 · b4b0b89 · 2026-06-15
- ➖ Шаг P0.13 — N/A: в `roadmap/P0-*.md` нет такого шага, фаза закрывается на 0.12 (строка-артефакт)

### Чекпоинты

- ✅ ЧП A: структура монорепо + строгий TS-тулинг · одобрено founder'ом (pinned ESLint 9 / TS 5) · 2026-06-15
- ✅ ЧП B: shared зелёный + coverage-гейт реально роняет билд · одобрено founder'ом (порог поднят до 100%) · 2026-06-15
- ✅ ЧП C: golden-video assertion-контракт для рендера · одобрено founder'ом (+ расширен: codec/pixfmt/audio) · 2026-06-15
- ✅ ЧП D: web Playwright smoke + worker-node Vitest зелёные · одобрено founder'ом · 2026-06-15
- ✅ ЧП E: /vendor со всеми 11 репами + PINS.lock + правовая разметка · одобрено founder'ом · 2026-06-15
- ✅ ЧП F: CI блокирует красный PR (fail-fast) + branch protection · CI зелёный на Actions + required job `ci` включён (strict, enforce_admins=false) · founder авторизовал · 2026-06-15

### Ключевые тесты

- `sha256Hex returns deterministic 64-char lowercase hex for given bytes`
- `coverage run fails when an uncovered exported function is added`
- `test_caption_band_overlapping_banner_is_rejected (safe-zone инвариант 1180+420=1600<=1640)`
- `test_detects_overlay_presence_via_pixel_region (golden-video overlay-ассерт)`
- `GET /api/health returns 200 with status ok (Playwright smoke)`
- `ci fails fast when a TS test is red (Playwright-шаг не достигнут)`

---

## P1 — Веб-каркас: auth, биллинг, лендинг с hero-дропзоной 🟨

**Цель:** Поднять и задеплоить на Railway полностью рабочую веб-оболочку FlipHouse: форк ixartz/SaaS-Boilerplate (Next.js App Router + Clerk auth + Stripe subscription + Postgres/Drizzle), приватная сеть Postgres+Redis, два типа аккаунта creator/advertiser с RBAC-разводкой дашбордов, и Lovable-style dark AI-tech лендинг с центрированной hero-дропзоной (Kibo Dropzone + AI Elements PromptInput над shadergradient WebGL-mesh, drag&drop + paste-link + статусы ready/submitted/streaming/error), launch-ui секции, motion + Magic UI + GSAP/Lenis scroll-сторителлинг. Всё через строгий TDD (RED→GREEN→refactor→commit, coverage ≥80%, zero bugs).

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P1-web-auth-billing-landing.md`
**Зависит от:** P0

### Шаги

- ✅ Шаг P1.1 · 87d0b54 · 2026-06-15 [✅ ЧЕКПОИНТ A одобрен · форк SaaS-Boilerplate → apps/web · PR #1 → main]
- ✅ Шаг P1.2 · f68358c · 2026-06-15 [/api/health: db+redis пробы, 200/503, публичный]
- ✅ Шаг P1.3 · 1e3e813 · 2026-06-15 [ioredis-синглтон на REDIS_PRIVATE_URL + Zod env-валидация + реальный probeRedis ping]
- ✅ Шаг P1.4 · 137fd81 · 2026-06-15 [oklch дизайн-токены через Style Dictionary; направление «Swiss Pop» после ЧП B] [✅ ЧЕКПОИНТ B одобрен]
- ⬜ Шаг P1.5 — Swiss Pop: шрифты (Archivo/Archivo Narrow/IBM Plex Mono) + jsdom/RTL + hero-каркас (бумажная сетка, дропзона, ранкед-тизер)
- ⬜ Шаг P1.5
- ⬜ Шаг P1.6
- ⬜ Шаг P1.7
- ⬜ Шаг P1.8
- ⬜ Шаг P1.9
- ⬜ Шаг P1.10
- ⬜ Шаг P1.11
- ⬜ Шаг P1.12
- ⬜ Шаг P1.13
- ⬜ Шаг P1.14
- ⬜ Шаг P1.15
- ⬜ Шаг P1.16
- ⬜ Шаг P1.17

### Чекпоинты

- ✅ ЧП A: база форка поднята, тесты зелёные — одобрено founder'ом («го, открывай PR») · PR #1 смержен в `main` · live sign-in проверен · 2026-06-15
- ✅ ЧП B: дизайн-направление утверждено — **Swiss Pop** (светлая, paper/ink + vermillion/cobalt); 2 раунда дизайн-разведки, founder выбрал и сказал «го» · 2026-06-15
- ⬜ ЧП C: hero-дропзона со всеми состояниями
- ⬜ ЧП D: лендинг целиком (секции + scroll + моушен)
- ⬜ ЧП E: два типа аккаунта + онбординг-развод
- ⬜ ЧП F: Stripe checkout + webhook
- ⬜ ЧП G: задеплоено на staging, e2e зелёные

### Ключевые тесты

- `signup → subscribe → lands on creator dashboard with active plan (Playwright e2e)`
- `submit with a file transitions ready→submitted→streaming and calls onFlip with the file (HeroDropzone component test)`
- `checkout.session.completed sets stripeSubscriptionStatus=active on org (Stripe webhook integration)`
- `rejects request with invalid signature (400) and does not mutate db (Stripe webhook security)`
- `requireAccountType redirects creator away from advertiser dashboard (RBAC unit)`
- `landing meets CWV budget: LCP<2.5s, CLS<0.1, TBT<200ms, JS<150kb (Lighthouse gate)`

---

## P2 — Загрузка + AI-нарезка MVP (openshorts + OpenRouter) на Railway ⬜

**Цель:** Поднять полный CPU-путь: tusd resumable upload → R2 → post-finish hook → BullMQ Flow-DAG (validate→transcode→asr→score→clip→store) → ранжированные вертикальные клипы 9:16 (1080×1920) в дашборде. Движок нарезки вендорится из mutonby/openshorts (main.py), Gemini-выбор хайлайтов свопается на OpenRouter (OpenAI-совместимый адаптер, response_format json_schema strict, роутинг моделей по doc 04). Транскрипция — faster-whisper base/cpu/int8. GPU-тяжёлые стадии (точный ASD/inpainting) заглушены под PHASE3-флагом с CPU-fallback (MediaPipe/blur-pad). Идемпотентность по content-hash на всех уровнях. TDD обязателен, покрытие ≥80%.

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P2-upload-clipping-mvp.md`
**Зависит от:** P0

### Шаги

- ⬜ Шаг P2.1
- ⬜ Шаг P2.2
- ⬜ Шаг P2.3
- ⬜ Шаг P2.4
- ⬜ Шаг P2.5
- ⬜ Шаг P2.6
- ⬜ Шаг P2.7
- ⬜ Шаг P2.8
- ⬜ Шаг P2.9
- ⬜ Шаг P2.10
- ⬜ Шаг P2.11
- ⬜ Шаг P2.12
- ⬜ Шаг P2.13
- ⬜ Шаг P2.14

### Чекпоинты

- ⬜ ЧП A: OpenRouter-адаптер (модели/роуты/JSON-схема/fallback)
- ⬜ ЧП B: Python-движок нарезки на golden-фикстуре (длительность/9:16/ранжирование)
- ⬜ ЧП C: Flow-DAG (порядок стадий/идемпотентность/failure/прогресс)
- ⬜ ЧП D: tusd→R2→hook (реальная загрузка триггерит DAG, леджер)
- ⬜ ЧП E: E2E дашборд (видео в → ранжированные 9:16 клипы видны и играются)

### Ключевые тесты

- `test_score_schema_matches_doc04_contract (OpenRouter JSON-schema контракт)`
- `test_clips_are_vertical_1080x1920 (ffprobe на выходных клипах)`
- `test_stage_is_idempotent_on_content_hash (переиспользование артефакта)`
- `test('flow runs stages in dependency order validate→...→store')`
- `test('post-finish hook enqueues flow with content-hash jobId')`
- `test('upload sample video yields ranked vertical clips in dashboard') (Playwright e2e)`

---

## P3 — Субтитры + speaker-tracking reframe (captacity + LR-ASD) ⬜

**Цель:** Добавить в конвейер две стадии и единый safe-zone-контракт: (1) reframe — LR-ASD на Modal-GPU (submit-and-park через webhook) → asd_frames.json → детерминированный planner (EMA + min-hold 12, лицо выше banner.y) → crop_keyframes.json → FFmpeg-crop в 1080×1920; (2) caption — пропатченный captacity жжёт karaoke-субтитры строго в caption_band и никогда в баннер-полосе; (3) safe_zones.json с CI-инвариантом caption_band ⊂ content_safe ∧ caption_band ∩ banner = ∅ (1180+420=1600 ≤ 1640), примиряющим caption safe-zone с зарезервированной P4-баннер-полосой. DoD: e2e-рендер на фикстуре даёт 1080×1920 mp4 с субтитрами в content-зоне, ноль пикселей в баннере, crop из реального ASD-скоринга; покрытие ≥80%.

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P3-captions-reframe.md`
**Зависит от:** P0, P1, P2

### Шаги

- ⬜ Шаг P3.1
- ⬜ Шаг P3.2
- ⬜ Шаг P3.3
- ⬜ Шаг P3.4
- ⬜ Шаг P3.5
- ⬜ Шаг P3.6
- ⬜ Шаг P3.7
- ⬜ Шаг P3.8
- ⬜ Шаг P3.9
- ⬜ Шаг P3.10
- ⬜ Шаг P3.11
- ⬜ Шаг P3.12
- ⬜ Шаг P3.13
- ⬜ Шаг P3.14
- ⬜ Шаг P3.15

### Чекпоинты

- ⬜ ЧП A: safe_zones.json + CI-инвариант (геометрия зон для P4)
- ⬜ ЧП B: golden-frame — субтитры в content-зоне, ноль пикселей в баннере
- ⬜ ЧП C: ASD→crop→video цепочка (EMA/min-hold/clearance тюнинг)
- ⬜ ЧП D: Modal submit-and-park + webhook HMAC-verify, идемпотентность
- ⬜ ЧП E: e2e — финальный вирусный клип 1080×1920 + субтитры + crop из ASD

### Ключевые тесты

- `test_safezone_invariant.py::test_caption_band_disjoint_from_banner`
- `test_caption_golden.py::test_zero_caption_pixels_in_banner_strip`
- `test_asd_contract.py::test_active_speaker_is_score_gt_zero`
- `test_reframe_planner.py::test_min_hold_12_frames_no_whip_pan`
- `test_e2e_pipeline.py::test_crop_derived_from_asd_scores`
- `test_e2e_pipeline.py::test_final_is_1080x1920_h264`

---

## P4 — Движок офферов + вставка баннера (ТЗ рекла → FFmpeg) ⬜

**Цель:** Поставить детерминированное ядро вставки оффера: JSON Schema 2020-12 ТЗ рекламодателя + Ajv-валидатор, 5-шаговый advertiser intake form (submit→in_review), fail-closed brand-safety гейт (NSFW/violence/face-region/audio-toxicity), чистый rules-engine plan(offer, clip_meta)→PlacementPlan с AABB collision avoidance (баннер никогда поверх caption/active-speaker face) + частотными правилами + dropped[], injection-hardened FFmpeg overlay-кодоген (-filter_complex_script, argv-входы, clamp/whitelist) + MoviePy v2 фолбэк, и попиксельный render-assertion. Heaviest-TDD фаза проекта; coverage ядра ≥95%.

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P4-offer-engine-banner.md`
**Зависит от:** P0, P1, P2

### Шаги

- ⬜ Шаг P4.1
- ⬜ Шаг P4.2
- ⬜ Шаг P4.3
- ⬜ Шаг P4.4
- ⬜ Шаг P4.5
- ⬜ Шаг P4.6
- ⬜ Шаг P4.7
- ⬜ Шаг P4.8
- ⬜ Шаг P4.9
- ⬜ Шаг P4.10
- ⬜ Шаг P4.11
- ⬜ Шаг P4.12
- ⬜ Шаг P4.13
- ⬜ Шаг P4.14
- ⬜ Шаг P4.15
- ⬜ Шаг P4.16
- ⬜ Шаг P4.17

### Чекпоинты

- ⬜ ЧП A: схема оффера + валидатор
- ⬜ ЧП B: advertiser intake form
- ⬜ ЧП C: brand-safety гейт fail-closed
- ⬜ ЧП D: rules-engine PlacementPlan golden
- ⬜ ЧП E: FFmpeg-вставка end-to-end рендер

### Ключевые тесты

- `invalid-offers.test.ts::requires intervalSec/rate/flatAmount/durationMs (if-then rules)`
- `test_spatial.py::test_banner_never_overlaps_caption_safe + test_banner_never_overlaps_speaker_box`
- `test_brand_safety_gate.py::test_analyzer_exception_fails_closed`
- `test_injection.py::test_malicious_headline_cannot_break_graph + test_no_filter_complex_string_arg_used`
- `test_plan_determinism.py::test_plan_matches_golden_for_clip0007 + test_input_hash_stable_across_runs`
- `test_render_assertion.py::test_banner_pixels_present_at_planned_xy_during_window + test_banner_absent_after_window`

---

## P5 — Маркетплейс креатор↔реклама + учёт показов/выплаты ⬜

**Цель:** Поднять полный self-serve двусторонний маркетплейс: advertiser публикует оффер (JSON-схема doc 03 §1) → creator находит/аппрувится/матчится → принятие генерирует impression_unit и детерминированно привязывает оффер к рендеру → клип рендерится с этим баннером → конверсия регистрируется → начисление через clean-room cliq-субстрат (Link→Conversion→Commission, Function/Condition/Effect) → Stripe Connect выплата. Поверх Phase 1 подписок добавлен идемпотентный Stripe usage/metered billing (per-clip/per-render/CPM, no double-charge на ретрае). Impression/CPM attribution v1: creator-OAuth метеринг по дельтам просмотров + трекинг-ссылки + аудит, с честными ограничениями doc 03 §5.4. TDD обязателен, покрытие ≥80%, детерминированные ядра 100%.

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P5-marketplace-attribution.md`
**Зависит от:** P0, P1, P2, P4

### Шаги

- ⬜ Шаг P5.1
- ⬜ Шаг P5.2
- ⬜ Шаг P5.3
- ⬜ Шаг P5.4
- ⬜ Шаг P5.5
- ⬜ Шаг P5.6
- ⬜ Шаг P5.7
- ⬜ Шаг P5.8
- ⬜ Шаг P5.9
- ⬜ Шаг P5.10
- ⬜ Шаг P5.11
- ⬜ Шаг P5.12
- ⬜ Шаг P5.13
- ⬜ Шаг P5.14
- ⬜ Шаг P5.15
- ⬜ Шаг P5.16
- ⬜ Шаг P5.17
- ⬜ Шаг P5.18
- ⬜ Шаг P5.19
- ⬜ Шаг P5.20
- ⬜ Шаг P5.21
- ⬜ Шаг P5.22
- ⬜ Шаг P5.23
- ⬜ Шаг P5.24
- ⬜ Шаг P5.25
- ⬜ Шаг P5.26

### Чекпоинты

- ⬜ ЧП-1 (5.3): схема БД маркетплейса + валидатор оффера
- ⬜ ЧП-2 (5.6): каталог + публикация оффера + brand-safety гейт
- ⬜ ЧП-3 (5.9): browse/apply/match creator
- ⬜ ЧП-4 (5.11): acceptance + impression_unit + детерминированный input_hash
- ⬜ ЧП-5 (5.13): рендер клипа с принятым оффером (golden-fixture)
- ⬜ ЧП-6 (5.16): cliq-субстрат Commission calculator (4 payout-модели)
- ⬜ ЧП-7 (5.19): Stripe usage/metered идемпотентность (no double-charge)
- ⬜ ЧП-8 (5.22): attribution v1 + честные ограничения
- ⬜ ЧП-9 (5.24): Stripe Connect payout + settlement
- ⬜ ЧП-10 (5.26): сквозной e2e + покрытие ≥80%

### Ключевые тесты

- `test('full flow: post offer → apply → accept → render → conversion → payout')`
- `test('idempotency: повтор accept+render+meter не задваивает ни impression_unit, ни usage, ни payout')`
- `test('повторный emitUsage того же события НЕ шлёт второй раз в Stripe')`
- `test('cpm: 50000 показов × visibility 0.4 × rate 120/1000 = 2400, fee 20% → creator 1920')`
- `test('второй снапшот биллит ТОЛЬКО дельту (new - prev), не lifetime')`
- `test_banner_present_in_window`

---

## P6 — Публикация (YT/TikTok/IG анти-блок) + OAuth + PWA + push ⬜

**Цель:** Превратить готовый клип в R2 в опубликованный пост в YouTube/TikTok/Instagram через официальные API: разделить identity (Auth.js v5) и публикационные коннекты (зашифрованная AES-256-GCM таблица SocialConnection); спрятать три несовместимые refresh-модели за getValidAccessToken; публиковать за абстракцией PublishProvider (Ayrshare фаза 1 + direct YT/TikTok/IG); enforced анти-блок чеклист doc 04 §4.3 (срез watermark, нет брендинга FlipHouse, per-platform транскод/метадата, AIGC-лейблы, обязательное human preview+approval, jitter-кадэнс, сохранение FTC-disclosure); PWA на Serwist + DB-backed web-push «нарезки готовы» из вебхука рендера с 404/410-прунингом. TDD на каждом шаге, coverage ≥80% глобально и ≥95% на доменных модулях.

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P6-publishing-pwa.md`
**Зависит от:** P0, P1, P2

### Шаги

- ⬜ Шаг P6.1
- ⬜ Шаг P6.2
- ⬜ Шаг P6.3
- ⬜ Шаг P6.4
- ⬜ Шаг P6.5
- ⬜ Шаг P6.6
- ⬜ Шаг P6.7
- ⬜ Шаг P6.8
- ⬜ Шаг P6.9
- ⬜ Шаг P6.10
- ⬜ Шаг P6.11
- ⬜ Шаг P6.12
- ⬜ Шаг P6.13
- ⬜ Шаг P6.14
- ⬜ Шаг P6.15
- ⬜ Шаг P6.16
- ⬜ Шаг P6.17
- ⬜ Шаг P6.18
- ⬜ Шаг P6.19
- ⬜ Шаг P6.20
- ⬜ Шаг P6.21
- ⬜ Шаг P6.22
- ⬜ Шаг P6.23
- ⬜ Шаг P6.24

### Чекпоинты

- ⬜ ЧП A: Token Vault + getValidAccessToken (шифрование/ротация/key-version)
- ⬜ ЧП B: Connect-флоу YT/TikTok/IG (scope-минимизация, CSRF state, PKCE)
- ⬜ ЧП C: Анти-блок transform-слой (watermark/транскод/метадата/AIGC/branding)
- ⬜ ЧП D: PublishProvider+Ayrshare e2e на staging (preview+approval, частичные отказы)
- ⬜ ЧП E: PWA + web-push из вебхука рендера на staging-устройстве
- ⬜ ЧП F: Direct-провайдеры + аудит-гейтинг (готовность к platform review)

### Ключевые тесты

- `storeDirectTokens writes ciphertext, never plaintext, to DB row`
- `persists rotated refresh token returned by strategy (TikTok case)`
- `output has no opaque pixels in known CapCut watermark region; FTC disclaimer band preserved`
- `per-platform outputs have DIFFERENT file hashes for the same source clip`
- `publishClip throws ApprovalRequiredError when approvalToken missing/invalid`
- `410/404 Gone response prunes the expired subscription row`
- `render webhook handler fires notifyClipsReady with userId+jobId on completion (idempotent)`

---

## P7 — Trust-слой (verified views), масштаб, харднинг, релиз-гейты ⬜

**Цель:** Закрыть три блокера go-live: (1) Trust-слой verified-views — creator-OAuth метеринг просмотров (TikTok/YouTube/IG) → Δviews × banner_visibility_factor → billable_impressions → charge, с anomaly-detection и cross-source аудитом, холдящими settlement; (2) масштаб/харднинг — доказанный под нагрузкой GPU-quota guard (setGlobalConcurrency + concurrency:1), BullMQ backpressure, R2 lifecycle, наблюдаемость (bull-board/pino/алерты), rate-limiting, nonce-CSP + security-заголовки; (3) релиз-гейт как CI-блокер (тесты+coverage+e2e+load+security) и go-live чеклист. Финальный smoke-e2e на весь путь upload→clip→banner→publish→attribution. Всё под founder-rule ZERO bugs через строгий TDD на каждом шаге.

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P7-trust-scale-hardening.md`
**Зависит от:** P0, P1, P2, P4, P5, P6

### Шаги

- ⬜ Шаг P7.1
- ⬜ Шаг P7.2
- ⬜ Шаг P7.3
- ⬜ Шаг P7.4
- ⬜ Шаг P7.5
- ⬜ Шаг P7.6
- ⬜ Шаг P7.7
- ⬜ Шаг P7.8
- ⬜ Шаг P7.9
- ⬜ Шаг P7.10
- ⬜ Шаг P7.11
- ⬜ Шаг P7.12
- ⬜ Шаг P7.13
- ⬜ Шаг P7.14
- ⬜ Шаг P7.15
- ⬜ Шаг P7.16

### Чекпоинты

- ⬜ ЧП A: метеринг-математика (Δviews×visibility, freeze день-90)
- ⬜ ЧП B: anomaly-detection пороги (velocity/flat-then-vertical)
- ⬜ ЧП C: cross-source verified-views аудит ("числа = пол")
- ⬜ ЧП D: GPU-quota guard под нагрузкой + backpressure
- ⬜ ЧП E: security surface (CSP/headers/rate-limit, SW+push+SSE целы)
- ⬜ ЧП F: релиз-гейт как CI-блокер
- ⬜ ЧП G: go-live чеклист + OAuth-аудиты

### Ключевые тесты

- `test('global cap of 2 holds across 5 concurrent workers')`
- `test('charge = deltaViews * visibility / 1000 * cpmRate')`
- `test_flat_then_vertical_spike_is_flagged`
- `test('discrepancy over 15% triggers hold')`
- `test('upload→clip→banner→publish→attribution end-to-end')`
- `test('gate passes only when ALL six checks green')`
