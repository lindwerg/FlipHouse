# P5 — Маркетплейс креатор↔реклама + учёт показов/выплаты

> Фаза 5 — это **двусторонний рынок**. Мы превращаем каталог офферов (из контракта doc 03) в живой маркетплейс: рекламодатель публикует оффер → клиппер находит, аппрувится, матчится → оффер принимается → клип рендерится с **этим** баннером → факт показа/конверсии регистрируется → начисляется выплата.
>
> Учётный движок (Link → Conversion → Commission, Function/Condition/Effect) **реимплементируется clean-room по блюпринту `org-quicko/cliq`** (репозиторий без лицензии — копировать код НЕЛЬЗЯ, см. doc 01 §1 «Правовые красные флаги»). Поверх крипто-биллинга из Phase 1 (через `PaymentProvider`, USDT-баланс) добавляем **metered-биллинг как наш собственный `usage_events`-ledger** (per-clip / per-render / CPM) → списание с USDT-баланса через `PaymentProvider.debit`. У крипты нет Stripe-style Billing Meters / автосписания, поэтому идемпотентность и учёт держим **на нашей стороне** (unique-ключ + off-chain ledger). Атрибуция показов/CPM — **v1 по doc 03 §5**: трекинг-ссылки + платформенная аналитика через creator-OAuth, с честными ограничениями (view-attribution, не viewability).
>
> Главное правило основателя — **ZERO BUGS**. Каждый шаг — TDD: красный тест → минимальная реализация → зелёный → рефактор → один коммит. Шаг не «готов», пока тесты не зелёные И покрытие не держит гейт.

---

## Цель фазы (Phase goal)

Поднять полный самообслуживаемый цикл маркетплейса, замыкающий A+B+C из мастер-дока в один поток:

1. **Каталог офферов** — рекламодатель публикует оффер по JSON-схеме doc 03 §1, оффер проходит lifecycle `draft → in_review → active → paused → exhausted → archived`.
2. **Browse / apply / match** — клиппер видит `active`-офферы (отфильтрованные по `targeting` + `creatorTier`), подаёт заявку на свой клип, матчинг-движок считает eligibility и score.
3. **Acceptance flow** — рекламодатель (или auto-accept по порогу) принимает заявку; принятие генерирует `impression_unit_id` и **жёстко привязывает оффер к рендеру клипа** (детерминированный `input_hash` из doc 03 §3.6).
4. **Payouts/attribution на cliq-субстрате** — Link → Conversion → Commission: трекинг-ссылка на оффер, конверсия (просмотр/показ/клик), детерминированный расчёт комиссии (Function/Condition/Effect), начисление в ledger, выплата креатору в USDT через `PaymentProvider.createPayout` (крипто-PSP — аналог Stripe Connect).
5. **Metered-биллинг (наш ledger)** — события usage (per-clip / per-render / CPM) → таблица `usage_events` (источник истины), идемпотентно (no double-charge на ретрае); списание через `PaymentProvider.chargeRecurring`.
6. **Impression/CPM attribution v1** — creator-OAuth метеринг (TikTok/YouTube/IG) + трекинг-ссылки, биллинг по дельтам просмотров × `banner_visibility_factor`, freeze на дне 90, аудит-кросс-чек. Честные ограничения зафиксированы в коде и тестах.

**Definition of Done фазы:** проходит сквозной e2e «advertiser posts offer → creator applies → accepted → clip rendered with that offer's banner → conversion recorded → payout accrued → metered (usage_events)», метеринг идемпотентен (нет двойного списания на ретрае), расчёт выплат покрыт unit-тестами на каждую payout-модель (`cpm` / `per_1k_views` / `flat` / `hybrid`), глобальное покрытие ≥ 80%.

---

## Зависимости (какие фазы должны быть готовы)

| Фаза | Что должна была дать | Почему нужна здесь |
|---|---|---|
| **Phase 0** (каркас/инфра) | Railway-проект, `web` (SaaS-Boilerplate + Drizzle + `PaymentProvider` + auth/RBAC), `Postgres`, `Redis`, `bullmq-worker` | На этом стоит вся БД маркетплейса, очередь начислений, клиент `PaymentProvider` |
| **Phase 1** (клиппинг-движок MVP) | `POST /clips` → `GET /clips/{job_id}`, рендер 9:16, `bullmq-worker`, **подписки** (`PaymentProvider`) | Метеринг (usage) надстраивается над подписками; рендер-джоба расширяется оффер-баннером |
| **Phase 2** (ad-insertion баннер) | `ad_banner.py` (ffmpeg `overlay`), offer-rules engine `plan(offer, clip_meta)`, FTC-дисклеймер | Acceptance flow дёргает именно этот рендер с принятым оффером |
| **Phase 4** (self-serve матчинг)* | matching-движок transcript-эмбеддинги ↔ offer-векторы, консоль рекламодателя (черновик) | P5 переводит matching из «auto-insert» в **explicit apply/accept** маркетплейс. Если P4 ещё не закрыт — берём упрощённый matcher как заглушку за интерфейсом и достраиваем |

> *Примечание: мастер-док (00 §5) ставит маркетплейс в Phase 4, а trust-слой (verified-views) в Phase 5. Этот файл — расширенная P5 «маркетплейс + атрибуция/выплаты», вбирающая explicit apply/accept-цикл и trust-метеринг. Где P4 уже дал matcher — переиспользуем; где нет — строим за интерфейсом `OfferMatcher`, чтобы P4-движок воткнулся без переписывания.

---

## Репозитории, клонируемые/используемые в этой фазе

Все clean-room-источники вендорим в `/vendor` **только как референс дизайна** (код не копируем), permissive-источники переиспользуем напрямую.

```bash
# 1. cliq — БЛЮПРИНТ учётного движка (Link→Conversion→Commission, Function/Condition/Effect).
#    НЕТ ЛИЦЕНЗИИ → all-rights-reserved → НЕ КОПИРОВАТЬ КОД. Только модель данных и поток событий.
git clone https://github.com/org-quicko/cliq vendor/cliq

# 2. medusajs/medusa — adopt-pattern для PromotionRule(attribute,operator,values) + CampaignBudget(limit,used).
#    MIT. Берём ПАТТЕРН форм правил/бюджетов, не весь монолит.
git clone --depth 1 https://github.com/medusajs/medusa vendor/medusa

# 3. nextjs/saas-starter — уже завендорен в Phase 0/1 как основа web. Здесь только сверяемся с webhook/Drizzle-слоем (PaymentProvider).
#    (если ещё нет в репо:)
git clone --depth 1 https://github.com/nextjs/saas-starter vendor/saas-starter
```

