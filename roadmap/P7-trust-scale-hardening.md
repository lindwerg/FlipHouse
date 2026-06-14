# P7 — Trust-слой (verified views), масштаб, харднинг, релиз-гейты

> Финальная фаза перед go-live. Превращаем рабочий пайплайн (upload → clip → banner → publish) в продукт, которому **рекламодатель доверяет платить по CPM**, а инфраструктура **держит burst без переподписки GPU-квоты**. Заканчиваем продакшн-релиз-гейтом и go-live чеклистом.
>
> Версия 1.0 · стек строго из `docs/00–04`. Тестовые инструменты: **TS → Vitest (unit/integration) + Playwright (e2e)**; **Python-воркеры → pytest + golden-file видео-фикстуры**. Любой FFmpeg/рендер-шаг проверяется по выходу (длительность, размеры, frame-hash, наличие оверлея), а не по «процесс завершился».

---

## Цель фазы (Phase goal)

Закрыть три блокера выхода в прод:

1. **Trust-слой (verified views).** Creator-OAuth метеринг просмотров (TikTok Display / YouTube Analytics / IG Graph) → конвертация `Δviews × banner_visibility_factor → billable_impressions → charge`. Anomaly-detection (velocity / flat-then-vertical / cross-source discrepancy) holds settlement до ручного разбора. Это реализация §5 документа `03`.
2. **Масштаб и харднинг.** GPU-quota guard (`setGlobalConcurrency` + `concurrency:1`) под нагрузкой; BullMQ backpressure (pause/resume по queue-depth, scale-to-zero cpu-worker); R2 lifecycle/expiry по prefix (`ingest`/`intermediate`/`clips`); наблюдаемость (bull-board за auth, структурные логи, алерты); rate-limiting на публичных эндпоинтах; CSP + security-заголовки (расширяем `next.config.ts` из `docs/04 §1.4`).
3. **Релиз-гейт + go-live.** Полный прогон тестов зелёный, coverage ≥ порога, e2e на staging, load-test рендер-пайплайна, security-чеклист — как **CI-гейт**, который физически блокирует деплой. Финальный smoke-e2e покрывает весь путь `upload → clip → banner → publish → attribution`.

**Инвариант фазы:** founder's #1 rule — **ZERO bugs**. Каждый шаг — TDD: тест-первым (RED) → минимальная имплементация (GREEN) → рефактор → коммит. Ни один шаг не «готов», пока его тесты не зелёные И coverage-гейт держится.

---

## Зависимости (какие фазы должны быть готовы)

| Нужно из | Что именно используем в P7 |
|---|---|
| **P0 (каркас/Railway)** | `web`, `Postgres`, `Redis`, окружения prod+staging, `railway.json`, healthcheck `/api/health` |
| **P1 (clipping MVP)** | `ai-render-worker`, `bullmq-worker`, tusd→R2, BullMQ-очереди, content-hash идемпотентность |
| **P2 (ad-banner overlay)** | `ad_banner.py`, FFmpeg LGPL-образ, `banner_visibility_factor` (экранное время баннера ÷ длительность клипа) |
| **P4 (маркетплейс)** | `SocialConnection`/`PublishJob`/`PublishTarget` (Prisma, `docs/04 §5.5`), offer-rules engine, payout-модель оффера (`docs/03 §1`), TokenVault |
| **P5/P6 (публикация)** | `PublishProvider` (Ayrshare сегодня), creator-OAuth коннекты (TikTok/YT/IG), refresh-воркер |

> P7 **не строит** OAuth-коннекты заново — он строит **метеринг поверх уже подключённых коннектов** и **гейты поверх работающего пайплайна**.

---

## Репозитории, клонируемые/используемые в этой фазе

Всё — в `/vendor` (lift конкретных файлов) либо как npm/pip-пакеты. Лицензии не блокер — берём лучшее.

```bash
# Наблюдаемость очередей (lift verbatim — docs/01 §5)
pnpm add @bull-board/api @bull-board/express @bull-board/ui
# (bullmq + ioredis уже стоят с P1)

# Rate-limiting на публичных Next-эндпоинтах (Redis-backed, edge-friendly)
pnpm add @upstash/ratelimit @upstash/redis           # работает поверх Railway Redis по REST-shim ИЛИ ioredis-адаптер
git clone https://github.com/animir/node-rate-limiter-flexible vendor/rate-limiter-flexible
#   ^ если хотим чистый ioredis без upstash REST — берём RateLimiterRedis из этого репо

# Security-заголовки / CSP nonce для Next App Router
pnpm add @next-safe/middleware                        # nonce-CSP, strict-dynamic, App-Router-совместим

# Структурные логи + корреляция
pnpm add pino pino-http pino-pretty

# JSON-Schema валидация офферов/метеринг-контрактов (если не стоит с P3/P4)
pnpm add ajv ajv-formats

# Load-test рендер-пайплайна (k6 — бинарь, ставится в CI-образ)
#   brew install k6   |   docker run grafana/k6
git clone https://github.com/grafana/k6 vendor/k6           # только как референс-образец сценариев

# Python-воркеры: метеринг-аномалии и фикстуры
pip install pytest pytest-cov numpy            # numpy для velocity/anomaly-математики
#   ffprobe доступен из FFmpeg-образа P1 — используем для assert на выходе клипа

# Security-аудит зависимостей в релиз-гейте
pnpm add -D @playwright/test                   # уже стоит с e2e P-фаз; фиксируем версию
```

**Что лифтим из vendor:**
- `vendor/rate-limiter-flexible/lib/RateLimiterRedis.js` → паттерн для `web/src/lib/ratelimit/redisLimiter.ts` (если не идём через `@upstash/ratelimit`).
- `vendor/k6/examples/` → шаблон сценария для `loadtest/render-pipeline.js`.
- bull-board, pino, @next-safe/middleware — используются как пакеты, не лифтятся.

---

## Чекпоинты этой фазы (что ревьюит founder между шагами)

