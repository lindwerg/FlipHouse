# P6 — Публикация (YT / TikTok / IG, анти-блок) + OAuth + PWA + push

> Фаза дистрибуции FlipHouse. Превращает «готовый клип в R2» в «опубликованный пост в YouTube / TikTok / Instagram» — легально, через официальные API, с обязательным human-preview и анти-блок трансформами, плюс PWA-оболочка с web-push «Твои нарезки готовы», вылетающим из вебхука рендер-задачи.
>
> Полностью реализует документ [`04-ИНТЕГРАЦИИ-PWA-AI-ПУБЛИКАЦИЯ.md`](../docs/04-ИНТЕГРАЦИИ-PWA-AI-ПУБЛИКАЦИЯ.md) §1 (PWA/push), §3 (YouTube), §4 (TikTok/IG + анти-блок), §5 (мультиплатформенная OAuth/токен-модель). §2 (OpenRouter-адаптер) — **не** в этой фазе (он часть рендер-движка, P1).

---

## Цель фазы (Phase goal)

Дать креатору возможность **подключить N социальных аккаунтов** (несколько каналов/профилей на платформу), **просмотреть и одобрить** каждый клип, и **опубликовать его в выбранные платформы** одним действием — так, чтобы:

1. **Identity ≠ Connections** — логин (Auth.js v5, минимальные scopes) физически отделён от публикационных коннектов (своя зашифрованная таблица `SocialConnection`).
2. **Токены зашифрованы** AES-256-GCM (envelope encryption, `encKeyVersion` для ротации master-key) — никогда не в plaintext, никогда не в `accounts` Auth.js.
3. **Три несовместимые refresh-модели** (YouTube OAuth2-grant / TikTok rotating 365d / IG sliding-window 60d) спрятаны за единым `getValidAccessToken(connectionId)`.
4. **Публикация за абстракцией `PublishProvider`**: фаза 1 — `AyrshareProvider` (уже одобрен платформами); направление 2 — `YouTubeDirect` / `TikTokDirect` / `InstagramDirect` как вторая реализация того же интерфейса.
5. **АНТИ-БЛОК чеклист дока 04 §4.3 enforced на уровне кода и тестов**: срезать ВСЕ сторонние watermark, НЕ вжигать брендинг FlipHouse, per-platform транскод (разные хэши/спеки), свежая per-platform метадата, AIGC-лейблы (`is_aigc`/IG AI-label), обязательное human preview+approval, jitter-планирование (не burst круглыми числами), pre-flight лимит-чеки, FTC/ASA-disclosure не снимается.
6. **PWA**: Serwist (precache + offline shell) + DB-backed web-push, отправляемый из обработчика вебхука рендера; прунинг просроченных подписок по 404/410; gated opt-in (не на загрузке); инсталлируемость через манифест.

**Founder's rule #1 — ZERO bugs.** Каждый шаг = TDD: сначала падающие тесты с точными именами и ассертами → RED → минимальная реализация → GREEN → рефактор → коммит. Шаг не «готов», пока тесты не зелёные И coverage-гейт держится (≥80%, доменные модули токенов/анти-блока — ≥95%).

---

## Зависимости (какие фазы должны быть закрыты до старта)

| Фаза | Что именно нужно из неё | Чем пользуемся |
|---|---|---|
| **P0 — Каркас и инфра** | Railway-проект (prod+staging), сервис `web` (Next.js App Router, TS), Postgres (`DATABASE_PRIVATE_URL`), Redis, `railway.json` healthcheck, Auth.js базовый логин | Логин-сессия даёт `user.id`, к которому привязываются коннекты; `web`-сервис хостит PWA, server actions, connection-роуты |
| **P1 — Клиппинг-движок MVP** | `clipId` + готовый клип в R2 (`clips/{clipId}/master.mp4`), `PublishJob`/контракт «клип готов», webhook-receiver рендера (`docs/01 §3`) | Источник медиа для публикации; вебхук рендера — реальный триггер push «нарезки готовы» |
| **P2 — Ad-insertion (баннер + FTC-дисклеймер)** | Несъёмный FTC/ASA-disclosure оверлей уже вшит в рендер | Анти-блок шаг «disclosure не снимается» опирается на то, что дисклеймер уже в пикселях клипа; публикация лишь верифицирует его наличие, не накладывает |

> P6 **не** требует P3 (native inpainting), P4 (маркетплейс), P5 (trust-слой). Публиковать можно баннер-клипы из P2.

---

## Репозитории, клонируемые/используемые в этой фазе

Всё в `/vendor` (вендоринг) либо через пакетный менеджер (`pnpm add`). Реальные команды:

```bash
# --- PWA / push (doc 04 §1.4) ---
pnpm add @serwist/next web-push
pnpm add -D serwist @types/web-push
pnpm dlx web-push generate-vapid-keys   # одноразово -> VAPID_* в Railway env

# --- Auth.js v5 + Prisma (doc 04 §5.2, §5.8) ---
pnpm add next-auth@beta @auth/prisma-adapter
pnpm add -D prisma
pnpm add @prisma/client

# --- Публикация фаза 1: Ayrshare за PublishProvider (doc 04 §5.3) ---
# У Ayrshare нет официального npm SDK — вызываем REST через undici (встроен в Node 20+),
# обёртка в src/publish/providers/ayrshare/. Эталон API: https://www.ayrshare.com/docs/
git clone https://github.com/ayrshare/social-post-api-node vendor/ayrshare-node
#   -> из vendor берём ТОЛЬКО форму вызовов (endpoints, поля /post, Profile-Key header)
#      как референс; собственная типизированная обёртка, не зависимость

# --- Публикация направление 2: YouTube direct (doc 04 §3.2) ---
pnpm add googleapis            # google-api-nodejs-client: oauth2 + youtube.videos.insert (resumable)
git clone https://github.com/youtube/api-samples vendor/youtube-api-samples
#   -> эталон resumable videos.insert: vendor/youtube-api-samples/python/upload_video.py
#      (порт логики chunked next_chunk на googleapis Node)

# --- TikTok direct (doc 04 §4.1): нет официального Node SDK, REST через undici ---
#   эталон контракта: https://developers.tiktok.com/doc/content-posting-api-get-started
#   PKCE через встроенный node:crypto, обёртка собственная

# --- Instagram Graph direct (doc 04 §4.2): REST через undici, обёртка собственная ---

# --- Тестовая гарнитура ---
pnpm add -D vitest @vitest/coverage-v8 vitest-fetch-mock msw
pnpm add -D @playwright/test
pnpm dlx playwright install --with-deps chromium firefox webkit
```

> Лицензии не препятствие (founder: «pick the best»). `googleapis` (Apache-2.0), `web-push`/`serwist` (MIT), `next-auth` (ISC), `msw` (MIT). Ayrshare-SDK-репо — только референс контракта, в зависимости не тянем (своя тонкая типизированная обёртка контролируема и тестируема).

---

## Чекпоинты (где фаундер вмешивается)