```bash
# Рантайм-зависимости фазы (в web / bullmq-worker, pnpm):
# SDK крипто-PSP (конкрет-реализация PaymentProvider, USDT) — для debit с баланса + выплаты createPayout.
# Пакет добавляется к коду блоков F/H. Metered-биллинг — наш usage_events-ledger, не Stripe Meters.
pnpm add ajv@latest ajv-formats@latest      # валидация оффера по JSON-Schema Draft 2020-12 (doc 03 §1)
pnpm add drizzle-orm@latest                 # ORM (уже из P0) — здесь новые таблицы маркетплейса
pnpm add nanoid@latest                      # генерация трекинг-кодов ссылок (cliq-style short code)
pnpm add decimal.js@latest                  # денежная арифметика без float-дрейфа в payout-расчёте

# Dev / тесты:
pnpm add -D vitest@latest @vitest/coverage-v8@latest   # unit/integration
pnpm add -D @playwright/test@latest                    # e2e сквозной маркетплейс-флоу
pnpm add -D drizzle-kit@latest                         # миграции
# фикстуры вебхуков крипто-PSP — нормализованные уведомления в fixtures/payments/*.json.
# Локальный webhook-forward — средствами PSP (личный кабинет / IPN), доставка в e2e на ЧЕКПОИНТЕ.
```

```bash
# Python render-воркер (ai-render-worker) — оффер-баннер уже из Phase 2; здесь только golden-fixture тесты:
pip install pytest pytest-cov
#  ffprobe/ffmpeg уже в LGPL-образе из doc 01 §6
```

---

## Чекпоинты фазы (что ревьюит основатель)

| # | После шага | 🛑 ЧЕКПОИНТ |
|---|---|---|
| ЧП-1 | 5.3 | Схема БД маркетплейса + валидатор оффера: модель данных Offer/Application/Match/ImpressionUnit/Conversion/Commission/Ledger корректна и расширяема |
| ЧП-2 | 5.6 | Каталог + публикация оффера (advertiser): lifecycle и brand-safety-гейт оффера работают, форма сериализуется в схему |
| ЧП-3 | 5.9 | Browse/apply/match (creator): eligibility-фильтрация по targeting + matching-score, заявки создаются |
| ЧП-4 | 5.11 | Acceptance flow: принятие заявки генерит impression_unit + детерминированно привязывает оффер к рендеру |
| ЧП-5 | 5.13 | Рендер клипа с принятым оффером: баннер реально в кадре (golden-fixture), привязка к impression_unit |
| ЧП-6 | 5.16 | cliq-субстрат: Link→Conversion→Commission движок (Function/Condition/Effect) детерминированно считает начисления |
| ЧП-7 | 5.19 | Metered-биллинг (наш usage_events-ledger): события usage идемпотентны, нет двойного списания на ретрае |
| ЧП-8 | 5.22 | Attribution v1: creator-OAuth метеринг по дельтам + аудит, честные ограничения зафиксированы |
| ЧП-9 | 5.24 | Payout/settlement: расчёт всех payout-моделей + выплата креатору в USDT через `PaymentProvider.createPayout` (крипто-PSP), monthly settle |
| ЧП-10 | 5.26 | Сквозной e2e зелёный, покрытие ≥80%, фаза готова к деплою на staging |

---

## Конвенции тестирования (общие для всей фазы)

- **TS unit/integration** → Vitest. Файлы рядом с кодом: `*.test.ts`. Integration с БД — против реального Postgres в `staging`-ветке схемы (Testcontainers-free: отдельная test-БД `fliphouse_test`, миграции применяются в `beforeAll`, транзакция-rollback на каждый тест).
- **TS e2e** → Playwright (`e2e/*.spec.ts`), детерминированные ожидания (`expect.poll` / `waitForResponse`), без `waitForTimeout`.
- **Python render** → pytest + golden-fixture: на выход FFmpeg ассертим `ffprobe` (duration ±0.1с, dimensions 1080×1920), **frame-hash** в окне показа баннера (баннер реально в пикселях), отсутствие баннера вне окна. Не «ffmpeg отработал».
- **Крипто-PSP** → mock через интерфейс `PaymentProvider` (подменённая реализация) + нормализованные фикстуры уведомлений (записаны в `fixtures/payments/*.json`). Идемпотентность проверяется повторной доставкой одного и того же `eventId`.
- **Деньги** → только `decimal.js`, никаких float. Тест на каждую payout-модель сверяет до копейки.
- **Coverage gate:** `vitest --coverage`, порог в `vitest.config.ts` — `lines/functions/branches/statements ≥ 80`. Шаг не мёржится при падении гейта.

---

# Шаги

## Блок A — Модель данных и валидатор (ЧП-1)

### Шаг 5.1 — Вендоринг cliq/medusa как референс + ADR clean-room
- **Цель / DoD:** в `/vendor` лежат `cliq` и `medusa`; написан `docs/adr/P5-001-cliq-cleanroom.md`, фиксирующий: какие сущности cliq реимплементируем (Link, Conversion, Commission, Function, Condition, Effect), что код НЕ копируется, маппинг cliq→FlipHouse. Никакого продового кода — только вендор + ADR.
- **Репозитории/команды:**
  ```bash
  git clone https://github.com/org-quicko/cliq vendor/cliq
  git clone --depth 1 https://github.com/medusajs/medusa vendor/medusa
  echo "vendor/" >> .gitignore   # вендор не коммитим в наш дерево, только ADR ссылается
  ```
- **Тесты СНАЧАЛА:** тестов кода нет (ADR-шаг). Вместо теста — **doc-gate**: `scripts/check-adr.test.ts` (Vitest) с тестом `test('ADR P5-001 существует и перечисляет все 6 cliq-примитивов')` — читает `docs/adr/P5-001-cliq-cleanroom.md`, ассертит наличие подстрок `Link`, `Conversion`, `Commission`, `Function`, `Condition`, `Effect` и слова `clean-room`.
- **Реализация:** клонировать вендор; написать ADR с таблицей маппинга cliq-сущность → наша таблица → отличия (главное: «cliq останавливается на accrual, не двигает деньги — мы добавляем payout через `PaymentProvider.createPayout`»).
- **✅ Готово когда:** `check-adr.test.ts` зелёный; `vendor/` в `.gitignore`; ADR ревьюабелен.
- **Commit:** `docs: ADR P5-001 clean-room cliq accrual model + vendor refs`

### Шаг 5.2 — JSON-Schema оффера + Ajv-валидатор
- **Цель / DoD:** схема оффера из doc 03 §1.1 лежит как файл; чистая функция `validateOffer(input): Result<Offer, ValidationError[]>` валидирует против неё (Draft 2020-12, `additionalProperties:false`, conditional `allOf` для `payout`/`timing`).
- **Репозитории/команды:** `pnpm add ajv ajv-formats` (уже выше).
- **Тесты СНАЧАЛА** (`src/marketplace/offer/offerSchema.test.ts`, Vitest):
  - `test('валидный пример из doc 03 §1.2 проходит валидацию')` — грузит `fixtures/offer/nitrogg.json` (тот самый NitroGG-пример), ассертит `result.ok === true`.
  - `test('отклоняет неизвестный schemaVersion major')` — `schemaVersion:"2.0.0"` → `ok===false`, ошибка по `schemaVersion`.
  - `test('требует rate при model=cpm')` — payout без `rate` → ошибка пути `/payout`.
  - `test('требует flatAmount при model=flat')`.
  - `test('требует intervalSec при frequency=interval')` — ошибка пути `/timing`.
  - `test('отклоняет additionalProperties в brand')` — лишнее поле → fail.
  - `test('primaryColor должен матчить ^oklch\\(')`.
  - `test('banner с type=animated требует durationMs')` — `$defs.bannerAsset` `allOf`.