- 🛑 **ЧЕКПОИНТ A** (после 7.3) — метеринг-математика: формула `Δviews × visibility → charge` и freeze-на-дне-90. Founder проверяет, что биллим по дельтам, а не по lifetime, и что определение «показа» совпадает с контрактом рекламодателя.
- 🛑 **ЧЕКПОИНТ B** (после 7.5) — anomaly-detection: пороги velocity/flat-then-vertical/discrepancy и поведение hold. Founder калибрует пороги на реальных кривых до того, как они начнут холдить деньги.
- 🛑 **ЧЕКПОИНТ C** (после 7.6) — verified-views OAuth-аудит: cross-source сверка TikTok/IG против публичного YouTube `viewCount`. Founder подтверждает, что «наши числа — это пол» зафиксировано в UI/контракте.
- 🛑 **ЧЕКПОИНТ D** (после 7.9) — GPU-quota guard под нагрузкой: load/concurrency-тест доказывает, что global cap держится при N репликах. Founder решает финальные числа `setGlobalConcurrency`.
- 🛑 **ЧЕКПОИНТ E** (после 7.12) — security surface: CSP/заголовки/rate-limit. Founder проверяет, что ничего не сломалось в SW/push/SSE (CSP не должен убить Serwist worker и EventSource).
- 🛑 **ЧЕКПОИНТ F** (после 7.14) — релиз-гейт как CI-блокер. Founder подтверждает пороги coverage и что гейт реально не пускает красный билд в прод.
- 🛑 **ЧЕКПОИНТ G** (после 7.16) — go-live чеклист. Финальный человеческий апрув перед первым продакшн-деплоем.

---

## Атомарные шаги

Каждый шаг = один git-commit. Формат фиксирован.

---

### Шаг 7.1 — Схема метеринга: таблицы view-снапшотов и billable-показов

- **Цель / DoD.** Postgres-схема, на которой стоит весь trust-слой: `view_snapshot` (time-series просмотров по `publish_target`), `impression_unit` (campaign × placement × clip + `banner_visibility_factor`), `settlement` (помесячные дельты, статус hold/settled). Drizzle/Prisma-миграция применяется в `preDeployCommand`. Без бизнес-логики — только схема + репозиторий-слой с CRUD.
- **Репозитории/команды.** Используем уже стоящий ORM из P0 (Drizzle per `docs/01`/Prisma per `docs/04 §5.5` — следуем тому, что выбрано в P0; в этом плане пишем Drizzle-стиль). Никаких новых клонов.
- **Тесты СНАЧАЛА** (`web/src/db/metering/__tests__/schema.test.ts`, Vitest + ephemeral PG через testcontainers или Railway staging-DB-URL):
  - `test('view_snapshot enforces unique (publishTargetId, capturedAt)')` — двойная вставка того же снапшота → конфликт/no-op.
  - `test('impression_unit stores banner_visibility_factor in [0,1]')` — вставка `1.4` отклоняется CHECK-констрейнтом.
  - `test('settlement defaults status to "accruing" and links to impressionUnit')`.
  - `test('viewSnapshotRepo.insertDelta computes delta from prior snapshot, never negative')` — два снапшота `500 → 1200` дают delta `700`; снапшот `1200 → 1100` (коррекция платформы) даёт delta `0`, не `-100`.
- **Реализация.** `web/src/db/metering/schema.ts` (таблицы + CHECK `banner_visibility_factor BETWEEN 0 AND 1`, `views >= 0`), `web/src/db/metering/repo.ts` (`insertViewSnapshot`, `insertDelta`, `upsertImpressionUnit`, `createSettlement`). Миграция в `web/drizzle/NNNN_metering.sql`. `delta = max(0, current - prior)` — именованная функция `computeViewDelta`.
- **✅ Готово когда.** 4 теста зелёные; миграция применяется на чистой БД и идемпотентна при повторе; coverage пакета `db/metering` ≥ 90%.
- **Commit.** `feat(metering): view_snapshot/impression_unit/settlement schema + repo`

---

### Шаг 7.2 — `banner_visibility_factor` из PlacementPlan (детерминированно)

- **Цель / DoD.** Чистая функция, которая по `PlacementPlan` (артефакт offer-rules engine, `docs/03 §3.6`) и длительности клипа считает `banner_visibility_factor = суммарное_экранное_время_баннера ÷ длительность_клипа`, клампленный в `[0,1]`. Для `persistent` = `1.0`. Это число — множитель биллинга, поэтому оно **детерминированное** и тестируется на golden-планах.
- **Репозитории/команды.** Нет новых. Переиспользуем `PlacementPlan`-тип из P2/P3.
- **Тесты СНАЧАЛА** (`web/src/lib/metering/__tests__/visibility.test.ts`, Vitest):
  - `test('persistent banner over 47.3s clip yields factor 1.0')`.
  - `test('two 5s appearances on 50s clip yields factor 0.2')` — `(5+5)/50`.
  - `test('overlapping windows are unioned, not double-counted')` — окна `[6,11]` и `[9,14]` на 50с-клипе дают `(14-6)/50 = 0.16`, не `0.2`.
  - `test('dropped placements contribute zero visibility')` — план с `dropped[]` и пустым `placements[]` → `0.0`.
  - `test('factor is clamped to 1.0 when windows exceed duration')` (защита от кривого плана).
- **Реализация.** `web/src/lib/metering/visibility.ts`: `computeVisibilityFactor(plan, clipDurationS)` — мёрджит интервалы появлений (union), делит на длительность, клампит. Чисто, без I/O, без часов.
- **✅ Готово когда.** 5 тестов зелёные; функция импортится в repo-слой 7.1; coverage `lib/metering` ≥ 95% (это биллинг — порог выше).
- **Commit.** `feat(metering): deterministic banner_visibility_factor from PlacementPlan`

---

### Шаг 7.3 — Конвертация просмотров → billable-показы → charge