1. 🛑 **ЧЕКПОИНТ A** (после Шаг 6.4) — Token Vault + `getValidAccessToken`: ревью схемы шифрования, обработки ротации refresh, key-version. *Founder может сменить KMS-стратегию / поля Prisma до того, как на них завяжется публикация.*
2. 🛑 **ЧЕКПОИНТ B** (после Шаг 6.9) — Connection-флоу (start/callback) для всех трёх платформ: ревью scope-минимизации, CSRF-`state`, PKCE. *Founder может изменить набор scopes / UX подключения.*
3. 🛑 **ЧЕКПОИНТ C** (после Шаг 6.13) — Анти-блок transform-слой: ревью, что именно срезается/чистится/маркируется. *Founder утверждает анти-блок политику до первой реальной публикации.*
4. 🛑 **ЧЕКПОИНТ D** (после Шаг 6.16) — `PublishProvider` + Ayrshare end-to-end на staging (реальная тест-публикация `SELF_ONLY`/draft): ревью human-preview+approval UX и частичных отказов. *Founder утверждает публикационный UX и решает Ayrshare-vs-direct таймлайн.*
5. 🛑 **ЧЕКПОИНТ E** (после Шаг 6.20) — PWA + web-push из вебхука рендера на staging-устройстве: ревью инсталлируемости и реального push «нарезки готовы». *Founder проверяет на своём телефоне.*
6. 🛑 **ЧЕКПОИНТ F** (после Шаг 6.23) — Direct-провайдеры (YouTube/TikTok/IG) за тем же интерфейсом + аудит-гейтинг: ревью готовности к подаче на platform review. *Founder решает, запускать ли official app review.*

---

## Тестовая стратегия (для всей фазы)

- **TS unit/integration** → Vitest. Внешние HTTP (Google/TikTok/IG/Ayrshare/push-сервисы) мокаются через **MSW** (`msw/node`) — детерминированные хендлеры, ассертим **исходящий запрос** (URL, заголовки, тело), не только ответ.
- **E2E** → Playwright (3 браузера: chromium/firefox/webkit). PWA-инсталлируемость, манифест, gated push opt-in, preview+approval UI.
- **Шифрование** → round-trip + tamper-detection (GCM auth-tag) unit-тесты, доменное покрытие ≥95%.
- **Анти-блок** → каждый transform имеет тест, ассертящий ПРИМЕНЕНИЕ (нет watermark-региона, метадата set, AIGC-флаг true, нет FlipHouse-брендинга) — НЕ «функция вызвалась».
- **FFmpeg/медиа-проба** (срез watermark, per-platform транскод) → ассерт на ВЫХОД: ширина/высота/длительность через `ffprobe`, наличие/отсутствие оверлей-региона через frame-hash/pixel-sample, moov-atom-front для IG. Golden-fixture набор клипов в `tests/fixtures/clips/`.
- **Coverage-гейт** в CI: глобально ≥80%; `src/connections/vault/**`, `src/publish/antiblock/**`, `src/connections/refresh/**` ≥95%. CI падает, если гейт не держится.

Конфиг (создаётся в Шаг 6.1):
```ts
// vitest.config.ts (фрагмент)
coverage: {
  provider: "v8",
  thresholds: {
    global: { lines: 80, functions: 80, branches: 80, statements: 80 },
    "src/connections/vault/**":   { lines: 95, functions: 95, branches: 90 },
    "src/publish/antiblock/**":   { lines: 95, functions: 95, branches: 90 },
    "src/connections/refresh/**": { lines: 95, functions: 95, branches: 90 },
  },
}
```

---

# Шаги

> Нумерация `6.<n>`. Каждый шаг = один git-commit, атомарный, проходимый одним ultracode-проходом. Формат строго по контракту.

---

### Шаг 6.1 — Каркас фазы: Prisma-схема публикации, env-контракт, тест-гарнитура

- **Цель / DoD:** В `web`-сервисе появляются Prisma-модели публикации (`Platform`/`ConnectionStatus`/`ProviderKind` enums, `SocialConnection`, `PublishJob`, `PublishTarget` — точь-в-точь doc 04 §5.5) + таблица `push_subscriptions` (doc 04 §1.9). Vitest+coverage-гейт и MSW-сервер сконфигурированы. Миграция применяется чисто на staging Postgres. Никакой бизнес-логики — только схема + гарнитура + env-валидация.
- **Репозитории/команды:**
  ```bash
  pnpm add -D prisma vitest @vitest/coverage-v8 msw @playwright/test
  pnpm add @prisma/client
  pnpm dlx prisma init   # если ещё нет
  ```
- **Тесты СНАЧАЛА** (`tests/schema/prisma-schema.test.ts`, Vitest):
  - `test('SocialConnection has unique [userId, platform, platformAccountId]')` — парсит `schema.prisma`, ассертит наличие `@@unique([userId, platform, platformAccountId])`.
  - `test('SocialConnection has index [status, accessTokenExpiresAt] for refresh worker scan')`.
  - `test('token ciphertext columns are Bytes and nullable (AGGREGATOR has no tokens)')` — `encAccessToken/Iv/Tag`, `encRefreshToken/Iv/Tag`, `encKeyVersion` присутствуют и `Bytes?`.
  - `test('ProviderKind defaults to AGGREGATOR')`.
  - `test('PublishTarget carries per-target status + errorCode for partial failure')`.
  - `tests/env/env-schema.test.ts`: `test('env schema rejects missing VAPID_PRIVATE_KEY')`, `test('env schema rejects missing TOKEN_VAULT_MASTER_KEY')` — zod-схема env падает без обязательных ключей.
  - Harness: Vitest (`tests/setup.ts` поднимает `msw` server `beforeAll`/`afterEach reset`/`afterAll close`).
- **Реализация:**
  - `prisma/schema.prisma` — модели из doc 04 §5.5 verbatim + `model PushSubscription` (`id`, `userId`, `endpoint @unique`, `p256dh`, `auth`, `createdAt`, `@@index([userId])`).
  - `src/env.ts` — zod-схема обязательных env (`TOKEN_VAULT_MASTER_KEY`, `TOKEN_VAULT_KEY_VERSION`, `VAPID_*`, `NEXT_PUBLIC_VAPID_PUBLIC_KEY`, `AYRSHARE_API_KEY`, OAuth client id/secret per-platform), `.parse(process.env)` на старте.
  - `vitest.config.ts` с coverage-гейтом (см. «Тестовая стратегия»).
  - `tests/setup.ts`, `playwright.config.ts` (3 проекта: chromium/firefox/webkit).
  - `pnpm prisma migrate dev --name p6_publishing_schema`.
- **✅ Готово когда:** все schema/env-тесты зелёные; `prisma migrate` применился на staging без ошибок; `pnpm vitest run` зелёный; coverage-конфиг активен.
- **Commit:** `feat: P6 publishing prisma schema, env contract, test harness`

---

### Шаг 6.2 — AES-256-GCM примитив шифрования (envelope, key-version)

- **Цель / DoD:** Чистая, не зависящая от БД крипто-функция `seal`/`open` (AES-256-GCM): принимает plaintext + master-key + keyVersion → `{ ciphertext, iv, tag, keyVersion }` и обратно. Tamper по ciphertext/tag/iv → throw. Покрытие ≥95%.
- **Репозитории/команды:** только `node:crypto` (встроен) — без внешних зависимостей.
- **Тесты СНАЧАЛА** (`src/connections/vault/crypto.test.ts`, Vitest):
  - `test('seal then open returns original plaintext')` — round-trip UTF-8 и бинарь.
  - `test('seal produces a fresh 12-byte IV each call')` — два `seal` одного plaintext дают разные `iv` и разный `ciphertext`.
  - `test('open throws on tampered ciphertext (GCM auth fails)')` — флипнуть байт ciphertext → throw.
  - `test('open throws on tampered auth tag')`.
  - `test('open throws on wrong master key')`.
  - `test('keyVersion round-trips so master-key rotation needs no bulk re-encrypt')` — seal v1, open даёт `keyVersion===1`; resolver выбирает ключ по версии.
  - `test('rejects master key that is not 32 bytes')`.