- **Реализация:** `src/marketplace/offer/offer.schema.json` (копия из doc 03 §1.1 дословно), `src/marketplace/offer/offerSchema.ts` (компиляция Ajv с `ajv-formats`, экспорт `validateOffer`), `fixtures/offer/nitrogg.json` (пример из §1.2).
- **✅ Готово когда:** все 8 тестов зелёные; coverage модуля 100%; ручной прогон `validateOffer` на 3 кривых офферах даёт читаемые пути ошибок.
- **Commit:** `feat: offer JSON-Schema + Ajv validator (doc 03 §1)`

### Шаг 5.3 — Drizzle-схема маркетплейса 🛑 ЧЕКПОИНТ
- **Цель / DoD:** Drizzle-таблицы и миграция для всего маркетплейса. Таблицы: `offers`, `offer_assets`, `applications`, `matches`, `impression_units`, `tracking_links`, `conversions`, `commissions`, `ledger_entries`, `payouts`, `usage_events`. FK/индексы/enum'ы выровнены под последующие шаги.
- **Репозитории/команды:** `pnpm add drizzle-orm`, `pnpm add -D drizzle-kit`. Сверка с биллинг/Drizzle-слоем `vendor/saas-starter` (Stripe-код там не используем — биллинг за `PaymentProvider`).
- **Тесты СНАЧАЛА** (`src/db/schema/marketplace.test.ts`, integration против `fliphouse_test`):
  - `test('миграция применяется и создаёт 11 таблиц маркетплейса')` — после `migrate()` `information_schema` содержит все 11.
  - `test('offer.status enum покрывает весь lifecycle')` — вставка каждого из `draft/in_review/active/paused/exhausted/archived`, недопустимое значение → ошибка.
  - `test('impression_units уникален по (campaign_id, placement_id, clip_id)')` — дубль → unique violation (зеркало doc 03 §5.2 шаг 2).
  - `test('ledger_entries имеет numeric(18,4) для amount, не float')` — проверка типа колонки.
  - `test('usage_events уникален по payment_idempotency_key')` — основа no-double-charge.
  - `test('FK application.offer_id → offers.id с ON DELETE RESTRICT')`.
- **Реализация:** `src/db/schema/marketplace.ts` (все таблицы; деньги — `numeric(18,4)`; статусы — pgEnum; `tracking_links.code` unique; `usage_events.paymentIdempotencyKey` unique). `drizzle-kit generate` → `drizzle/00XX_p5_marketplace.sql`. Скрипт миграции test-БД в `vitest.setup.ts`.
- **✅ Готово когда:** все 6 тестов зелёные; миграция применяется и откатывается чисто; ER-диаграмма в ADR обновлена.
- **🛑 ЧЕКПОИНТ ЧП-1:** основатель ревьюит модель данных Offer/Application/Match/ImpressionUnit/Conversion/Commission/Ledger — расширяема ли она под verified-views, hybrid-payouts, мульти-коннект. Может поменять имена/типы/индексы до того, как на схему ляжет код.
- **Commit:** `feat: marketplace Drizzle schema + migration (offers→payouts)`

---

## Блок B — Каталог и публикация оффера (advertiser) (ЧП-2)

### Шаг 5.4 — Offer repository (CRUD + lifecycle переходы)
- **Цель / DoD:** `OfferRepository` (паттерн репозитория из common/patterns): `create/findById/findActive/update/transition`. Переходы статуса — чистая `canTransition(from,to)` валидирующая допустимые рёбра lifecycle; `exhausted` авто-проставляется при достижении `totalBudget` (проверяется отдельно).
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/marketplace/offer/offerRepository.test.ts`, integration):
  - `test('create присваивает offerId (uuid) и status=draft')`.
  - `test('transition draft→in_review→active разрешён')`.
  - `test('transition active→draft запрещён (бросает InvalidTransition)')`.
  - `test('findActive возвращает только status=active')` — вставляем по одному каждого статуса, ждём один.
  - `test('update не даёт менять серверные поля offerId/createdAt')` — попытка → игнор/ошибка.
- **Реализация:** `src/marketplace/offer/offerRepository.ts`, `src/marketplace/offer/lifecycle.ts` (граф переходов как const-таблица рёбер, чистая `canTransition`).
- **✅ Готово когда:** 5 тестов зелёные; lifecycle-граф покрыт на 100% (все рёбра + все запрещённые).
- **Commit:** `feat: offer repository + lifecycle transition guard`

### Шаг 5.5 — API публикации оффера (`POST /api/offers`, `PATCH /api/offers/:id`)
- **Цель / DoD:** API-роуты Next.js: создание оффера (валидация через `validateOffer`, `status=draft`, серверные поля проставляет сервер), submit (`PATCH` → `status=in_review`), список своих офферов рекламодателя. RBAC: только `accountType=advertiser`.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/app/api/offers/offers.route.test.ts`, integration):
  - `test('POST /api/offers с валидным телом создаёт draft и возвращает offerId')` → 201.
  - `test('POST /api/offers с невалидным payout → 422 со списком путей ошибок')`.
  - `test('POST игнорирует клиентский offerId/createdAt/platformFeePct')` — сервер перезаписывает.
  - `test('PATCH submit переводит draft→in_review')`.
  - `test('creator (не advertiser) получает 403 на POST /api/offers')`.
  - `test('advertiser видит только свои офферы в GET /api/offers')`.
- **Реализация:** `src/app/api/offers/route.ts` (POST/GET), `src/app/api/offers/[id]/route.ts` (PATCH), общий envelope ответа (common/patterns: `{success,data,error}`). Серверная подстановка `platformFeePct` из конфига.
- **✅ Готово когда:** 6 тестов зелёные; покрытие роутов ≥80%.
- **Commit:** `feat: advertiser offer publish API (POST/PATCH/GET /api/offers)`