- **Цель / DoD.** Чистая биллинг-функция (`docs/03 §5.3`): `billable_impressions(window) = Δviews × banner_visibility_factor`; `charge = billable_impressions / 1000 × CPM_rate`. Биллим **по дельтам** в окне, не по lifetime. Freeze на дне 90. Учитываем `minViewsToQualify` и `platformFeePct` из оффера. Никакого I/O — вход: снапшоты + оффер-payout, выход: `BillableLine`.
- **Репозитории/команды.** Нет новых.
- **Тесты СНАЧАЛА** (`web/src/lib/metering/__tests__/charge.test.ts`, Vitest):
  - `test('charge = deltaViews * visibility / 1000 * cpmRate')` — `Δ=10_000, vis=0.5, rate=120` → `600`.
  - `test('per_1k_views model bills on confirmed views not impressions')`.
  - `test('no charge before minViewsToQualify reached')` — клип с `420 < 500` просмотров → `charge=0`, статус `pending_qualification`.
  - `test('snapshots after day 90 are frozen and excluded')` — снапшот с `capturedAt` день 91 → дельта не биллится.
  - `test('platformFeePct splits creator payout transparently')` — `charge=600, fee=20%` → `creatorNet=480, platformCut=120`.
  - `test('hybrid model sums flatAmount base + per_1k_views variable')`.
  - `test('exhausted offer (totalBudget reached) emits no further charge')`.
- **Реализация.** `web/src/lib/metering/charge.ts`: `billWindow(snapshots, offerPayout, visibilityFactor, publishedAt, now)` → `{ billableImpressions, charge, creatorNet, platformCut, status }`. Константы: `FREEZE_DAY = 90`, `IMPRESSION_DIVISOR = 1000`. Деньги — в minor units (копейки), без float-накопления.
- **✅ Готово когда.** 7 тестов зелёные; coverage `lib/metering` ≥ 95%; ручной чек: прогнать пример NitroGG-оффера (`docs/03 §1.2`, `per_1k_views, rate=120, fee=20`) и сверить число руками.
- **Commit.** `feat(metering): views→billable_impressions→charge with day-90 freeze`

🛑 **ЧЕКПОИНТ A:** founder ревьюит метеринг-математику — биллим по дельтам (не lifetime), freeze день 90, определение «показа» = `Δviews × visibility`. Может изменить `FREEZE_DAY`, divisor, трактовку hybrid, формулу `creatorNet` до того, как это начнёт двигать реальные деньги.

---

### Шаг 7.4 — Метеринг-поллер: затухающее расписание опроса просмотров

- **Цель / DoD.** BullMQ-джоб `meter`, который по затухающему расписанию (`docs/03 §5.2 шаг 4`: hourly день 1 → 4×/день до дня 7 → daily до дня 30 → weekly до дня 90 → freeze) опрашивает per-video просмотры через `PublishProvider`/коннект и пишет `view_snapshot`. Сам провайдер-вызов мокается (реальные API — в P5/P6); здесь тестируем **расписание и идемпотентность снапшота**, не сеть.
- **Репозитории/команды.** Переиспользуем BullMQ (`taskforcesh/bullmq`, уже vendored P1) + repo из 7.1.
- **Тесты СНАЧАЛА** (`web/src/queues/__tests__/meter.scheduler.test.ts`, Vitest, fake timers):
  - `test('schedules hourly on day 1')` — `publishedAt=now`, next-run через ~1ч.
  - `test('schedules 4x/day on days 2-7')`.
  - `test('schedules weekly on days 31-90')`.
  - `test('returns null next-run after day 90 (freeze)')` — джоб не перепланируется.
  - `test('meter job is idempotent on retry: same snapshot not double-inserted')` — повтор того же `(publishTargetId, capturedAt)` → repo no-op (использует 7.1 unique-констрейнт).
  - `test('provider 429 reschedules with backoff, does not crash worker')` — мок кидает 429 → джоб `delay`, не `failed`.
- **Реализация.** `web/src/queues/meter.ts`: `nextMeterRun(publishedAt, now)` → `Date | null` (чистая, тестируемая отдельно), воркер-хендлер `processMeterJob` (вызывает мокаемый `provider.getViewCount`, пишет снапшот, репланирует через `queue.add(..., { delay })`). Без блокировки воркера — провайдер-вызов короткий read.
- **✅ Готово когда.** 6 тестов зелёные; `nextMeterRun` покрыт на всех граничных днях (1, 2, 7, 8, 30, 31, 90, 91); coverage `queues/meter` ≥ 90%.
- **Commit.** `feat(metering): decaying-cadence view poller with idempotent snapshots`

---

### Шаг 7.5 — Anomaly-detection: velocity / flat-then-vertical / impossible-growth

- **Цель / DoD.** Чистый детектор аномалий на time-series снапшотов (`docs/03 §5.2 шаг 6`). Три сигнала: (1) **velocity** — рост физически невозможный (Δviews/Δt выше потолка платформы); (2) **flat-then-vertical** — плоская кривая, затем вертикальный скачок (куплены просмотры); (3) детектор возвращает `{ anomalous: bool, signal, score }`. Аномалия → `settlement` уходит в `hold`, биллинг продолжает копить, но не платит.
- **Репозитории/команды.** Python-сайд (математика живёт рядом с воркером): `pip install numpy pytest pytest-cov`. (Если метеринг целиком в TS — зеркалим в `web/src/lib/metering/anomaly.ts` теми же кейсами; план показывает Python-вариант, т.к. это data-математика.)
- **Тесты СНАЧАЛА** (`worker/fliphouse/metering/test_anomaly.py`, pytest, golden time-series фикстуры в `worker/tests/fixtures/views/`):
  - `test_organic_decay_curve_is_not_flagged` — нормальная вирусная кривая (быстрый рост → плато) → `anomalous=False`.
  - `test_flat_then_vertical_spike_is_flagged` — `[100,105,108,110, 50000]` → `signal='flat_then_vertical'`.
  - `test_physically_impossible_velocity_is_flagged` — 1M просмотров за 60с на канале с 5k подписчиков → `signal='velocity'`.
  - `test_monotonic_correction_does_not_flag` — платформа скорректировала вниз `1200→1180` → не аномалия (это §5.4 «view-фрод реален, но коррекции бывают»).
  - `test_threshold_is_configurable_per_platform` — TikTok-потолок ≠ YouTube-потолок.
  - `test_anomaly_score_monotonic_in_severity` — больше отклонение → больше score.