- **Реализация:** `src/connections/vault/crypto.ts`:
  - `seal(plaintext: Buffer, key: Buffer, keyVersion: number): SealedToken` — `createCipheriv('aes-256-gcm', key, randomBytes(12))`, вернуть `{ ciphertext, iv, tag: cipher.getAuthTag(), keyVersion }`.
  - `open(sealed: SealedToken, keyResolver: (v:number)=>Buffer): Buffer` — `createDecipheriv`, `setAuthTag`, throw на провал.
  - `KeyRing` — map `keyVersion → 32-byte key` из env (`TOKEN_VAULT_MASTER_KEY` base64, `TOKEN_VAULT_KEY_VERSION`).
- **✅ Готово когда:** все крипто-тесты зелёные; модуль `src/connections/vault/**` coverage ≥95%; tamper-кейсы все бросают.
- **Commit:** `feat: AES-256-GCM token sealing primitive with key-version envelope`

---

### Шаг 6.3 — Token Vault: persist/load зашифрованных токенов в SocialConnection

- **Цель / DoD:** `TokenVault` пишет/читает токены коннекта через crypto-примитив в реальные `enc*`-колонки `SocialConnection`. AGGREGATOR-строки токенов не несут. `aggregatorProfileKey` (секрет Ayrshare) тоже шифруется.
- **Репозитории/команды:** Prisma client (из 6.1). Тестовая БД — Postgres staging-schema через `prisma migrate reset` в CI или testcontainers; в unit-слое репозиторий мокается, в integration — реальная транзакция.
- **Тесты СНАЧАЛА** (`src/connections/vault/tokenVault.integration.test.ts`):
  - `test('storeDirectTokens writes ciphertext, never plaintext, to DB row')` — после записи читаем сырую строку Prisma, ассертим что `encAccessToken` ≠ исходный токен и расшифровка даёт исходный.
  - `test('loadAccessToken decrypts round-trip')`.
  - `test('storing rotated refresh token overwrites prior refresh ciphertext')` — критично для TikTok.
  - `test('AGGREGATOR connection stores encrypted aggregatorProfileKey, no token columns set')`.
  - `test('encKeyVersion persisted matches active key ring version')`.
- **Реализация:** `src/connections/vault/tokenVault.ts`:
  - `storeDirectTokens(connectionId, { access, refresh, accessExpiresAt, refreshExpiresAt })` — seal каждый, upsert колонок.
  - `loadAccessToken(connectionId)` / `loadRefreshToken(connectionId)` — open через KeyRing.
  - `storeAggregatorRef(connectionId, { profileKey, ref })` — seal profileKey.
- **✅ Готово когда:** integration-тесты зелёные на реальном Postgres; в БД нет plaintext-токенов (проверено сырым селектом); vault-coverage ≥95%.
- **Commit:** `feat: TokenVault persists AES-256-GCM sealed tokens into SocialConnection`

---

### Шаг 6.4 — `getValidAccessToken`: ленивый refresh + диспетчер стратегий (заглушки)