### Шаг 5.6 — Brand-safety-гейт ОФФЕРА (in_review→active) 🛑 ЧЕКПОИНТ
- **Цель / DoD:** при submit оффер ставится `in_review`; гейт оффера (модерация: запрещённые ассеты, валидность лого https, sane payout-cap, наличие хотя бы одного 9:16/1:1 баннера) переводит в `active` или оставляет `in_review` с причиной. Это гейт **оффера**, не клипа (клиповый brand-safety — Phase 2/doc 03 §4).
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/marketplace/offer/offerReview.test.ts`):
  - `test('оффер с 9:16 баннером и https-лого проходит → active')`.
  - `test('оффер без вертикального баннера остаётся in_review с reason=no_vertical_banner')`.
  - `test('оффер с http (не https) лого → reject reason=insecure_asset')`.
  - `test('rate ниже 0 или totalBudget=0 при cpm → reject reason=invalid_economics')`.
  - `test('approveOffer идемпотентен (повторный вызов на active = no-op)')`.
- **Реализация:** `src/marketplace/offer/offerReview.ts` (чистая `reviewOffer(offer): ReviewDecision`), хук в submit-флоу, который дёргает review и применяет transition.
- **✅ Готово когда:** 5 тестов зелёные.
- **🛑 ЧЕКПОИНТ ЧП-2:** основатель ревьюит публикацию оффера end-to-end (форма → схема → review → active в каталоге). Может изменить правила гейта, набор reason-кодов, политику auto-approve vs manual.
- **Commit:** `feat: offer brand-safety review gate (in_review→active)`

---

## Блок C — Browse / apply / match (creator) (ЧП-3)

### Шаг 5.7 — Eligibility-фильтр (targeting → eligible offers для клипа)
- **Цель / DoD:** чистая функция `filterEligible(offers, clipMeta): Offer[]` — применяет `targeting` оффера (contentNiches/excludedNiches/platforms/geo/languages/min-maxClipDuration/creatorTier) к метаданным клипа. Детерминированно, без I/O.
- **Репозитории/команды:** adopt-pattern `vendor/medusa` PromotionRule(attribute,operator,values).
- **Тесты СНАЧАЛА** (`src/marketplace/match/eligibility.test.ts`):
  - `test('оффер с contentNiches=[gaming] матчит клип niche=gaming')`.
  - `test('оффер с excludedNiches=[finance] отсекает клип niche=finance')`.
  - `test('клип короче minClipDurationSec не eligible')`.
  - `test('creatorTier=[verified,top] отсекает клиппера tier=new')`.
  - `test('geo=[RU] отсекает клиппера geo=US, пустой geo = без ограничения')`.
  - `test('фильтр детерминированен: один вход → один и тот же отсортированный выход')`.
- **Реализация:** `src/marketplace/match/eligibility.ts` (правила как `Rule[]` в форме medusa `{attribute,operator,values}`, движок применяет AND по всем правилам).
- **✅ Готово когда:** 6 тестов зелёные; покрытие 100% (это часть «детерминированного ядра»).
- **Commit:** `feat: targeting eligibility filter (medusa rule pattern)`

### Шаг 5.8 — OfferMatcher (score eligibility + ранжирование) за интерфейсом
- **Цель / DoD:** интерфейс `OfferMatcher.score(offer, clipMeta): MatchScore` + дефолтная реализация `HeuristicMatcher` (взвешенная сумма: niche-overlap, duration-fit, tier-fit). Интерфейс готов принять P4 embedding-matcher без изменения вызывающего кода.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/marketplace/match/matcher.test.ts`):
  - `test('точное совпадение ниши даёт score выше частичного')`.
  - `test('score в диапазоне [0,1]')`.
  - `test('HeuristicMatcher детерминирован')`.
  - `test('matcher за интерфейсом: подмена на StubEmbeddingMatcher не ломает вызывающий код')` — DI-проверка.
- **Реализация:** `src/marketplace/match/matcher.ts` (интерфейс + HeuristicMatcher), `matcher.di.ts` (фабрика, env-флаг `MATCHER=heuristic|embedding`).
- **✅ Готово когда:** 4 теста зелёные.
- **Commit:** `feat: OfferMatcher interface + heuristic scorer`

### Шаг 5.9 — Apply API + browse (creator) 🛑 ЧЕКПОИНТ
- **Цель / DoD:** `GET /api/marketplace/offers?clipId=` (eligible+scored список для клипа клиппера), `POST /api/applications` (клиппер подаёт заявку оффер↔клип; создаёт `applications` row `status=pending` + `matches` row со score). Идемпотентность: повторная заявка тем же (offer,clip) — no-op/409.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/app/api/applications/applications.route.test.ts`, integration):
  - `test('GET browse возвращает только eligible offers, отсортированные по score desc')`.
  - `test('POST /api/applications создаёт application=pending + match со score')`.
  - `test('повторная заявка (offer,clip) → 409 conflict, дубля нет')`.
  - `test('заявка на не-active оффер → 422')`.
  - `test('заявка на не-eligible клип → 422 reason=not_eligible')`.
  - `test('advertiser не может подать заявку (403)')`.
- **Реализация:** `src/app/api/marketplace/offers/route.ts` (browse), `src/app/api/applications/route.ts` (apply), `ApplicationRepository`.
- **✅ Готово когда:** 6 тестов зелёные.
- **🛑 ЧЕКПОИНТ ЧП-3:** основатель ревьюит creator-флоу: видит ли клиппер релевантные офферы, как ранжируются, корректна ли заявка. Может поменять веса matcher, политику дублей, поля browse-карточки.
- **Commit:** `feat: creator browse + apply API (eligibility+score+dedup)`

---

## Блок D — Acceptance + рендер с оффером (ЧП-4, ЧП-5)

### Шаг 5.10 — Accept/reject API + генерация impression_unit
- **Цель / DoD:** `POST /api/applications/:id/accept` (рекламодатель или auto-accept): переводит `application.status pending→accepted`, **генерирует `impression_unit_id` (campaign × placement × clip)**, создаёт `impression_units` row с CPM-ставкой, % экранного времени баннера (из PlacementPlan), in/out timestamps — зеркало doc 03 §5.2 шаг 2. Reject → `status=rejected` с reason.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/marketplace/accept/acceptance.test.ts`, integration):
  - `test('accept переводит pending→accepted и создаёт impression_unit')`.
  - `test('impression_unit несёт cpm_rate, banner_visibility_factor, t_in/t_out')`.
  - `test('accept уже принятой заявки идемпотентен (тот же impression_unit_id)')` — критично против двойной генерации.
  - `test('reject переводит pending→rejected с reason')`.
  - `test('accept не-pending заявки → 409')`.
  - `test('auto-accept срабатывает когда matchScore ≥ порога оффера')`.
- **Реализация:** `src/marketplace/accept/acceptance.ts` (`acceptApplication` — транзакция: transition + insert impression_unit с дедупом по `(campaign,placement,clip)` unique), `src/app/api/applications/[id]/accept/route.ts`.
- **✅ Готово когда:** 6 тестов зелёные; идемпотентность accept доказана (повторный accept не плодит impression_units).
- **Commit:** `feat: acceptance flow + impression_unit generation (doc 03 §5.2)`

### Шаг 5.11 — Привязка оффера к рендер-джобе (детерминированный input_hash) 🛑 ЧЕКПОИНТ
- **Цель / DoD:** принятие enqueue'ит/обновляет рендер-джобу клипа с **этим** оффером. Вычисляется `input_hash = sha256(offer, clip_meta, engine_version)` (doc 03 §3.6) — ключ кеша рендера и связующее звено impression_unit ↔ render. BullMQ jobId детерминирован от input_hash (идемпотентность по doc 01 §5).
- **Репозитории/команды:** BullMQ (из P0/P1).
- **Тесты СНАЧАЛА** (`src/marketplace/accept/renderBinding.test.ts`):
  - `test('input_hash детерминирован для одинаковых (offer,clip,engine_version)')`.
  - `test('изменение rate в оффере меняет input_hash')` — хеш покрывает оффер целиком.
  - `test('accept ставит render-job с jobId=render:{input_hash} и offerId в payload')`.
  - `test('повторный accept того же → тот же jobId → BullMQ дедуп (no-op)')`.
  - `test('impression_unit.render_input_hash == job input_hash')` — связь сохранена.