- **Реализация.** `worker/fliphouse/metering/anomaly.py`: `detect_anomaly(snapshots, platform_caps) -> AnomalyResult`. numpy для производных/окон. Пороги — в `PLATFORM_VELOCITY_CAPS` (именованные константы, не magic numbers). Чисто, детерминированно.
- **✅ Готово когда.** 6 тестов зелёные; фикстуры покрывают organic/fraud/correction; coverage `metering/anomaly` ≥ 90%; ручной чек на 2–3 реальных экспортированных кривых.
- **Commit.** `feat(metering): anomaly detection (velocity/flat-then-vertical) holds settlement`

🛑 **ЧЕКПОИНТ B:** founder калибрует пороги (`PLATFORM_VELOCITY_CAPS`, flat-then-vertical чувствительность) на реальных кривых. Решает, какой `score` триггерит hold vs review. Подтверждает: коррекции вниз не флагаются, иначе ложно холдим честных креаторов.

---

### Шаг 7.6 — Verified-views аудит: cross-source сверка против публичного YouTube

- **Цель / DoD.** Аудит-слой (`docs/03 §5.2 шаг 6`, §5.4 п.4): сверяем OAuth-`view_count` против **единственного независимого источника** — публичного YouTube `videos.list.statistics.viewCount` (без auth). `discrepancy > порога (15%)` → `hold settlement` + флаг ручного разбора. Для TikTok/IG независимого cross-check нет — для них аудит = только velocity/watermark (фиксируем это в коде как «no independent source»).
- **Репозитории/команды.** YouTube Data API `videos.list` (публичный, 1 unit) — клиент из P6. Здесь — детектор расхождений, сетевой вызов мокается.
- **Тесты СНАЧАЛА** (`web/src/lib/metering/__tests__/audit.test.ts`, Vitest):
  - `test('discrepancy under 15% passes audit')` — OAuth `10_000` vs public `9_500` → `ok`.
  - `test('discrepancy over 15% triggers hold')` — OAuth `10_000` vs public `7_000` → `hold`, `reason='oauth_public_discrepancy'`.
  - `test('tiktok/instagram have no independent cross-source')` — аудит TikTok возвращает `independentSource=false`, не пытается сверять.
  - `test('audit failure is fail-open for billing but flags review')` — публичный YouTube недоступен → биллинг не блокируется, но `auditStatus='unverified'` (это §5.4: аудит не блокирует биллинг).
  - `test('hold from audit composes with anomaly hold (max severity wins)')`.
- **Реализация.** `web/src/lib/metering/audit.ts`: `auditViewCount({ oauthViews, publicYoutubeViews?, platform })` → `{ auditStatus, discrepancyPct, hold, reason }`. Константа `DISCREPANCY_THRESHOLD = 0.15`. Композиция с anomaly-результатом из 7.5.
- **✅ Готово когда.** 5 тестов зелёные; coverage `lib/metering` держит ≥ 95%; ручной чек: реальное видео — OAuth-число vs публичный `viewCount`.
- **Commit.** `feat(metering): cross-source view audit (public YouTube) gates settlement`

🛑 **ЧЕКПОИНТ C:** founder подтверждает позиционирование «наши числа — это пол» (§5.4 п.2) зашито в UI/контракт; `DISCREPANCY_THRESHOLD`; и что TikTok/IG честно помечены как «без независимого источника». Это про доверие рекламодателя — главный ров.

---

### Шаг 7.7 — Settlement-машина: helds, разрешение, помесячный расчёт

- **Цель / DoD.** State-machine `settlement`: `accruing → (hold | settled)`, hold снимается ручным разбором или авто-resolve по затуханию аномалии. Помесячный расчёт по накопленным дельтам (`docs/03 §5.3`). Любой клип с флагом аудита/аномалии — на hold, не платится. Интеграция repo (7.1) + charge (7.3) + anomaly (7.5) + audit (7.6).
- **Репозитории/команды.** Нет новых.
- **Тесты СНАЧАЛА** (`web/src/services/__tests__/settlement.test.ts`, Vitest, integration с ephemeral PG):
  - `test('clean clip settles monthly on accumulated deltas')`.
  - `test('anomaly-flagged clip stays on hold, never auto-settles')`.
  - `test('audit-discrepancy clip stays on hold until manual resolve')`.
  - `test('manual resolve(hold→settled) requires reviewer id, is audited')` — запись в audit-log кто снял hold.
  - `test('settlement is idempotent: re-running month does not double-pay')` — повторный `settleMonth` для уже settled периода → no-op.
  - `test('partial: some targets held, others settled in same job')` — частичный расчёт first-class.
- **Реализация.** `web/src/services/settlement.ts`: `settleMonth(period)` сканит `impression_unit`, считает charge, проверяет anomaly+audit holds, пишет `settlement` со статусом. `resolveHold(settlementId, reviewerId, decision)`. Идемпотентность по `(impressionUnitId, period)` unique.
- **✅ Готово когда.** 6 тестов зелёные; coverage `services/settlement` ≥ 90%; миграция audit-log применена.
- **Commit.** `feat(metering): settlement state-machine with hold/resolve + monthly idempotent run`

---

### Шаг 7.8 — GPU-quota guard: интеграционный тест, что global cap держится

- **Цель / DoD.** Доказать тестом (не на словах), что `Queue.setGlobalConcurrency(2)` + per-worker `concurrency:1` (`docs/01 §5`, инвариант 5) **никогда не пускает >2 GPU-джоба одновременно**, даже когда поднято N воркеров/реплик. Это load/concurrency-тест, который **держит GPU-квоту** — прямое требование промпта.
- **Репозитории/команды.** BullMQ (vendored P1) + Railway Redis (или локальный Redis в CI). `ioredis` уже стоит.
- **Тесты СНАЧАЛА** (`worker/src/__tests__/gpu-quota.integration.test.ts`, Vitest, реальный Redis):
  - `test('global concurrency cap holds across 1 worker')` — 10 джоб, `concurrency:1`, observed max-in-flight `== 1`.
  - `test('global cap of 2 holds across 5 concurrent workers')` — поднять 5 Worker-инстансов на ту же `gpu-asr` очередь, закинуть 50 джоб; счётчик «активных одновременно» (атомарный Redis INCR/DECR в самом джоб-хендлере) **никогда не превышает 2**. Это ядро теста.
  - `test('worker concurrency does not override global cap')` — воркер с `concurrency:10` + `setGlobalConcurrency(2)` → max-in-flight всё равно `2` (docs подтверждают: global — потолок).
  - `test('GPU job failure releases the global slot')` — упавший джоб не «залипает» в слоте; следующий стартует.
  - `test('rate-limited (429 from provider) job does not consume a permanent slot')` — `RateLimitError` + `worker.rateLimit()` освобождает слот корректно.