- **Цель / DoD:** Центральная функция `getValidAccessToken(connectionId)` (doc 04 §5.4): дешифровать; если `expires_at` > 5 мин — вернуть; иначе диспатч в per-platform refresh-стратегию; сохранить новый access + новый `expires_at` + (возможно) ротированный refresh; при отказе — `status='REAUTH_REQUIRED'`, никогда silent swallow. Стратегии пока — инжектируемые интерфейсы с тестовыми реализациями (реальные провайдеры — 6.6–6.8).
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/connections/getValidAccessToken.test.ts`, refresh-стратегии мокнуты):
  - `test('returns cached access token when expiry more than 5 minutes away')` — стратегия НЕ вызывается.
  - `test('refreshes when token expires within 5-minute skew window')`.
  - `test('persists rotated refresh token returned by strategy (TikTok case)')`.
  - `test('sets status REAUTH_REQUIRED and throws ReauthRequiredError when refresh fails')`.
  - `test('YouTube with no captured refresh_token goes REAUTH_REQUIRED immediately, never fakes')`.
  - `test('AGGREGATOR connection short-circuits — no local refresh attempted')`.
  - `test('two concurrent calls do not double-refresh (single-flight lock)')` — два параллельных вызова на истёкшем токене дают один refresh.
- **Реализация:** `src/connections/getValidAccessToken.ts`:
  - `RefreshStrategy` интерфейс `{ refresh(conn): Promise<RefreshResult> }`, реестр `Record<Platform, RefreshStrategy>`.
  - 5-мин skew-константа `REFRESH_SKEW_MS = 5 * 60_000`.
  - Single-flight: мьютекс по `connectionId` (in-memory map promise) против двойного refresh.
  - `ReauthRequiredError` (типизированная), запись `status=REAUTH_REQUIRED` + `lastRefreshedAt`.
- **✅ Готово когда:** все тесты зелёные; coverage `src/connections/**` ≥95%; нет пути, где ошибка глотается молча.
- **🛑 ЧЕКПОИНТ A:** Token Vault + `getValidAccessToken` — фаундер ревьюит модель шифрования, обработку ротации refresh, key-version и 5-мин skew. Может сменить KMS-стратегию / поля Prisma до того, как на них завяжется публикация.
- **Commit:** `feat: getValidAccessToken lazy-refresh dispatcher with single-flight + reauth guard`

---

### Шаг 6.5 — CSRF `state` + PKCE утилиты для connection-флоу

- **Цель / DoD:** Утилиты `signState`/`verifyState` (HMAC-подписанный, короткий TTL, привязан к `user.id`+`platform`) и `createPkcePair` (`code_verifier`/`code_challenge` S256). Сервер-сайд хранение `code_verifier` по `state` (Redis, TTL). Doc 04 §5.4.
- **Репозитории/команды:** `node:crypto`, Redis (из P0).
- **Тесты СНАЧАЛА** (`src/connections/oauth/state.test.ts`, `pkce.test.ts`):
  - `test('verifyState accepts freshly signed state bound to user and platform')`.
  - `test('verifyState rejects tampered payload')`.
  - `test('verifyState rejects expired state (TTL passed)')`.
  - `test('verifyState rejects state minted for a different user')`.
  - `test('createPkcePair: challenge is base64url SHA256 of verifier (S256)')` — пересчёт challenge независимо.
  - `test('verifier stored in Redis under state key, retrievable once, then consumed')` — single-use.
- **Реализация:** `src/connections/oauth/state.ts` (HMAC через `TOKEN_VAULT_MASTER_KEY`-derived ключ, `{ userId, platform, nonce, exp }`), `src/connections/oauth/pkce.ts`, `src/connections/oauth/verifierStore.ts` (Redis set/get/del, TTL 600с).
- **✅ Готово когда:** все тесты зелёные; tamper/expiry/cross-user отвергаются; verifier single-use.
- **Commit:** `feat: signed-state CSRF + PKCE pair + single-use verifier store for connect flow`

---

### Шаг 6.6 — YouTube refresh-стратегия (Google OAuth2-grant)

- **Цель / DoD:** Реальная `YouTubeRefreshStrategy` (doc 04 §5.7): стандартный OAuth2 refresh-grant против Google token endpoint. Нет captured `refresh_token` → `REAUTH_REQUIRED` сразу. Обмен code→tokens с `access_type=offline`+`prompt=consent` (форсит refresh).
- **Репозитории/команды:** `pnpm add googleapis`; эталон resumable/auth — `vendor/youtube-api-samples`.
- **Тесты СНАЧАЛА** (`src/connections/refresh/youtube.test.ts`, MSW мокает `oauth2.googleapis.com/token`):
  - `test('exchangeCode posts code with grant_type=authorization_code and returns refresh_token')` — ассерт исходящего тела.
  - `test('refresh posts grant_type=refresh_token and returns new short-lived access token')`.
  - `test('missing refresh_token in connection -> ReauthRequiredError, no network call')`.
  - `test('Google 400 invalid_grant -> ReauthRequiredError (refresh token revoked)')`.
  - `test('new accessTokenExpiresAt computed from expires_in')`.
- **Реализация:** `src/connections/refresh/youtube.ts` — обёртка над `google.auth.OAuth2`, `exchangeCode(code)`, `refresh(conn)`; нормализация в `RefreshResult`. Регистрация в реестре стратегий из 6.4.
- **✅ Готово когда:** тесты зелёные; ассертим именно исходящие grant-параметры; refresh-coverage ≥95%.
- **Commit:** `feat: YouTube OAuth2 refresh strategy (offline grant, reauth on invalid_grant)`

---

### Шаг 6.7 — TikTok refresh-стратегия (rotating refresh, 24h access)

- **Цель / DoD:** `TikTokRefreshStrategy` (doc 04 §4.1/§5.7): refresh против `open.tiktokapis.com/v2/oauth/token/`; access 24ч, refresh 365д; **всегда сохранять ротированный refresh_token** + обновлять `refreshTokenExpiresAt`. PKCE на code-обмене.
- **Репозитории/команды:** REST через `undici` (встроен); эталон — TikTok Content Posting docs.
- **Тесты СНАЧАЛА** (`src/connections/refresh/tiktok.test.ts`, MSW мокает token endpoint):
  - `test('exchangeCode includes code_verifier (PKCE) and client_key in body')`.
  - `test('refresh sends grant_type=refresh_token to v2/oauth/token')`.
  - `test('rotated refresh_token in response is persisted (NOT the old one)')` — главный кейс ротации.
  - `test('refreshTokenExpiresAt set to now + refresh_expires_in (365d nudge)')`.
  - `test('access token expiry set to 24h')`.
  - `test('error_code in body -> ReauthRequiredError')`.
- **Реализация:** `src/connections/refresh/tiktok.ts` — `exchangeCode`/`refresh`, маппинг `open_id`→`platformAccountId`, всегда сериализуем `data.refresh_token` обратно в vault. Регистрация в реестре.
- **✅ Готово когда:** тесты зелёные; ротированный refresh подтверждённо перезаписывает старый; coverage ≥95%.
- **Commit:** `feat: TikTok refresh strategy persisting rotated refresh_token (PKCE, 24h/365d)`

---

### Шаг 6.8 — Instagram refresh-стратегия (sliding-window 60d, нет refresh-grant)

- **Цель / DoD:** `InstagramRefreshStrategy` (doc 04 §4.2/§5.7): НЕТ классического refresh. Short-lived (1ч) → long-lived (60д) через `ig_exchange_token`; in-place refresh long-lived через `GET /refresh_access_token?grant_type=ig_refresh_token` (токен ≥24ч). Пропуск 60-дн окна → `EXPIRED` (полный reconnect).
- **Репозитории/команды:** REST через `undici`; эталон — IG `refresh_access_token` docs.
- **Тесты СНАЧАЛА** (`src/connections/refresh/instagram.test.ts`, MSW мокает `graph.instagram.com`):
  - `test('exchangeShortForLong calls ig_exchange_token and stores 60-day token')`.
  - `test('refresh calls refresh_access_token with grant_type=ig_refresh_token')`.
  - `test('long-lived token younger than 24h is NOT refreshed (API rejects)')`.
  - `test('expired beyond 60-day window -> status EXPIRED, full reconnect required')`.
  - `test('encAccessToken holds long-lived token; no refresh token columns used')` — IG-конвенция doc 04 §5.5.
- **Реализация:** `src/connections/refresh/instagram.ts` — `exchangeShortForLong`, `refresh` (in-place, обновляет `accessTokenExpiresAt = now+60d`). Регистрация в реестре.
- **✅ Готово когда:** тесты зелёные; <24ч не рефрешится; >60д → EXPIRED; coverage ≥95%.
- **Commit:** `feat: Instagram sliding-window refresh strategy (ig_refresh_token, 60-day wall)`

---

### Шаг 6.9 — Connection-роуты: `/connect/[platform]/start` + `/callback` (scope-минимизация)

- **Цель / DoD:** Реальные роуты подключения (doc 04 §5.4): `start` генерит `state`+PKCE, редиректит на authorize **только с publish-scopes этой платформы** (Google `youtube.upload`, TikTok `video.publish`, IG `instagram_business_basic`+`instagram_business_content_publish` — НЕ login-scopes); `callback` валидирует `state`, обменивает code (через стратегии 6.6–6.8), нормализует, шифрует, пишет НОВУЮ строку `SocialConnection`. N коннектов на платформу.
- **Репозитории/команды:** Next.js App Router route handlers.
- **Тесты СНАЧАЛА** (`tests/connect/connect-flow.integration.test.ts`, Auth.js-сессия + провайдеры мокнуты MSW):
  - `test('YouTube start redirects with scope=youtube.upload and access_type=offline & prompt=consent')` — ассерт query authorize-URL; НЕТ широкого `youtube` scope.
  - `test('TikTok start redirects with scope=video.publish and code_challenge (PKCE)')`.
  - `test('Instagram start redirects with only basic+content_publish scopes')`.
  - `test('callback rejects request with invalid state (CSRF)')`.
  - `test('callback creates a SocialConnection row with encrypted tokens and grantedScopes')`.
  - `test('second connect for same user+platform creates a SECOND row (multi-account)')` — `@@unique` не мешает разным `platformAccountId`.
  - `test('login scopes are never requested on connect (identity != connections)')` — нет `openid/email/profile` в connect-URL.
- **Реализация:** `app/connect/[platform]/start/route.ts`, `app/connect/[platform]/callback/route.ts`; `src/connections/scopes.ts` (per-platform publish-scope таблица, doc 04 §5.6); `src/connections/connectionService.ts` (`createConnection`, нормализация токена в модель).
- **✅ Готово когда:** все тесты зелёные; для каждой платформы запрашиваются ТОЛЬКО publish-scopes; CSRF-state enforced; мульти-аккаунт работает.
- **🛑 ЧЕКПОИНТ B:** Connection-флоу для всех трёх платформ — фаундер ревьюит scope-минимизацию, CSRF-`state`, PKCE и UX подключения. Может изменить набор scopes / онбординг.
- **Commit:** `feat: per-platform connect start/callback routes with publish-only scopes`

---

### Шаг 6.10 — Connection Service: list / revoke / capability-check

- **Цель / DoD:** `listConnections(userId)`, `revokeConnection(connectionId)` (status=REVOKED + best-effort provider-revoke), `assertCanPublish(connection)` (проверка `grantedScopes` перед публикацией → ясное «переподключитесь с правами публикации» вместо сырого 403). Doc 04 §5.6.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/connections/connectionService.test.ts`):
  - `test('listConnections returns connections scoped to the user only')`.
  - `test('revokeConnection sets status REVOKED and zeroes token ciphertext')`.
  - `test('assertCanPublish passes when grantedScopes include publish scope')`.
  - `test('assertCanPublish throws MissingPublishScopeError with reconnect hint when scope absent')`.
  - `test('REAUTH_REQUIRED connection is excluded from publishable list')`.
- **Реализация:** дополнить `src/connections/connectionService.ts`; `MissingPublishScopeError` с человекочитаемым сообщением.
- **✅ Готово когда:** тесты зелёные; capability-чек даёт actionable-ошибку, не сырой 403.
- **Commit:** `feat: connection service list/revoke + publish capability assertion`

---

### Шаг 6.11 — Анти-блок: срез сторонних watermark (FFmpeg, ассерт на пиксели)

- **Цель / DoD:** `stripThirdPartyWatermarks(clipPath)` — детект+удаление известных watermark-регионов (CapCut/TikTok-export/IG-download) через FFmpeg crop/delogo, БЕЗ затрагивания несъёмного FTC-дисклеймера (P2). Doc 04 §4.3 «Срезать ВСЕ сторонние watermark». Ассерт на ВЫХОД (пиксели), не «функция вызвана».
- **Репозитории/команды:** FFmpeg LGPL-образ из doc 01 §6 (уже собран в P1). Golden-фикстуры: `tests/fixtures/clips/with-capcut-watermark.mp4`, `clean.mp4`.
- **Тесты СНАЧАЛА** (`src/publish/antiblock/watermark.media.test.ts`, ffprobe + pixel-sample хелпер):
  - `test('output has no opaque pixels in known CapCut watermark region (corner sample)')` — сэмплим угол до/после, ассертим что регион очищен/перекрыт.
  - `test('output keeps the same width/height/duration (no re-frame side effect)')` — ffprobe.
  - `test('FTC disclaimer band pixels are preserved (anti-block must NOT remove our disclosure)')` — сэмпл disclosure-региона неизменён.
  - `test('clean input passes through unchanged (idempotent, no spurious crop)')` — frame-hash равен.
  - `test('TikTok-exported watermark in moving corner is removed across sampled frames')` — несколько таймкодов.
- **Реализация:** `src/publish/antiblock/watermark.ts` — таблица known-watermark регионов per-source, FFmpeg `delogo`/`crop`+`pad` фильтр-граф через `-filter_complex_script` (injection-safe, doc 01 §6); pixel-sample/ffprobe хелперы в `tests/helpers/media.ts`.
- **✅ Готово когда:** медиа-тесты зелёные на golden-фикстурах; disclosure сохранён; clean-вход идемпотентен; `src/publish/antiblock/**` coverage ≥95%.
- **Commit:** `feat: strip third-party watermarks preserving FTC disclosure (pixel-asserted)`

---

### Шаг 6.12 — Анти-блок: per-platform транскод + чистка метадаты + AIGC-лейбл

- **Цель / DoD:** `transcodeForPlatform(clip, platform)` (doc 04 §4.3): разные файлы/хэши per-platform с нативными спеками — **TikTok** MP4/H.264 9:16 1080×1920; **IG** moov-atom **впереди** (`-movflags +faststart`), H.264/AAC, 3–90с; **YouTube** 9:16 ≤180с. Чистка метадаты (`-map_metadata -1` + per-platform теги). Маркеры AIGC: `is_aigc=true` (TikTok payload-флаг), IG AI-label, YT `containsSyntheticMedia=true` — выставляются в publish-payload (не в файл), но контракт фиксируется здесь.
- **Репозитории/команды:** FFmpeg-образ; `ffprobe` для ассертов.
- **Тесты СНАЧАЛА** (`src/publish/antiblock/transcode.media.test.ts`):
  - `test('IG output has moov atom before mdat (faststart)')` — парсим atom-порядок из первых байт mp4.
  - `test('TikTok output is H.264 9:16 1080x1920 MP4')` — ffprobe codec/dims.
  - `test('per-platform outputs have DIFFERENT file hashes for the same source clip')` — не байт-идентичны (главный кросс-пост суппрессор).
  - `test('source metadata is stripped (-map_metadata -1): no leftover creation tags)')` — ffprobe format tags пусты/перезаписаны.
  - `test('YouTube clip rejected if duration > 180s')`.
  - `test('IG clip rejected if duration outside 3-90s')`.
  - `test('aigcLabels() returns is_aigc=true for TikTok, synthetic=true for YouTube, ai_label for IG')` — payload-контракт.
- **Реализация:** `src/publish/antiblock/transcode.ts` (per-platform FFmpeg-профили, validation gates), `src/publish/antiblock/aigc.ts` (payload-маркеры). Atom-парсер хелпер в `tests/helpers/mp4.ts`.
- **✅ Готово когда:** медиа-тесты зелёные; хэши per-platform различны; moov-front для IG; длительности валидируются; coverage ≥95%.
- **Commit:** `feat: per-platform transcode, metadata strip, AIGC labels (anti-block specs)`

---

### Шаг 6.13 — Анти-блок: свежая per-platform метадата + проверка «нет брендинга FlipHouse»

- **Цель / DoD:** `buildPlatformCaption(clip, platform)` (doc 04 §4.3): уникальная подпись, уникальные первые 3 слова, нативные хэштеги per-platform; НИКОГДА не идентичный caption в две API. Гард `assertNoFlipHouseBranding(caption, mediaOverlays)`: блокирует брендинг/логотип/промо-ссылки FlipHouse в подписи И вжатый брендинг в кадр (TikTok удаляет контент/блок; IG режет охват).
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/publish/antiblock/caption.test.ts`):
  - `test('captions for two platforms differ in their first three words')`.
  - `test('captions for two platforms are never byte-identical')`.
  - `test('hashtags are platform-native (TikTok vs IG sets differ)')`.
  - `test('assertNoFlipHouseBranding throws when caption contains fliphouse.app link')`.
  - `test('assertNoFlipHouseBranding throws when caption contains "FlipHouse" brand token')`.
  - `test('assertNoFlipHouseBranding passes a clean creator caption')`.
  - `test('disclosure text (FTC) is allowed and required — not flagged as branding')`.
- **Реализация:** `src/publish/antiblock/caption.ts` (per-platform шаблоны, hashtag-наборы, dedupe первых слов), `src/publish/antiblock/branding.ts` (allowlist/denylist токенов, regex ссылок). Disclosure НЕ путать с брендингом.
- **✅ Готово когда:** тесты зелёные; брендинг блокируется; disclosure разрешён; captions гарантированно различны; coverage ≥95%.
- **🛑 ЧЕКПОИНТ C:** Анти-блок transform-слой (watermark / транскод / метадата / AIGC / branding) — фаундер ревьюит, что именно срезается, чистится, маркируется и блокируется. Утверждает анти-блок политику до первой реальной публикации.
- **Commit:** `feat: fresh per-platform captions + no-FlipHouse-branding guard`

---

### Шаг 6.14 — Jitter-планировщик + pre-flight лимит-чеки + rate-guard

- **Цель / DoD:** `scheduleWithJitter(targets)` (doc 04 §4.3 «Ритм и лимиты»): рандомные минутные оффсеты вместо burst круглыми числами. Pre-flight: TikTok `creator_info/query` каждый пост (abort при лимитах), IG `content_publishing_limit` (100/24ч, 400 контейнеров/24ч), TikTok rate 6 req/min/user. Backoff на `403 spam_risk_*` / `reached_active_user_cap`.
- **Репозитории/команды:** MSW для лимит-эндпоинтов.
- **Тесты СНАЧАЛА** (`src/publish/scheduling/jitter.test.ts`, `preflight.test.ts`):
  - `test('jitter spreads N posts across distinct non-round minute offsets')` — не все на :00, разброс детерминирован seed.
  - `test('jitter offsets stay within configured window')`.
  - `test('TikTok preflight queries creator_info before every post')` — MSW счётчик.
  - `test('preflight aborts with LimitReachedError when creator_info reports limit hit')`.
  - `test('IG preflight reads content_publishing_limit and blocks at 100/24h')`.
  - `test('TikTok rate-guard enforces <=6 req/min per user token')` — 7-й вызов в окне отложен/отклонён.
  - `test('403 spam_risk_too_many_posts triggers backoff, not crash')`.
- **Реализация:** `src/publish/scheduling/jitter.ts` (seedable RNG для тестируемости), `src/publish/scheduling/preflight.ts` (per-platform лимит-квери), `src/publish/scheduling/rateGuard.ts` (token-bucket 6/min, backoff).
- **✅ Готово когда:** тесты зелёные; jitter не даёт круглых burst; pre-flight блокирует на лимитах; rate-guard держит 6/min.
- **Commit:** `feat: jittered cadence, pre-flight limit checks, TikTok rate-guard`

---

### Шаг 6.15 — `PublishProvider` интерфейс + `AyrshareProvider` (фаза 1)

- **Цель / DoD:** Интерфейс `PublishProvider` (`publish(target, media, caption, labels): Promise<PublishResult>`) и первая реализация `AyrshareProvider` (doc 04 §5.3): per-user Profile-Key, один `/post` с `platforms:["youtube","tiktok","instagram"]`, токены/refresh держит Ayrshare. Анти-блок transforms (6.11–6.13) применяются ДО provider-вызова. `is_aigc`/AI-labels проброшены.
- **Репозитории/команды:** `vendor/ayrshare-node` — референс контракта; своя обёртка через `undici`.
- **Тесты СНАЧАЛА** (`src/publish/providers/ayrshare/ayrshare.test.ts`, MSW мокает `app.ayrshare.com/api/post`):
  - `test('publish posts with Profile-Key header and selected platforms')` — ассерт исходящего запроса.
  - `test('anti-block transforms run before provider call (transcode+caption+watermark invoked)')` — спаи на transform-слой, порядок.
  - `test('rejects publish if media still contains a third-party watermark (gate)')` — guard перед отправкой.
  - `test('rejects publish if caption fails no-FlipHouse-branding guard')`.
  - `test('passes is_aigc/AI-label flags into the post payload')`.
  - `test('maps Ayrshare per-platform response into per-target PublishResult (partial success)')`.
  - `test('Ayrshare error for one platform marks only that target failed, others published')`.
- **Реализация:** `src/publish/providers/publishProvider.ts` (интерфейс + типы), `src/publish/providers/ayrshare/ayrshareProvider.ts`; декоратор `withAntiBlock(provider)` оборачивает любой provider анти-блок-гейтами (DRY для direct-провайдеров позже).
- **✅ Готово когда:** тесты зелёные; анти-блок гейты блокируют watermark/branding ДО отправки; частичный успех маппится per-target.
- **Commit:** `feat: PublishProvider interface + AyrshareProvider behind anti-block gate`

---

### Шаг 6.16 — Publish-абстракция: `publishClip` + human preview+approval + PublishTarget state-machine

- **Цель / DoD:** `publishClip({ clipId, connectionIds, captionsByPlatform, approvalToken })` (doc 04 §5.4): **обязательное human preview+approval ДО любого post-вызова** (никогда silent auto-post). Создаёт `PublishJob` + `PublishTarget` per-connection; диспатчит через `PublishProvider`; per-target результат → частичный отказ first-class; poll статуса до `FINISHED`/`published` перед «опубликовано». UI preview/approve (server actions + страница).
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`src/publish/publishClip.test.ts` + `tests/publish/approval.e2e.ts` Playwright):
  - `test('publishClip throws ApprovalRequiredError when approvalToken missing/invalid')` — нельзя постить без явного одобрения.
  - `test('creates one PublishTarget per connection with status pending')`.
  - `test('partial failure: one target failed, others published — job status = partial')`.
  - `test('polls platform status until FINISHED before marking target published')`.
  - `test('all caption/hashtag/privacy fields are editable — none preset/locked')` — payload отражает пользовательские правки (требование аудита TikTok/doc 04 §4.3).
  - `test('recipient account (handle/nickname) shown before approval')`.
  - E2E `playwright: 'preview shows clip + editable caption + per-platform toggle, Publish disabled until Approve checked'`.
- **Реализация:** `src/publish/publishClip.ts` (state-machine `pending→uploading→published|failed`, approval-token verify), `app/publish/[clipId]/page.tsx` (preview+approve UI: видео-плеер, редактируемые поля, чекбокс одобрения, выбор коннектов с показом handle), `app/publish/actions.ts` server actions.
- **✅ Готово когда:** unit+e2e зелёные; публикация невозможна без approval; поля редактируемы; частичный отказ корректен; статус поллится до финала.
- **🛑 ЧЕКПОИНТ D:** `PublishProvider`+Ayrshare end-to-end на staging (реальная тест-публикация `SELF_ONLY`/draft) — фаундер ревьюит human-preview+approval UX и частичные отказы. Утверждает публикационный UX и Ayrshare-vs-direct таймлайн.
- **Commit:** `feat: publishClip orchestration with mandatory human preview+approval`

---

### Шаг 6.17 — PWA: динамический манифест + иконки + инсталлируемость

- **Цель / DoD:** `app/manifest.ts` (doc 04 §1.6, точные поля: `standalone`/`portrait`/`theme #0a0a12`/maskable-иконка) + иконки 192/512/maskable. Инсталлируемость проходит Playwright/Lighthouse manifest-чек.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`tests/pwa/manifest.test.ts` Vitest + `tests/pwa/installable.e2e.ts` Playwright):
  - `test('manifest has standalone display, portrait orientation, FlipHouse name')`.
  - `test('manifest includes 192, 512 and a maskable 512 icon')`.
  - `test('theme_color and background_color match --color-bg #0a0a12')`.
  - `test('start_url and id are set (installability requirement)')`.
  - E2E `playwright: 'manifest is linked and parseable, all icon URLs return 200'`.
- **Реализация:** `app/manifest.ts` (MetadataRoute.Manifest), `public/icon-192x192.png`, `icon-512x512.png`, `icon-maskable-512.png`, `badge.png`.
- **✅ Готово когда:** тесты зелёные; иконки отдаются 200; манифест валиден.
- **Commit:** `feat: PWA dynamic manifest + maskable icons (installable)`

---

### Шаг 6.18 — PWA: Serwist service worker (precache + offline shell + Webpack-сборка)

- **Цель / DoD:** `app/sw.ts` (doc 04 §1.5) — Serwist precache + runtime cache + offline fallback `/~offline`; `next.config.ts` через `withSerwistInit` (doc 04 §1.4) с `/sw.js` no-cache заголовками + security-заголовками. **Прод-сборка на Webpack** (Serwist требует Webpack — doc 04 §1.2); проверка `public/sw.js` в образе.
- **Репозитории/команды:** `pnpm add @serwist/next` `pnpm add -D serwist`.
- **Тесты СНАЧАЛА** (`tests/pwa/sw-build.test.ts` + `tests/pwa/offline.e2e.ts`):
  - `test('production build emits public/sw.js (Webpack path, not Turbopack)')` — после `next build` файл существует и непустой.
  - `test('/sw.js is served with no-cache, no-store headers')` — ассерт заголовков.
  - `test('security headers present: X-Content-Type-Options nosniff, X-Frame-Options DENY')`.
  - E2E `playwright: 'navigating offline serves the /~offline shell, not a browser error'`.
- **Реализация:** `app/sw.ts` (Serwist + `defaultCache` + fallbacks), `app/~offline/page.tsx`, `next.config.ts` (withSerwistInit + headers, doc 04 §1.4), `tsconfig.json` types/lib/exclude правки, `.gitignore` `public/sw*`.
- **✅ Готово когда:** `next build` эмитит `public/sw.js`; `/sw.js` no-cache; offline-shell отдаётся; e2e зелёный.
- **Commit:** `feat: Serwist service worker, offline shell, Webpack prod build`

---

### Шаг 6.19 — Web-push: VAPID + DB-backed подписки + server actions + 404/410-прунинг

- **Цель / DoD:** `lib/push/subscriptions.ts` (репозиторий в Postgres, upsert по endpoint — doc 04 §1.7, НЕ в памяти) + `lib/push/send.ts` (`webpush.sendNotification` обёртка с **обязательным удалением подписки на 404/410** — главная операционная деталь doc 04 §1.7) + server actions `subscribeUser`/`unsubscribeUser` + push-листенеры в `sw.ts` (`push`/`notificationclick`, deep-link к `/clips/{jobId}`).
- **Репозитории/команды:** `pnpm add web-push`; `pnpm dlx web-push generate-vapid-keys`.
- **Тесты СНАЧАЛА** (`lib/push/subscriptions.test.ts`, `lib/push/send.test.ts`, web-push мокнут):
  - `test('saveSubscription upserts by endpoint (no duplicate rows for same endpoint)')`.
  - `test('subscriptions persist in DB, survive a simulated process restart')` — не модульная переменная.
  - `test('notifyClipsReady sends to all of a users subscriptions')`.
  - `test('410 Gone response prunes the expired subscription row')` — критичный кейс.
  - `test('404 Not Found response prunes the expired subscription row')`.
  - `test('non-404/410 error does NOT prune (transient failure kept)')`.
  - `test('payload deep-links to /clips/{jobId} and tags by jobId (dedupe)')`.
- **Реализация:** `lib/push/subscriptions.ts` (Prisma `PushSubscription` репозиторий), `lib/push/send.ts` (`notifyClipsReady`, prune-на-404/410 через `Promise.allSettled`), `app/(push)/actions.ts` (server actions + `webpush.setVapidDetails`), push/notificationclick листенеры дополняют `app/sw.ts`.
- **✅ Готово когда:** тесты зелёные; подписки в БД (не в памяти); 404/410 чистят строки; transient — нет; deep-link/tag корректны.
- **Commit:** `feat: DB-backed web-push with mandatory 404/410 subscription prune`

---

### Шаг 6.20 — Gated push opt-in UI + вызов `notifyClipsReady` из вебхука рендера

- **Цель / DoD:** `PushOptIn` (doc 04 §1.7 — **gated, не на загрузке**; запрос после осмысленного действия, напр. после старта первого рендера; на iOS — за A2HS, детект `display-mode: standalone`) + `InstallPrompt` (iOS Share→«На экран Домой», т.к. нет `beforeinstallprompt`). **Реальный триггер push — обработчик вебхука рендер-задачи** (doc 04 §1.7, не кнопка): когда webhook-receiver рендера (P1, doc 01 §3) получает «клипы готовы» → `notifyClipsReady(userId, jobId)`.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`tests/pwa/optin.e2e.ts` Playwright + `tests/push/webhook-trigger.integration.test.ts`):
  - E2E `playwright: 'Notification.requestPermission is NOT called on page load'` — спай на старте 0 вызовов.
  - E2E `playwright: 'opt-in prompt appears only after first render is started'`.
  - E2E `playwright: 'on non-standalone iOS UA, install instructions shown before push opt-in'`.
  - `test('render webhook handler fires notifyClipsReady with userId+jobId on completion')` — мок webhook payload → push отправлен.
  - `test('webhook handler is idempotent: duplicate completion callback sends push once')` — дедуп (вендоры ретраят, doc 01 §3).
- **Реализация:** `app/components/pwa/PushOptIn.tsx` (gated, по тапу, standalone-детект), `app/components/pwa/InstallPrompt.tsx` (iOS-инструкция), хук в webhook-receiver рендера: на `render.completed` → `notifyClipsReady` (идемпотентно по jobId).
- **✅ Готово когда:** e2e+integration зелёные; нет авто-запроса разрешения; push летит из вебхука, не из кнопки; идемпотентен.
- **🛑 ЧЕКПОИНТ E:** PWA + web-push из вебхука рендера на staging-устройстве — фаундер устанавливает PWA на свой телефон и проверяет реальный push «🎬 Твои нарезки готовы» с deep-link. Проверяет инсталлируемость и gated opt-in.
- **Commit:** `feat: gated push opt-in + render-webhook-fired clips-ready notification`

---

### Шаг 6.21 — Refresh-воркер (cron): per-platform стратегии за одним сканом

- **Цель / DoD:** Cron-воркер (doc 04 §5.7) сканирует `@@index([status, accessTokenExpiresAt])`, диспатчит per-platform refresh ДО истечения: TikTok — сохранить ротированный refresh + nudge на 365д; IG — refresh на день ~30–50 (до 60-дн стены); YouTube — OAuth2-grant, нет refresh → `REAUTH_REQUIRED`; AGGREGATOR-строки пропускает (refresh upstream у Ayrshare).
- **Репозитории/команды:** BullMQ repeatable job (из P1) или Railway cron.
- **Тесты СНАЧАЛА** (`src/connections/refresh/worker.test.ts`):
  - `test('worker selects only connections nearing expiry (index-driven query)')`.
  - `test('AGGREGATOR connections are skipped (Ayrshare owns refresh)')`.
  - `test('TikTok refresh near 365-day mark flags reconnect nudge')`.
  - `test('Instagram refresh runs in 30-50 day window, well before 60-day wall')`.
  - `test('YouTube without refresh_token is marked REAUTH_REQUIRED, not retried forever')`.
  - `test('a single connection failure does not abort the whole batch')`.
- **Реализация:** `src/connections/refresh/worker.ts` (батч-скан, per-platform диспатч через стратегии 6.6–6.8, изоляция ошибок per-connection), регистрация repeatable job.
- **✅ Готово когда:** тесты зелёные; AGGREGATOR пропускается; окна refresh корректны; батч устойчив к одиночным сбоям; coverage ≥95%.
- **Commit:** `feat: cron refresh worker with per-platform strategies + reauth nudges`

---

### Шаг 6.22 — Direct YouTube provider (resumable videos.insert) за `PublishProvider`

- **Цель / DoD:** `YouTubeDirectProvider` (doc 04 §3.2) — реализация ТОГО ЖЕ `PublishProvider`: owner-OAuth токены из vault через `getValidAccessToken`; **resumable `videos.insert`** (chunked, эталон `vendor/youtube-api-samples/python/upload_video.py`); `part=snippet,status` с обязательными `selfDeclaredMadeForKids` + `containsSyntheticMedia=true`; форс 9:16 ≤180с (Shorts-классификация); различать `uploadLimitExceeded` vs `quotaExceeded`. Под тем же `withAntiBlock`-декоратором.
- **Репозитории/команды:** `pnpm add googleapis`; `vendor/youtube-api-samples`.
- **Тесты СНАЧАЛА** (`src/publish/providers/youtube/youtubeDirect.test.ts`, MSW мокает upload-эндпоинт):
  - `test('uses resumable upload (initiates session, sends chunks)')` — ассерт resumable-протокол.
  - `test('sets selfDeclaredMadeForKids explicitly (COPPA)')`.
  - `test('sets containsSyntheticMedia=true for AI clips')` — анти-блок AIGC-контракт.
  - `test('forces 9:16 <=180s before upload (Shorts classification)')`.
  - `test('uploadLimitExceeded mapped to channel-daily-cap error, distinct from quotaExceeded')`.
  - `test('anti-block transforms applied: no watermark, fresh metadata, before insert')`.
  - `test('partial failure surfaces as failed PublishTarget with errorCode')`.
- **Реализация:** `src/publish/providers/youtube/youtubeDirect.ts` (googleapis OAuth2 + resumable insert, порт chunk-логики), маппинг ошибок. Тот же интерфейс/декоратор, что Ayrshare.
- **✅ Готово когда:** тесты зелёные; resumable; AIGC+made-for-kids выставлены; ошибки квоты различимы; анти-блок применён.
- **Commit:** `feat: YouTubeDirect provider (resumable videos.insert, synthetic-media label)`

---

### Шаг 6.23 — Direct TikTok + Instagram providers за `PublishProvider`

- **Цель / DoD:** `TikTokDirectProvider` (doc 04 §4.1: `/v2/post/publish/video/init/`, `PULL_FROM_URL` с верифиц. домена / `FILE_UPLOAD` chunked, обязательный `creator_info/query` pre-post, `is_aigc=true`, статус-поллинг, audit-гейт `SELF_ONLY` до аудита) и `InstagramDirectProvider` (doc 04 §4.2: 3-шаг `media`→poll `status_code` FINISHED→`media_publish`, `video_url` публичный, контейнер истекает 24ч, AI-label). Оба под `withAntiBlock`.
- **Репозитории/команды:** REST через `undici`; эталоны — TikTok/IG docs.
- **Тесты СНАЧАЛА** (`src/publish/providers/tiktok/tiktokDirect.test.ts`, `instagram/instagramDirect.test.ts`, MSW):
  - TikTok `test('queries creator_info before init (mandatory pre-post)')`.
  - TikTok `test('sets is_aigc=true and PULL_FROM_URL from verified domain')`.
  - TikTok `test('before audit, forces SELF_ONLY privacy (audit gate)')`.
  - TikTok `test('polls publish/status/fetch until success before marking published')`.
  - TikTok `test('403 reached_active_user_cap surfaces as retryable target error')`.
  - IG `test('container flow: create media -> poll status_code FINISHED -> media_publish')`.
  - IG `test('aborts if container would exceed 24h expiry before publish')`.
  - IG `test('sets AI label and uses a public video_url')`.
  - Both `test('anti-block transforms (per-platform transcode, fresh caption) applied before publish')`.
- **Реализация:** `src/publish/providers/tiktok/tiktokDirect.ts`, `src/publish/providers/instagram/instagramDirect.ts` — оба реализуют `PublishProvider`, оба обёрнуты `withAntiBlock`; провайдер-реестр выбирает Ayrshare-vs-direct per-platform по конфигу/флагу.
- **✅ Готово когда:** все тесты зелёные; creator_info pre-post enforced; audit-гейт SELF_ONLY; IG container-flow + expiry; AIGC-лейблы; анти-блок применён обоими.
- **🛑 ЧЕКПОИНТ F:** Direct-провайдеры (YouTube/TikTok/IG) за тем же интерфейсом + аудит-гейтинг — фаундер ревьюит готовность к подаче на official platform review (TikTok audit, Meta App Review на `instagram_business_content_publish`, YouTube API compliance audit). Решает, запускать ли app review.
- **Commit:** `feat: TikTokDirect + InstagramDirect providers (audit-gated, AIGC-labeled)`

---

### Шаг 6.24 — Сквозной анти-блок интеграционный тест + coverage-гейт фазы

- **Цель / DoD:** Один интеграционный сценарий «клип → опубликован в 3 платформы» ассертит ВЕСЬ анти-блок чеклист doc 04 §4.3 разом, через любой provider (Ayrshare и direct прогоняются параметризованно). Финальный coverage-гейт фазы держится. Никакого нового продакшн-кода, кроме склейки.
- **Репозитории/команды:** —
- **Тесты СНАЧАЛА** (`tests/publish/antiblock-e2e.integration.test.ts`, параметризовано по provider):
  - `test('[%s provider] published media carries no third-party watermark')`.
  - `test('[%s provider] published media carries no FlipHouse branding')`.
  - `test('[%s provider] each platform gets a DIFFERENT file (distinct hash) and DIFFERENT caption')`.
  - `test('[%s provider] FTC disclosure survives the whole pipeline')`.
  - `test('[%s provider] AIGC labels set per platform (is_aigc / synthetic / ai_label)')`.
  - `test('[%s provider] no post without human approval token')`.
  - `test('[%s provider] cadence is jittered (no round-number burst)')`.
  - `test('partial failure on one platform leaves others published (first-class partial)')`.
- **Реализация:** только тестовый сценарий + фикстуры; при пробелах — точечный фикс, не новый модуль.
- **✅ Готово когда:** интеграционный набор зелёный для ОБОИХ provider-режимов; глобальный coverage ≥80%, доменные модули ≥95%; CI coverage-гейт зелёный.
- **Commit:** `test: end-to-end anti-block compliance across Ayrshare + direct providers`

---

## Выход фазы (Phase exit criteria)

Фаза P6 закрыта, когда ВСЁ ниже верно и подтверждено зелёными тестами:

- [ ] **Identity ≠ Connections**: логин (Auth.js) и публикационные коннекты физически разделены; токены коннектов НЕ в `accounts` Auth.js.
- [ ] **AES-256-GCM token vault**: токены шифруются (envelope + `encKeyVersion`); в БД нет ни одного plaintext-токена (проверено сырым селектом); tamper детектится auth-tag'ом; coverage ≥95%.
- [ ] **`getValidAccessToken`** скрывает три несовместимые refresh-модели; ротированный TikTok refresh сохраняется; YouTube-без-refresh → `REAUTH_REQUIRED`; IG sliding-window соблюдён; single-flight против двойного refresh; ошибки никогда не глотаются молча.
- [ ] **Connect-флоу** для YT/TikTok/IG с CSRF-`state` + PKCE; запрашиваются ТОЛЬКО publish-scopes (login-scopes никогда); мульти-аккаунт (N коннектов/платформа) работает.
- [ ] **АНТИ-БЛОК (doc 04 §4.3) enforced и протестирован на выходе**: сторонние watermark срезаны (ассерт по пикселям); брендинг FlipHouse заблокирован; per-platform транскод даёт разные хэши + нативные спеки (moov-front для IG); свежие per-platform captions (разные первые 3 слова, никогда байт-идентичны); AIGC-лейблы выставлены; FTC-disclosure сохраняется сквозь пайплайн; jitter-кадэнс без round-burst; pre-flight лимит-чеки + 6/min rate-guard.
- [ ] **Human preview+approval обязателен**: ни одна публикация невозможна без явного approval-token; поля caption/hashtag/privacy/interaction редактируемы (не preset/locked); handle получателя показан.
- [ ] **`PublishProvider`-абстракция**: `AyrshareProvider` (фаза 1) И `YouTubeDirect`/`TikTokDirect`/`InstagramDirect` реализуют один интерфейс под общим `withAntiBlock`-гейтом; частичный отказ — first-class (`PublishTarget` per-target).
- [ ] **Direct-провайдеры**: YouTube resumable `videos.insert` (`selfDeclaredMadeForKids` + `containsSyntheticMedia`); TikTok `creator_info` pre-post + audit-гейт `SELF_ONLY` + статус-поллинг; IG container-flow (FINISHED→publish) + 24ч-expiry-гард.
- [ ] **PWA**: динамический манифест + maskable-иконки (инсталлируемо); Serwist SW (precache + `/~offline` shell) собирается Webpack-путём (`public/sw.js` в образе); `/sw.js` no-cache + security-заголовки.
- [ ] **Web-push**: подписки в Postgres (не в памяти, переживают рестарт); `notifyClipsReady` летит из обработчика **вебхука рендера** (не из кнопки), идемпотентно по jobId; 404/410 чистят просроченные подписки, transient — нет; deep-link `/clips/{jobId}` + dedupe-tag.
- [ ] **Gated opt-in**: `Notification.requestPermission` НИКОГДА не на загрузке; на iOS — install-инструкция (Share→A2HS) перед push, детект standalone.
- [ ] **Refresh-воркер** (cron) обновляет токены до истечения per-platform; AGGREGATOR пропускается; устойчив к одиночным сбоям.
- [ ] **Coverage-гейт CI зелёный**: глобально ≥80%; `src/connections/vault/**`, `src/publish/antiblock/**`, `src/connections/refresh/**` ≥95%.
- [ ] Все 6 чекпоинтов (A–F) пройдены и подписаны фаундером.
- [ ] **Только официальные API** — ни одного неофициального/реверс-инженеренного эндпоинта (явное правило doc 04 §4: единственный shippable путь).
```