- **Реализация:** `src/marketplace/accept/renderBinding.ts` (canonical-JSON сериализация offer+clipMeta → sha256, enqueue в `cpu`/`orchestrate` очередь с offer в data), обновление `impression_units.render_input_hash`.
- **✅ Готово когда:** 5 тестов зелёные; идемпотентность энкью доказана.
- **🛑 ЧЕКПОИНТ ЧП-4:** основатель ревьюит acceptance: генерируется ли impression_unit, детерминированно ли оффер привязывается к рендеру, не плодятся ли дубли на ретрае. Может изменить состав input_hash, политику auto-accept-порога.
- **Commit:** `feat: bind accepted offer to render job via deterministic input_hash`

### Шаг 5.12 — Render-воркер: рендер с принятым оффер-баннером (offer-rules → ffmpeg)
- **Цель / DoD:** `ai-render-worker` принимает job с offer payload, гоняет offer-rules engine `plan(offer, clip_meta)` (Phase 2) → PlacementPlan → ffmpeg overlay-граф (doc 03 §3.7), выдаёт `out.mp4`. Записывает render hash в `impression_units`. FTC-дисклеймер (`cta.requiredDisclosure`) — несъёмный.
- **Репозитории/команды:** ffmpeg LGPL-образ (doc 01 §6), offer-rules engine (Phase 2).
- **Тесты СНАЧАЛА** (`workers/render/test_offer_render.py`, pytest + golden-fixture):
  - `test_render_produces_1080x1920` — `ffprobe` на выходе: width=1080, height=1920.
  - `test_render_duration_matches_clip` — duration ±0.1с от исходного клипа.
  - `test_banner_present_in_window` — извлекаем кадр в `t_in+0.5с`, frame-hash зоны баннера ≠ хешу того же региона на исходнике (баннер реально в пикселях).
  - `test_banner_absent_outside_window` — кадр до `appearAtSec`: регион баннера == исходник (вне окна чисто).
  - `test_disclosure_overlay_present` — дисклеймер-страйп присутствует (frame-hash/OCR-проба на наличие `requiredDisclosure`-зоны).
  - `test_render_deterministic` — два прогона одного (offer,clip) → идентичный sha256 выходного файла.
- **Реализация:** `workers/render/offer_render.py` (вызов plan→filtergraph→`-filter_complex_script`→ffmpeg), запись render hash. Golden-фикстуры: `workers/render/fixtures/clip_sample_15s.mp4` + `nitrogg.json`.
- **✅ Готово когда:** 6 pytest зелёные; golden-кадры сверены; детерминизм доказан.
- **Commit:** `feat: render worker composites accepted offer banner (golden-tested)`

### Шаг 5.13 — Регистрация рендера + статус impression_unit 🛑 ЧЕКПОИНТ
- **Цель / DoD:** по завершении рендера webhook/воркер обновляет `impression_units.status=rendered`, `render_url` (R2), `render_hash`; публикует клип в R2 `clips/`. Привязка impression_unit ↔ итоговый клип замкнута.
- **Репозитории/команды:** R2 (doc 01 §4), webhook-receiver (P1).
- **Тесты СНАЧАЛА** (`src/marketplace/render/renderComplete.test.ts`, integration):
  - `test('render-complete обновляет impression_unit на rendered + render_url')`.
  - `test('идемпотентность: повторная доставка render-complete не дублирует')` — дедуп по render_hash.
  - `test('render-complete на неизвестный input_hash → 404, не падает')`.
  - `test('connects impression_unit → clip_id → application → offer (полная цепочка JOIN)')`.
- **Реализация:** `src/marketplace/render/renderComplete.ts` + хук в webhook-receiver.
- **✅ Готово когда:** 4 теста зелёные.
- **🛑 ЧЕКПОИНТ ЧП-5:** основатель проверяет реальный клип с вкомпонованным NitroGG-баннером (golden-fixture + ручной просмотр). Подтверждает: баннер в кадре, дисклеймер на месте, impression_unit связан с клипом. Может зарубить визуал/позицию баннера.
- **Commit:** `feat: register render completion → impression_unit rendered`

---

## Блок E — cliq-субстрат: Link → Conversion → Commission (ЧП-6)

### Шаг 5.14 — Tracking links (Link-сущность cliq, clean-room)
- **Цель / DoD:** генерация трекинг-ссылки на принятый оффер↔клип (короткий код nanoid), редирект-эндпоинт `GET /t/:code` → 302 на `cta.destinationUrl` с UTM, регистрирует **click**-конверсию-кандидата. Это «другой продукт» из doc 03 §5.1 (click-атрибуция) — отдельный от view-метеринга канал.
- **Репозитории/команды:** `pnpm add nanoid`. Референс модели — `vendor/cliq` Link.
- **Тесты СНАЧАЛА** (`src/marketplace/tracking/link.test.ts`, integration):
  - `test('createTrackingLink генерит уникальный код, привязанный к impression_unit')`.
  - `test('GET /t/:code редиректит 302 на destinationUrl с UTM-параметрами')`.
  - `test('GET /t/:code пишет click-событие (ip-hash, ts, referer)')`.
  - `test('неизвестный код → 404')`.
  - `test('код урл-безопасен и не коллизирует (10k генераций без дублей)')`.
- **Реализация:** `src/marketplace/tracking/link.ts` (`createTrackingLink`, `resolveLink`), `src/app/t/[code]/route.ts` (302 + click insert в `conversions` как `kind=click pending`).
- **✅ Готово когда:** 5 тестов зелёные.
- **Commit:** `feat: tracking links (cliq Link, click attribution channel)`

### Шаг 5.15 — Conversion-движок (Function/Condition/Effect, clean-room cliq)
- **Цель / DoD:** реимплементация cliq Function/Condition/Effect как **чистого детерминированного движка**: `Condition(attribute, operator, value)` оценивается над событием конверсии, `Function` группирует условия, `Effect` описывает что начисляется. `evaluate(conversion, rules): Effect[]` — без I/O, без часов, без RNG.
- **Репозитории/команды:** `vendor/cliq` (только дизайн!), `vendor/medusa` (форма правил).
- **Тесты СНАЧАЛА** (`src/marketplace/commission/engine.test.ts`):
  - `test('Condition view_count ≥ minViewsToQualify проходит при достижении порога')`.
  - `test('Function требует ВСЕ Condition (AND) для срабатывания Effect')`.
  - `test('Effect commission рассчитывается детерминированно для одинакового входа')`.
  - `test('конверсия ниже minViewsToQualify не порождает Effect (анти-фрод порог)')`.
  - `test('движок чист: нет обращений к Date.now / random / сети')` — статанализ/инъекция фейкового clock, ассерт неиспользования.
  - `test('неизвестный operator → ошибка валидации, не молчаливый пропуск')`.
- **Реализация:** `src/marketplace/commission/engine.ts` (типы Condition/Function/Effect, `evaluate`), `operators.ts` (whitelist операторов: `gte/lte/eq/in/contains`).
- **✅ Готово когда:** 6 тестов зелёные; покрытие 100% (детерминированное ядро).
- **Commit:** `feat: clean-room conversion engine (Function/Condition/Effect)`