- **Реализация.** `worker/src/queues/gpuQueue.ts`: фабрика очереди с `setGlobalConcurrency`, хендлер инкрементит/декрементит Redis-счётчик `gpu:inflight` и пишет наблюдённый максимум в `gpu:inflight:max` для ассерта. Тест-харнесс поднимает несколько Worker, ждёт drain, читает max.
- **✅ Готово когда.** 5 тестов зелёные на реальном Redis; observed max строго ≤ global cap во всех кейсах; тест помечен как обязательный в релиз-гейте (7.14).
- **Commit.** `test(gpu): integration proof global concurrency cap holds under N workers`

---

### Шаг 7.9 — BullMQ backpressure: pause/resume по queue-depth + scale-to-zero

- **Цель / DoD.** Backpressure-контроллер: когда `gpu-*` очереди переполнены (depth > high-watermark) — паузим upstream `cpu`-энкью, чтобы не копить незавершаемую работу; resume при depth < low-watermark. Плюс scale-to-zero сигнал для `cpu-worker` между бёрстами (`docs/01 §6` «idle → только volume», §7 рычаги стоимости). Orchestrator (`min:1`) никогда не паузится (иначе parent залипнет в `waiting-children`).
- **Репозитории/команды.** BullMQ `queue.pause()/resume()`, `getJobCounts()`. Нет новых клонов.
- **Тесты СНАЧАЛА** (`worker/src/__tests__/backpressure.test.ts`, Vitest, реальный Redis):
  - `test('pauses upstream cpu queue when gpu depth exceeds high watermark')`.
  - `test('resumes upstream when gpu depth drops below low watermark')` — гистерезис, не флаппинг на одном пороге.
  - `test('orchestrate queue is never paused by backpressure')` — защита от deadlock parent.
  - `test('scale-to-zero signal emitted only when cpu queue empty AND no active jobs')`.
  - `test('hysteresis prevents pause/resume thrash at boundary')` — depth колеблется вокруг порога → не дёргает pause/resume каждый тик.
- **Реализация.** `worker/src/backpressure.ts`: `BackpressureController` с `HIGH_WATERMARK`/`LOW_WATERMARK` (именованные), периодический `getJobCounts`, `pauseUpstream`/`resumeUpstream`, эмит `scale-to-zero` события (читается Railway-автоскейл-хуком/cron). Whitelist «непаузимых» очередей: `orchestrate`.
- **✅ Готово когда.** 5 тестов зелёные; гистерезис доказан тестом; coverage `worker/backpressure` ≥ 90%; ручной чек: засыпать 200 джоб, увидеть pause→drain→resume в bull-board (7.10).
- **Commit.** `feat(queues): backpressure controller (pause/resume + scale-to-zero) with hysteresis`

🛑 **ЧЕКПОИНТ D:** founder ревьюит GPU-quota guard под нагрузкой (7.8) + backpressure (7.9) вместе. Решает финальные числа `setGlobalConcurrency(N)`, high/low watermark, и подтверждает, что автоскейл Railway не может переподписать фиксированный GPU-пул на fal/Modal.

---

### Шаг 7.10 — Наблюдаемость: bull-board за auth + структурные логи + алерты

- **Цель / DoD.** `bull-board`-сервис (read-only дашборд всех очередей, `docs/01 §7`) за basic/session-auth; структурные логи (`pino`) с корреляцией по `jobId`/`contentHash`; алерт-хуки на (а) GPU-слот залип, (б) settlement-hold открыт >24ч, (в) DLQ-рост, (г) error-rate spike. Алерты — в лог + webhook (Railway/Slack), не молчат.
- **Репозитории/команды.**
  ```bash
  pnpm add @bull-board/api @bull-board/express @bull-board/ui pino pino-http
  ```
- **Тесты СНАЧАЛА** (`observability/__tests__/bullboard.test.ts` + `logger.test.ts`, Vitest + Supertest):
  - `test('bull-board route returns 401 without auth')` — голый GET → 401.
  - `test('bull-board route returns 200 with valid session')`.
  - `test('bull-board is read-only: no retry/remove mutations exposed')` — POST на job-mutation → 403/405.
  - `test('logger attaches jobId and contentHash to every render-pipeline log line')` — лог-запись содержит корреляционные поля.
  - `test('alert fires when settlement hold older than 24h')` — мок-часы +25ч → алерт-вызов.
  - `test('alert fires on DLQ growth above threshold')`.
- **Реализация.** `observability/bullboard.ts` (Express-адаптер, auth-middleware, все очереди read-only), `observability/logger.ts` (pino + child-logger по `jobId`), `observability/alerts.ts` (`checkAlerts()` cron: stuck-slot, stale-hold, DLQ, error-rate → webhook). Логи без секретов/PII.
- **✅ Готово когда.** 6 тестов зелёные; bull-board открывается за auth на staging; алерт реально приходит на тестовый webhook; coverage `observability` ≥ 85%.
- **Commit.** `feat(observability): authed bull-board + pino structured logs + alert hooks`

---

### Шаг 7.11 — R2 lifecycle/expiry по prefix (ingest/intermediate/clips)