### Шаг 5.16 — Commission calculator (все payout-модели) 🛑 ЧЕКПОИНТ
- **Цель / DoD:** `computeCommission(impressionUnit, conversion, payout): Commission` для всех 4 моделей doc 03 §1: `cpm`, `per_1k_views`, `flat`, `hybrid`. Учитывает `banner_visibility_factor`, `platformFeePct`, `minViewsToQualify`, `viewWindowDays`, `totalBudget`-cap. **Только `decimal.js`.**
- **Репозитории/команды:** `pnpm add decimal.js`.
- **Тесты СНАЧАЛА** (`src/marketplace/commission/computeCommission.test.ts`):
  - `test('cpm: 50000 показов × visibility 0.4 × rate 120/1000 = 2400, fee 20% → creator 1920')` — точная копейка.
  - `test('per_1k_views: дельта 10000 просмотров × rate 120/1000 = 1200')`.
  - `test('flat: фикс flatAmount за принятый клип, независимо от просмотров')`.
  - `test('hybrid: flatAmount база + per_1k_views переменная')`.
  - `test('просмотры < minViewsToQualify → commission = 0')`.
  - `test('расход не превышает totalBudget; превышение клампится и помечает exhausted')`.
  - `test('platformFeePct корректно вычитается, creatorShare = gross × (1 - fee)')`.
  - `test('нет float-дрейфа: 0.1+0.2 кейс через decimal.js точен')`.
- **Реализация:** `src/marketplace/commission/computeCommission.ts` (свитч по `payout.model`, всё через `Decimal`), `money.ts` (хелперы округления — banker's rounding до 4 знаков, до 2 на выплате).
- **✅ Готово когда:** 8 тестов зелёные; покрытие 100%; каждая модель сверена до копейки.
- **🛑 ЧЕКПОИНТ ЧП-6:** основатель ревьюит cliq-субстрат: корректны ли все 4 формулы выплат, как считается visibility_factor, как клампится бюджет, нет ли float-дрейфа. Может изменить округление, fee-политику, определение «показа».
- **Commit:** `feat: commission calculator for cpm/per_1k_views/flat/hybrid (decimal.js)`

### Шаг 5.17 — Ledger (двойная запись начислений + idempotency)
- **Цель / DoD:** `LedgerService.accrue(commission)` пишет двойную запись (`debit advertiser_budget` / `credit creator_payable` / `credit platform_fee`) в `ledger_entries`, идемпотентно по `(impression_unit_id, conversion_id)`. Баланс сходится (sum debit == sum credit).
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/marketplace/ledger/ledger.test.ts`, integration):
  - `test('accrue пишет сбалансированную тройку записей (debit==credit)')`.
  - `test('повторный accrue той же (impression_unit,conversion) идемпотентен')` — no double-accrual.
  - `test('creator_payable аккумулируется по нескольким конверсиям клипа')`.
  - `test('balance(advertiser) уменьшается ровно на gross commission')`.
  - `test('конкурентные accrue не задваивают (тест на гонку через unique-constraint)')`.
- **Реализация:** `src/marketplace/ledger/ledger.ts` (транзакция + unique `(impression_unit_id, conversion_id)`).
- **✅ Готово когда:** 5 тестов зелёные; инвариант баланса проверяется свойством.
- **Commit:** `feat: double-entry ledger with idempotent accrual`

---

## Блок F — Metered-биллинг (наш usage_events-ledger) (ЧП-7)

> У крипто-биллинга нет Stripe-style Billing Meters / автосписания. Поэтому metered-биллинг — это **наш** ledger
> `usage_events` (источник истины идемпотентности), из которого формируется списание с USDT-баланса
> через `PaymentProvider.debit`. Никакого делегирования дедупа PSP.

### Шаг 5.18 — usage event recorder (идемпотентный, наш ledger)
- **Цель / DoD:** `recordUsage(usageEvent)` пишет `usage_events` row с **`paymentIdempotencyKey` = детерминированный idempotency-key** (per-clip / per-render / CPM) через `INSERT ... ON CONFLICT DO NOTHING`; если конфликт → событие уже учтено → skip (no double-charge). Списание агрегата с USDT-баланса — отдельным billing-прогоном через `PaymentProvider.debit`.
- **Репозитории/команды:** — (SDK крипто-PSP подключается на billing-прогоне, не здесь; запись в ledger — чистый Drizzle).
- **Тесты СНАЧАЛА** (`src/billing/usage/recordUsage.test.ts`, integration на PGlite):
  - `test('recordUsage(per_render) пишет usage_events row с детерминированным paymentIdempotencyKey')`.
  - `test('повторный recordUsage того же события НЕ создаёт второй row')` — count == 1.
  - `test('конкурентные recordUsage (та же джоба ретраится) → один row')` — unique-constraint держит.
  - `test('billing-прогон агрегирует неоплаченные usage_events и шлёт ОДНО списание через PaymentProvider')` — мок провайдера, вызов == 1.
  - `test('три типа usage (per_clip/per_render/cpm) мапятся на правильный billing unit')`.
- **Реализация:** `src/billing/usage/recordUsage.ts` (запись в `usage_events`), `src/billing/usage/meterKeys.ts` (детерминированная генерация ключа: `${type}:${input_hash}:${unit}`), `src/billing/usage/chargeUsage.ts` (агрегация → `PaymentProvider.chargeRecurring`).
- **✅ Готово когда:** 5 тестов зелёные; идемпотентность на нашей unique-таблице доказана.
- **Commit:** `feat: idempotent metered usage_events ledger (per-clip/render/cpm)`

### Шаг 5.19 — Usage-хуки в пайплайн (render done → per_render; impression → cpm) 🛑 ЧЕКПОИНТ
- **Цель / DoD:** разместить вызовы `emitUsage` в правильных точках: рендер завершён → `per_render` + `per_clip`; биллабельный показ начислен (Блок G) → `cpm`. Все за идемпотентным emitter'ом. Ретрай джобы не задваивает usage.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/billing/usage/usageHooks.test.ts`, integration):
  - `test('render-complete эмитит per_render + per_clip ровно один раз')`.
  - `test('повторная доставка render-complete (ретрай вебхука) не задваивает usage')`.
  - `test('billable impression эмитит cpm usage с quantity = billable_impressions')`.
  - `test('падение emitUsage не откатывает рендер (usage в отдельной транзакции, ретраится воркером)')`.
- **Реализация:** хуки в `renderComplete.ts` (Блок D) и в metering-сервисе (Блок G); usage эмитится из `bullmq-worker` с собственными attempts/backoff.
- **✅ Готово когда:** 4 теста зелёные; no-double-charge на ретрае доказан end-to-end.
- **🛑 ЧЕКПОИНТ ЧП-7:** основатель ревьюит метеринг: события usage идемпотентны, нет двойного списания на ретрае вебхука/джобы, корректный маппинг типов на billing units. Может изменить, что именно метрируется и по какой цене.
- **Commit:** `feat: wire metered usage into render + impression pipeline`