- **Цель / DoD.** Конфигурация R2-lifecycle (`docs/01 §4`): `ingest/` — abort incomplete MPU >1d, delete >2d; `intermediate/` — delete >3d; `clips/` — Standard→Infrequent Access после 90d. Применяется как код (S3 `PutBucketLifecycleConfiguration`), идемпотентно, с дрифт-детектом. Плюс ручной reaper-джоб для объектов вне lifecycle (orphaned `intermediate` без parent-клипа).
- **Репозитории/команды.** `@aws-sdk/client-s3` (уже с P1 для R2). Нет новых клонов.
- **Тесты СНАЧАЛА** (`web/src/lib/r2/__tests__/lifecycle.test.ts`, Vitest, мок S3-клиент или MinIO-контейнер):
  - `test('lifecycle config has rule per prefix (ingest/intermediate/clips)')` — собранный конфиг содержит 3 правила с правильными `Prefix`.
  - `test('ingest rule aborts incomplete MPU after 1 day')` — `AbortIncompleteMultipartUpload.DaysAfterInitiation == 1`.
  - `test('intermediate rule deletes after 3 days')`.
  - `test('clips rule transitions to IA after 90 days, never deletes')` — у `clips` нет `Expiration`.
  - `test('applyLifecycle is idempotent: re-apply does not duplicate rules')`.
  - `test('reaper deletes orphaned intermediate objects without parent clip')` — мок: `intermediate/job123/` без записи в БД → удаляется; с записью → нет.
- **Реализация.** `web/src/lib/r2/lifecycle.ts`: `buildLifecycleConfig()` (чистая, возвращает правила), `applyLifecycle(s3)` (идемпотентный put), `reapOrphans(s3, db)` (cron). Константы `INGEST_DELETE_DAYS=2`, `INTERMEDIATE_DELETE_DAYS=3`, `CLIPS_IA_DAYS=90`.
- **✅ Готово когда.** 6 тестов зелёные; конфиг применён на staging-R2; coverage `lib/r2/lifecycle` ≥ 90%; ручной чек: загруженный orphan удаляется reaper'ом.
- **Commit.** `feat(r2): prefix-driven lifecycle (expiry/IA-transition) + orphan reaper`

---

### Шаг 7.12 — Rate-limiting + CSP/security-заголовки (харднинг публичной поверхности)

- **Цель / DoD.** (1) Rate-limit на всех публичных мутирующих эндпоинтах (`/api/offers`, `/connect/*`, publish, SSE-подписка) — Redis-backed, per-IP + per-user. (2) Расширить `next.config.ts` (`docs/04 §1.4`) до полного security-набора: **nonce-CSP** (`script-src 'self' 'nonce-…'`, не `unsafe-inline`), HSTS, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, `X-Frame-Options`. CSP не должен сломать Serwist SW, web-push, SSE/EventSource.
- **Репозитории/команды.**
  ```bash
  pnpm add @upstash/ratelimit @upstash/redis @next-safe/middleware
  git clone https://github.com/animir/node-rate-limiter-flexible vendor/rate-limiter-flexible
  ```
  (Берём `RateLimiterRedis` из vendor, если идём через чистый ioredis вместо upstash REST.)
- **Тесты СНАЧАЛА** (`web/src/middleware/__tests__/ratelimit.test.ts` + `security-headers.test.ts`, Vitest + Supertest/Playwright):
  - `test('offer create returns 429 after N requests in window')` — N+1-й запрос за окно → 429 + `Retry-After`.
  - `test('rate limit is per-user not just per-IP')` — два юзера за одним IP не блокируют друг друга.
  - `test('SSE progress endpoint is rate-limited per connection')`.
  - `test('response has CSP header with per-request nonce')` — два запроса → разные nonce.
  - `test('CSP allows self + nonce, forbids unsafe-inline scripts')`.
  - `test('HSTS/nosniff/frame-deny/referrer/permissions headers present')` — табличная проверка всех заголовков из `security.md`.
  - `test('CSP does not block service worker, web-push, or EventSource')` — `connect-src`/`worker-src` включают нужное; e2e: SW регистрируется, SSE коннектится под CSP.
- **Реализация.** `web/src/middleware.ts`: rate-limit (sliding window, Redis) + `@next-safe/middleware` nonce-CSP. `web/next.config.ts`: достроить `headers()` до полного набора (`docs/web/security.md`). Nonce пробрасывается в `<script nonce>`. `worker-src 'self'`, `connect-src 'self' https://openrouter.ai https://*.r2.cloudflarestorage.com` (+ SSE same-origin).
- **✅ Готово когда.** 7 тестов зелёные; e2e подтверждает SW+push+SSE живут под CSP; Lighthouse/security-scan без CSP-warnings; coverage `middleware` ≥ 85%.
- **Commit.** `feat(security): redis rate-limiting + nonce-CSP + full security headers`

🛑 **ЧЕКПОИНТ E:** founder проверяет security surface — CSP/HSTS/rate-limit. Критично: CSP не убил Serwist worker, web-push и EventSource-прогресс. Founder калибрует rate-limit-окна (не задушить легитимный batch-публишинг) и CSP-allowlist (OpenRouter, R2, Ayrshare).

---

### Шаг 7.13 — Smoke-e2e: весь путь upload → clip → banner → publish → attribution

- **Цель / DoD.** Один Playwright e2e на staging, проходящий **весь путь** (требование промпта): загрузка длинного видео (tus) → нарезка клипа → вставка баннера (offer) → публикация (mock/sandbox PublishProvider) → регистрация `impression_unit` → один meter-снапшот → расчёт `charge`. Ассерты на **выход**, не «дошло»: клип `1080×1920`, длительность ≤180с, баннер-оверлей присутствует (frame-hash diff в banner-band), attribution-строка содержит ненулевой `banner_visibility_factor`.
- **Репозитории/команды.** Playwright (стоит). Видео-фикстура `e2e/fixtures/sample-long.mp4` (короткое, детерминированное — 30с тест-клип). PublishProvider в sandbox-режиме (Ayrshare sandbox/мок).
- **Тесты СНАЧАЛА** (`e2e/full-pipeline.spec.ts`, Playwright):
  - `test('upload→clip→banner→publish→attribution end-to-end')` — главный smoke, шаги через UI/API.
  - Ассерты внутри: `expect(clip.width).toBe(1080)`, `expect(clip.height).toBe(1920)`, `expect(clip.durationS).toBeLessThanOrEqual(180)`, `expect(bannerBandFrameHash).not.toBe(baseClipBandHash)` (баннер реально в кадре), `expect(impressionUnit.bannerVisibilityFactor).toBeGreaterThan(0)`, `expect(charge).toBeGreaterThanOrEqual(0)`.
  - `test('published clip carries required FTC disclosure in caption')` — `docs/03`: `requiredDisclosure` несъёмен.
  - `test('clip with no safe banner slot drops banner but still publishes')` — collision-policy путь (clip без баннера всё равно доходит до publish).