---

## Блок G — Attribution v1: creator-OAuth метеринг (ЧП-8)

### Шаг 5.20 — Publish-claim: матч опубликованного клипа ↔ impression_unit
- **Цель / DoD:** по публикации (из doc 04 §5 `PublishTarget`) ловим `platformPostId`/URL, матчим к impression_unit по render_hash + watermark-токену (doc 03 §5.2 шаг 3). Авто (опрос video.list) + ручной фолбэк (креатор вставляет URL, с аудит-флагом).
- **Репозитории/команды:** OAuth-коннекты из doc 04 §5 (Phase 4/предыдущие).
- **Тесты СНАЧАЛА** (`src/attribution/publishClaim.test.ts`, integration):
  - `test('publish с render_hash матчит к impression_unit и пишет platform/postId')`.
  - `test('ручной URL-фолбэк создаёт claim с audit_flag=manual')`.
  - `test('двойной claim одного postId идемпотентен')`.
  - `test('claim без матча render_hash → held для ручного разбора, не падает')`.
- **Реализация:** `src/attribution/publishClaim.ts`, привязка к `PublishTarget`.
- **✅ Готово когда:** 4 теста зелёные.
- **Commit:** `feat: publish-claim matches published clip to impression_unit`

### Шаг 5.21 — Метеринг просмотров: затухающий polling + дельты
- **Цель / DoD:** cron-воркер опрашивает per-video просмотры по затухающему расписанию (doc 03 §5.2 шаг 4: hourly d1 → 4×/day d7 → daily d30 → weekly d90 → freeze). Хранит time-series снапшоты в `conversions` (kind=view), биллит по **дельтам** (не lifetime → нет двойного счёта на перечитанном клипе). Нормализация per-platform (TikTok view ≠ YouTube view ≠ Reels play).
- **Репозитории/команды:** TikTok Display API / YouTube Analytics / IG Graph (doc 04 §3-4), `getValidAccessToken` (doc 04 §5.4).
- **Тесты СНАЧАЛА** (`src/attribution/meter.test.ts`, integration + mocked platform APIs):
  - `test('первый снапшот пишет view_count, delta = full count')`.
  - `test('второй снапшот биллит ТОЛЬКО дельту (new - prev), не lifetime')` — против двойного счёта.
  - `test('расписание затухает: d1 hourly, d8 daily, d31 weekly, d91 freeze')`.
  - `test('после freeze (d90) новые опросы не биллятся')`.
  - `test('платформенная нормализация: метрика помечена source-платформой, не смешана')`.
  - `test('отозванный OAuth → graceful degrade к публичному viewCount (только YouTube) или manual, не краш')`.
- **Реализация:** `src/attribution/meter.ts` (snapshot+delta), `src/attribution/schedule.ts` (декей-расписание), `src/attribution/platformAdapters/*` (нормализация). Cron через BullMQ repeatable.
- **✅ Готово когда:** 6 тестов зелёные; дельта-биллинг и freeze доказаны.
- **Commit:** `feat: decaying view metering by deltas + per-platform normalization`

### Шаг 5.22 — Билл показов + аудит-кросс-чек + честные ограничения 🛑 ЧЕКПОИНТ
- **Цель / DoD:** `billable_impressions = Δviews × banner_visibility_factor` → conversion(kind=impression) → запускает Conversion-движок (Блок E) → commission → ledger → cpm usage (Блок F). Параллельно (не блокируя биллинг) аудит: velocity-аномалии, YouTube public-viewCount кросс-чек, discrepancy>15% → hold settlement. Честные ограничения doc 03 §5.4 закодированы как метки.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/attribution/billImpressions.test.ts`, integration):
  - `test('billable = delta_views × visibility_factor (1.0 для persistent)')`.
  - `test('биллинг показов триггерит commission → ledger accrual')` — цепочка замкнута.
  - `test('velocity-аномалия (плоско→вертикально) ставит audit hold, биллинг продолжается')`.
  - `test('YouTube OAuth view_count vs public viewCount расхождение >15% → settlement hold')`.
  - `test('каждая конверсия несёт метку attribution_grade=influencer_view (не verified_display)')` — честный фрейминг doc 03 §5.4 п.1.
  - `test('неонбордженный репост невидим: числа помечены floor=true')` — doc 03 §5.4 п.2.
- **Реализация:** `src/attribution/billImpressions.ts`, `src/attribution/audit.ts` (velocity + cross-check, async, не блокирует).
- **✅ Готово когда:** 6 тестов зелёные; ограничения зафиксированы метками в данных и тестах.
- **🛑 ЧЕКПОИНТ ЧП-8:** основатель ревьюит атрибуцию: дельта-биллинг, freeze, аудит-холды, и — важно — что **честные ограничения** (influencer-grade view, floor-числа, нет viewability) явно закодированы и не выдаются за verified-display. Может изменить пороги аудита, окно freeze, hold-политику.
- **Commit:** `feat: bill impressions + fraud audit + honest attribution grading`

---

## Блок H — Payout / settlement (ЧП-9)

### Шаг 5.23 — Monthly settlement (накопленные дельты → payout-кандидаты)
- **Цель / DoD:** `settleMonth(period)` агрегирует `creator_payable` из ledger за период, исключает audit-held, формирует `payouts` row (status=pending) на креатора. Идемпотентно по `(creator_id, period)`.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/payout/settlement.test.ts`, integration):
  - `test('settle агрегирует все creator_payable периода в один payout')`.
  - `test('audit-held конверсии исключены из payout')`.
  - `test('повторный settle того же периода идемпотентен (тот же payout)')`.
  - `test('payout-сумма == sum(ledger creator_payable периода) минус held')` — сверка до копейки.
  - `test('нулевой баланс не создаёт payout')`.
- **Реализация:** `src/payout/settlement.ts` (BullMQ repeatable monthly).
- **✅ Готово когда:** 5 тестов зелёные.
- **Commit:** `feat: monthly settlement aggregates ledger into payouts`

### Шаг 5.24 — Выплата креатору в USDT через `PaymentProvider.createPayout` (крипто-PSP) 🛑 ЧЕКПОИНТ
- **Цель / DoD:** `executePayout(payout)` через `PaymentProvider.createPayout` (**выплата USDT** на крипто-адрес/кошелёк креатора — аналог Stripe Connect transfer), идемпотентно по `payout.id` (наш idempotency key + idempotency-ключ PSP). Обновляет `payouts.status pending→paid`/`failed`. Webhook PSP (`payout.succeeded`/`payout.failed`) финализирует.
- **Репозитории/команды:** SDK крипто-PSP (Выплаты/mass-payout). Фикстуры уведомлений PSP для webhook-тестов.
- **Тесты СНАЧАЛА** (`src/payout/executePayout.test.ts`, integration + mocked `PaymentProvider`):
  - `test('executePayout шлёт createPayout на USDT-адрес креатора с idempotency key = payout.id')`.
  - `test('повторный executePayout НЕ шлёт вторую выплату')` — наша guard + idempotency PSP.
  - `test('payout.succeeded вебхук переводит payout→paid')`.
  - `test('payout.failed вебхук переводит payout→failed с reason')`.
  - `test('payout без привязанного USDT-адреса креатора → held reason=no_payout_address')`.
  - `test('webhook с невалидной подписью → 400, состояние не меняется')` — security (common/security).
- **Реализация:** `src/payout/executePayout.ts`, `src/app/api/webhooks/payments/route.ts` (`PaymentProvider.verifyWebhook` → finalize).
- **✅ Готово когда:** 6 тестов зелёные; идемпотентность выплаты доказана; подпись вебхука верифицируется ДО мутации (doc 01 §3 паттерн).
- **🛑 ЧЕКПОИНТ ЧП-9:** основатель ревьюит выплаты: корректна ли сумма USDT, идемпотентна ли выплата, как обрабатывается отсутствие крипто-адреса, верифицируются ли вебхуки. Может изменить payout-расписание, KYC/AML-гейт, сеть USDT (TRC-20/ERC-20), валютную логику.
- **Commit:** `feat: creator USDT payout via PaymentProvider.createPayout + webhook finalization`

---

## Блок I — Сквозной e2e + гейт фазы (ЧП-10)

### Шаг 5.25 — Advertiser/creator консоли: минимальный UI (списки + статусы)
- **Цель / DoD:** минимальные UI-страницы (Next.js + дизайн-токены oklch из doc 02): advertiser — список офферов + входящие заявки + accept-кнопка; creator — browse офферов + мои заявки + статус выплат. Не template-look: иерархия, статус-чипы, hover/focus-состояния (web/design-quality).
- **Репозитории/команды:** shadcn/launch-ui компоненты (из P0 web).
- **Тесты СНАЧАЛА** (`e2e/console.spec.ts`, Playwright):
  - `test('advertiser видит свой оффер со статус-чипом active')`.
  - `test('advertiser принимает заявку → статус заявки accepted в UI')`.
  - `test('creator видит eligible-оффер в browse и статус выплаты')`.
  - `test('клавиатурная навигация по accept-кнопке работает (a11y)')`.
- **Реализация:** `src/app/(advertiser)/offers/page.tsx`, `src/app/(advertiser)/applications/page.tsx`, `src/app/(creator)/marketplace/page.tsx`, `src/app/(creator)/payouts/page.tsx` + статус-компоненты.
- **✅ Готово когда:** 4 Playwright-теста зелёные; визуальный скриншот на 375/768/1440 без overflow (web/testing).
- **Commit:** `feat: minimal advertiser/creator marketplace consoles`

### Шаг 5.26 — Сквозной e2e маркетплейс-флоу 🛑 ЧЕКПОИНТ
- **Цель / DoD:** один Playwright-сценарий проходит весь цикл: advertiser постит оффер → активируется → creator применяет к клипу → accepted → клип рендерится с этим баннером (golden-проба) → conversion записана → payout начислен → usage_event зафиксирован. Это «#1 правило основателя» в исполнении.
- **Репозитории/команды:** Playwright + render-воркер + mocked `PaymentProvider`/platform APIs.
- **Тесты СНАЧАЛА** (`e2e/marketplace-flow.spec.ts`, Playwright):
  - `test('full flow: post offer → apply → accept → render → conversion → payout')` — единый сценарий со всеми этапами, ассертит на каждом стыке (offer active, application accepted, impression_unit rendered с правильным offerId, conversion с delta, ledger accrual, payout pending, usage_event записан).
  - `test('idempotency: повтор accept+render+meter не задваивает ни impression_unit, ни usage, ни payout')` — сводный no-double-charge.
  - `test('rejected application НЕ доходит до рендера/начисления')` — негативный путь.
  - `test('exhausted offer (бюджет исчерпан) перестаёт принимать заявки')`.
- **Реализация:** `e2e/marketplace-flow.spec.ts` + сид-хелперы `e2e/helpers/seed.ts` (создание advertiser/creator/clip-fixture).
- **✅ Готово когда:** 4 e2e зелёные; **глобальное покрытие ≥80%** (`vitest --coverage` + pytest-cov); CI зелёный.
- **🛑 ЧЕКПОИНТ ЧП-10:** основатель прогоняет сквозной сценарий, подтверждает «клип, который сам себя окупает» работает end-to-end, ревьюит покрытие. Зелёный свет на деплой staging.
- **Commit:** `test: end-to-end marketplace flow (post→apply→accept→render→convert→payout)`

---

## Выход фазы (Phase exit criteria)

- [ ] **Каталог офферов:** advertiser публикует оффер по JSON-схеме doc 03 §1, lifecycle `draft→in_review→active→…` работает, brand-safety-гейт оффера переводит в `active` (ЧП-2).
- [ ] **Browse/apply/match:** creator видит eligible+scored офферы, подаёт заявку, дубли защищены (ЧП-3).
- [ ] **Acceptance:** принятие генерит `impression_unit_id`, детерминированно привязывает оффер к рендеру через `input_hash`, идемпотентно (ЧП-4).
- [ ] **Рендер с оффером:** клип рендерится с принятым баннером, golden-fixture подтверждает баннер в кадре + FTC-дисклеймер, детерминизм доказан (ЧП-5).
- [ ] **cliq-субстрат:** Link→Conversion→Commission (Function/Condition/Effect) — чистый детерминированный движок; все 4 payout-модели (`cpm/per_1k_views/flat/hybrid`) сверены до копейки на `decimal.js`; double-entry ledger идемпотентен (ЧП-6).
- [ ] **Metered usage (наш ledger):** события usage (per-clip/per-render/cpm) идемпотентны — **нет двойного списания на ретрае** (идемпотентность на нашей unique-таблице `usage_events.paymentIdempotencyKey`) (ЧП-7).
- [ ] **Attribution v1:** creator-OAuth метеринг по дельтам, затухающее расписание + freeze d90, аудит-кросс-чек, **честные ограничения зафиксированы метками** (influencer-grade view, floor-числа, не verified-display) (ЧП-8).
- [ ] **Payout:** monthly settlement → выплата креатору в USDT через `PaymentProvider.createPayout` (крипто-PSP), идемпотентно, вебхук-подпись верифицируется до мутации, KYC/AML + крипто-адрес-гейт (ЧП-9).
- [ ] **Сквозной e2e зелёный:** `post offer → apply → accept → render → conversion → payout → metered` (ЧП-10).
- [ ] **Идемпотентность доказана сводным тестом:** повтор accept+render+meter+payout не задваивает ничего.
- [ ] **Покрытие ≥80%** глобально (Vitest + pytest-cov); детерминированные ядра (offer-rules, eligibility, conversion engine, commission calc) — 100%.
- [ ] **Безопасность:** filtergraph-injection защита (doc 01 §6 / doc 03 §3.7), вебхук-подписи, шифрование OAuth-токенов, no-secrets-in-code — все чек-листы common/security пройдены.
- [ ] **Лицензионная чистота:** ни строки из `cliq` (no-license) или SamurAIGPT не скопировано; cliq использован только как clean-room блюпринт (ADR P5-001).
- [ ] Деплой на `staging` Railway, миграции в `preDeployCommand`, smoke-проверка сквозного флоу на staging.