- **Реализация.** `e2e/full-pipeline.spec.ts` + helper `e2e/helpers/pipeline.ts` (драйвит tus-upload, поллит SSE до готовности, читает clip-meta из API, вычисляет frame-hash banner-band через ffprobe/ffmpeg в helper). Python-сайд: golden-фикстура + `ffprobe` ассерты переиспользуются из P2-тестов.
- **✅ Готово когда.** 3 e2e зелёные на staging; smoke стабилен (нет flaky-timeout — детерминированные waits на SSE-событиях, не `sleep`); прогон <10 мин.
- **Commit.** `test(e2e): full pipeline smoke upload→clip→banner→publish→attribution`

---

### Шаг 7.14 — Load-test рендер-пайплайна (k6) + порог-ассерты

- **Цель / DoD.** k6-сценарий, льющий конкурентные рендер-джобы в пайплайн на staging, с **ассертами-порогами** (`docs/01 §6` стоимость/конкурентность): p95 latency клипа, throughput клипов/мин, и — критично — **GPU global cap не превышен под нагрузкой** (читаем `gpu:inflight:max` из 7.8 после прогона). Load-test — обязательная часть релиз-гейта.
- **Репозитории/команды.**
  ```bash
  git clone https://github.com/grafana/k6 vendor/k6     # референс сценариев
  # k6 бинарь в CI: brew install k6 / docker run grafana/k6
  ```
- **Тесты СНАЧАЛА** (`loadtest/render-pipeline.js`, k6 `thresholds` = ассерты):
  - `thresholds: { 'http_req_duration{stage:enqueue}': ['p95<2000'] }` — энкью не тормозит под нагрузкой.
  - `thresholds: { 'clip_render_duration': ['p95<90000'] }` — p95 рендера клипа < 90с (запас над ~30с wall-clock из `docs/01 §6`).
  - `thresholds: { 'gpu_inflight_max': ['value<=2'] }` — кастомная метрика: global cap держится под load (связка с 7.8).
  - `thresholds: { 'checks': ['rate>0.99'] }` — ≥99% джоб дошли до final clip в R2.
  - Сценарий: ramp 1→20→50 VU, каждый VU энкьюит рендер, поллит до готовности, проверяет clip в R2.
- **Реализация.** `loadtest/render-pipeline.js`: setup (auth, fixture-upload), VU-итерация (enqueue→poll→assert R2-object), `handleSummary` пишет `loadtest/results.json`. CI-обёртка `scripts/loadtest.sh` запускает k6, фейлит билд при нарушении threshold.
- **✅ Готово когда.** k6-прогон на staging проходит все thresholds; `gpu_inflight_max<=2` подтверждён под 50 VU; результаты в `loadtest/results.json`; скрипт фейлит при превышении.
- **Commit.** `test(load): k6 render-pipeline load test with GPU-cap & latency thresholds`

---

### Шаг 7.15 — Релиз-гейт как CI-блокер (тесты + coverage + e2e + load + security)

- **Цель / DoD.** Единый CI-гейт (`.github/workflows/release-gate.yml` или Railway pre-deploy), который **физически блокирует прод-деплой**, если не выполнено всё: (1) весь unit/integration зелёный; (2) coverage ≥ порога (TS ≥85% / биллинг-модули ≥95% / Python-метеринг ≥90%); (3) e2e на staging зелёный (7.13); (4) load-test thresholds пройдены (7.14); (5) security-чеклист (CSP/headers/rate-limit тесты 7.12 + `pnpm audit`/`pip-audit` без HIGH/CRITICAL); (6) GPU-quota integration (7.8) зелёный. Это формализация `docs/web/testing.md` приоритетов и founder-rule «ZERO bugs».
- **Репозитории/команды.** GitHub Actions / Railway `preDeployCommand`. `pnpm audit`, `pip-audit`.
- **Тесты СНАЧАЛА** (`scripts/__tests__/release-gate.test.ts` — тестируем сам гейт-скрипт):
  - `test('gate fails when any unit suite is red')`.
  - `test('gate fails when coverage below threshold')` — мок-coverage 84% при пороге 85% → exit≠0.
  - `test('gate fails when e2e smoke red')`.
  - `test('gate fails when load thresholds breached')` — `results.json` с `gpu_inflight_max=3` → fail.
  - `test('gate fails on HIGH/CRITICAL dependency vuln')`.
  - `test('gate passes only when ALL six checks green')`.
- **Реализация.** `scripts/release-gate.ts`: оркестрирует 6 проверок, агрегирует, exit-code. `release-gate.yml`: матрица (TS-tests, py-tests, e2e, load, security-scan, gpu-integration) → all-green required. Branch protection: нельзя мерджить/деплоить в `production` без зелёного гейта. Coverage-пороги в `vitest.config.ts` (`coverage.thresholds`) и `pytest.ini` (`--cov-fail-under`).
- **✅ Готово когда.** 6 тестов гейт-скрипта зелёные; гейт реально блокирует красный билд (проверено намеренным провалом одного теста); зелёный путь деплоит; coverage-пороги enforced в конфигах.
- **Commit.** `ci(release-gate): block prod deploy on tests/coverage/e2e/load/security`

🛑 **ЧЕКПОИНТ F:** founder подтверждает пороги coverage (особенно ≥95% на биллинг-модулях), что все 6 проверок обязательны, и что гейт **физически** не пускает красный билд в `production`. Это последний технический барьер перед go-live.

---

### Шаг 7.16 — Go-live чеклист + production-readiness прогон

- **Цель / DoD.** Исполняемый go-live чеклист (`docs/web/deployment-patterns` + все anti-block из `docs/04 §3.4/§4.3`): прод-секреты présents (VAPID, OPENROUTER, R2-креды, KMS, Stripe Connect), OAuth-аудиты пройдены (YouTube API compliance audit, TikTok audit, Meta App Review), миграции применены, healthcheck зелёный, lifecycle применён, алерты подключены, rate-limit/CSP live. Чеклист — машинно-проверяемый скрипт + человеческий апрув-гейт.
- **Репозитории/команды.** Нет новых. Railway MCP/`railway` CLI для env-проверок.
- **Тесты СНАЧАЛА** (`scripts/__tests__/golive-check.test.ts`, Vitest):
  - `test('fails if any required prod env var missing')` — нет `VAPID_PRIVATE_KEY` → fail с явным именем.
  - `test('fails if migrations not applied (pending count > 0)')`.
  - `test('fails if /api/health not 200 on prod URL')`.
  - `test('fails if R2 lifecycle config drifted from expected')` — переиспользует 7.11.
  - `test('warns (not blocks) on OAuth audit flags that are manual')` — YouTube/TikTok/Meta audits = manual checklist items, скрипт их перечисляет для человека.
  - `test('golive-check exits 0 only when all automated checks pass')`.
- **Реализация.** `scripts/golive-check.ts`: env-presence, миграции (`drizzle-kit`/`prisma migrate status`), health-probe, lifecycle-drift (из 7.11), затем печатает manual-checklist (OAuth-аудиты, anti-block gating из `docs/04`). `roadmap/GO-LIVE-CHECKLIST.md` — человеческая версия с чекбоксами (см. ниже).
- **✅ Готово когда.** 6 тестов зелёные; `golive-check` зелёный на staging-имитации прода; manual-чеклист заполнен и подписан founder'ом.
- **Commit.** `chore(golive): production-readiness check script + go-live checklist`

🛑 **ЧЕКПОИНТ G:** founder проходит go-live чеклист руками — OAuth-аудиты (YouTube compliance / TikTok / Meta App Review реально approved), секреты, алерты, фолбэки. Финальный человеческий апрув. После этого — первый продакшн-деплой.

---

## Go-Live чеклист (человеческая версия — `roadmap/GO-LIVE-CHECKLIST.md`)

**Trust / метеринг**
- [ ] `view_snapshot`/`impression_unit`/`settlement` миграции в prod
- [ ] Метеринг-поллер запущен, затухающее расписание активно
- [ ] Anomaly-detection пороги откалиброваны (ЧЕКПОИНТ B)
- [ ] Cross-source аудит включён; «наши числа — это пол» в UI/контракте (ЧЕКПОИНТ C)
- [ ] Settlement holds блокируют выплату до ручного разбора

**Масштаб / харднинг**
- [ ] `setGlobalConcurrency` финальные числа (ЧЕКПОИНТ D), integration-тест 7.8 зелёный
- [ ] Backpressure watermarks выставлены; orchestrate не паузится
- [ ] R2 lifecycle применён (ingest 2d / intermediate 3d / clips IA 90d)
- [ ] bull-board за auth; pino-логи; алерты на webhook
- [ ] Rate-limit live на публичных эндпоинтах
- [ ] CSP/HSTS/headers live; SW+push+SSE не сломаны (ЧЕКПОИНТ E)

**Релиз-гейт**
- [ ] Полный тест-сьют зелёный (TS + Python)
- [ ] Coverage ≥ порога (TS 85% / billing 95% / py-metering 90%)
- [ ] e2e smoke на staging зелёный (7.13)
- [ ] Load-test thresholds пройдены, `gpu_inflight_max ≤ 2` (7.14)
- [ ] `pnpm audit` / `pip-audit` без HIGH/CRITICAL
- [ ] Release-gate физически блокирует красный билд (ЧЕКПОИНТ F)

**Публикация / anti-block (docs/04)**
- [ ] YouTube **API compliance audit** пройден (иначе видео молча private)
- [ ] YouTube OAuth consent screen → **In production** (refresh не мрут за 7д)
- [ ] **TikTok audit** пройден (иначе 5 юзеров/24ч, SELF_ONLY)
- [ ] **Meta App Review** на `instagram_business_content_publish`
- [ ] Срез чужих watermark; FlipHouse-брендинг НЕ вжигается
- [ ] `containsSyntheticMedia=true` (YT) / `is_aigc=true` (TikTok) / AI-label (IG)
- [ ] FTC/ASA `requiredDisclosure` несъёмен в публикации

**Секреты / инфра**
- [ ] VAPID (public на build-time), OPENROUTER, R2-креды, KMS, Stripe Connect — present
- [ ] `/api/health` 200 на prod; миграции применены; 2 реплики `web`
- [ ] Все сервисы на `0.0.0.0`/`::`; приватные `_PRIVATE_`-URL

---

## Выход фазы (Phase exit criteria)

- [ ] **Trust-слой работает end-to-end:** OAuth-коннект → метеринг-снапшоты → `Δviews × visibility → charge` → settlement, с anomaly+audit holds. (7.1–7.7)
- [ ] **GPU-квота доказана под нагрузкой:** integration-тест (7.8) + load-test (7.14) показывают `inflight ≤ global cap` при N репликах/50 VU. (ЧЕКПОИНТ D)
- [ ] **Backpressure + scale-to-zero** держат burst без переполнения и без deadlock orchestrate. (7.9)
- [ ] **R2 lifecycle** применён по всем трём prefix; orphan-reaper работает. (7.11)
- [ ] **Наблюдаемость live:** bull-board за auth, структурные логи, рабочие алерты. (7.10)
- [ ] **Security surface закрыт:** rate-limit + nonce-CSP + полный набор заголовков, SW/push/SSE не сломаны. (7.12, ЧЕКПОИНТ E)
- [ ] **Smoke-e2e зелёный** на весь путь upload→clip→banner→publish→attribution с ассертами на выход (размеры/длительность/баннер/visibility). (7.13)
- [ ] **Релиз-гейт — CI-блокер:** красный билд физически не доходит до прода; coverage-пороги enforced. (7.15, ЧЕКПОИНТ F)
- [ ] **Go-live чеклист пройден** и подписан founder'ом; OAuth-аудиты (YT/TikTok/Meta) реально approved. (7.16, ЧЕКПОИНТ G)
- [ ] **Founder-rule «ZERO bugs»:** каждый шаг закрыт TDD-циклом (RED→GREEN→refactor→commit), coverage-гейт держится на каждом коммите.

---

*Конец P7. После прохождения ЧЕКПОИНТА G и зелёного релиз-гейта — первый продакшн-деплой FlipHouse.*
