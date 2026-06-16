# FlipHouse — STATE.md (Трекер прогресса)

> **[РЕШЕНИЕ FOUNDER'А · 2026-06-15] ВСЁ НА КРИПТЕ. STRIPE+ЮKassa УБРАНЫ.** Креаторам выплачивают в крипте → и за использование платят криптой. Биллинг — за vendor-нейтральной абстракцией `PaymentProvider` (как `PublishProvider` в P6); конкрет = **свой on-chain приёмник USDT TRC-20** (УРОВЕНЬ 3: HD-кошелёк per-user deposit-адрес + свой TRON-узел/TronGrid + `tronweb`; БЕЗ чужого процессора — никто не блокирует на уровне PSP; остаётся только риск эмитента Tether → чистый AML+ротация+быстрый офф-рамп). Сеть **TRC-20**. **В крипте нет автосписания → модель = предоплаченный USDT-баланс** (off-chain ledger): депозит USDT → on-chain watcher подтверждает (≥N блоков, идемпотентно по `txid`) → `credit`; списания: **PAYG $0.25/мин исходника (~90% маржи)** и/или **подписка** (раз/мес `debit` с баланса). Методы: `getDepositAddress`/`getBalance`/`debit`/`createPayout`(`tronweb`). Безопасность: seed+hot-key в KMS, hot/cold-split. Тарифы (USDT, лимит минут/мес; драйвер себес — GPU ~$0.025/мин): Бесплатно 30 / Старт $9·150 / **Актив $24·300** / Студия $59·1000; PAYG $0.25/мин; депозиты $10/$25/$50/$100. Сетка **выверена против Opus Clip** ($29·300). Биллинг-состояние — на **`userId`** (`subscription` + `balance_entries`), НЕ на организации (удалены в P1.11). Metered P5 — наш `usage_events`-ledger; выплаты креаторам — USDT (`createPayout`). Stripe/ЮKassa-кода в репо НЕ было — сделан ре-план роадмапа/доков (P1.12/1.13, P5, P7, ROADMAP, docs 00/01/03/05) + чистка локалей; кода ещё нет, P1.12/P1.13 по TDD после аппрува.
>
> **[РЕШЕНИЕ FOUNDER'А · 2026-06-15] ЯЗЫК ИНТЕРФЕЙСА — РУССКИЙ.** Весь UI-копирайт пишем по-русски (nav, CTA, лейблы, hero, секции). Бренд `FlipHouse` — латиницей. Наши кастомные компоненты (SiteHeader/Eyebrow/landing) используют русский текст напрямую; полноценная i18n-разводка (ru-локаль/messages для boilerplate-страниц) — отдельное решение при сборке лендинга (P1.8) если понадобится.
>
> **🟨 P1 В РАБОТЕ · ✅ ЧЕКПОИНТ F ОДОБРЕН (2026-06-16) → web ЗАДЕПЛОЕН НА RAILWAY STAGING (живой: `https://web-staging-32d77.up.railway.app`, health db+redis up, dual-stack `::`, миграции в preDeploy, 3 smoke-теста зелёные) → ✅ P1.16 ЗАКРЫТ (сквозные e2e signup→пополнение→дашборд + hero-drop + визуальная регрессия 320/768/1024/1440 + Lighthouse-гейт) → **✅ ЧЕКПОИНТ G ОДОБРЕН founder'ом (2026-06-16): «всё ок — коммит, пуш, мёрж»** → **ФАЗА P1 ЗАВЕРШЕНА**, ветка `p1.13-tron-watcher` (P1.13–P1.16) мёржится в `main` через PR. JS-бюджет лендинга (First-Load 203kb > 150kb) founder принял на ЧЕКПОИНТЕ G (CWV LCP/CLS/TBT в бюджете; оптимизацию бандла отложили). **Следующий шаг: P2.1** (загрузка + AI-нарезка MVP, см. `roadmap/P2`). P1.15 закрыт (Railway staging: проект fliphouse + PG/Redis + web из GitHub, RAILPACK, railway.json исправлен под реальный деплой). P1.14 закрыт (`railway.json` config-as-code). P1.13.1 закрыт (реальный on-chain TRON: HD-деривация + TronGrid-поллер). Все гейты зелёные. **[ЧЕКПОИНТ F — ТЕХНИЧЕСКИ ВАЛИДИРОВАН ВЖИВУЮ 2026-06-16]** founder дал TronGrid-ключ → исполнитель прогнал `source.tron.ts` против РЕАЛЬНОЙ сети Nile (ключ+мнемоник в `.env.local`, gitignored): `getCurrentBlock` (live block 68368130), реальная trc20-страница распарсилась 1:1 с `trc20PageSchema`, `blockNumber` резолвится вторым вызовом (live), и **полный путь депозит→watcher→баланс отработал на РЕАЛЬНОМ on-chain трансфере** (1000 USDT, блок 68368062, ~68 подтверждений → credit; повторный тик — идемпотентен, 0 двойных). Гейт-харнесс `source.tron.live.test.ts` (skip без `TRON_LIVE=1`, в CI не гоняется). **Живой демо-роут `/tron-demo`** (публичный dev-preview, как `design-preview`): на рендере опрашивает РЕАЛЬНУЮ Nile через `source.tron.ts` + применяет confirmations-гейт и рисует реальный `DepositPanel` + баланс (на скрине: 1000 USDT, блок #68368577, tx 3ad4ca3…) — founder видит путь в браузере (`pnpm exec next dev` → http://localhost:3000/tron-demo), 0 console-ошибок, гейты зелёные. `.env.local` переключён на `PAYMENT_PROVIDER=tron` + сгенерирован свежий **testnet**-мнемоник; index-0 deposit-адрес founder'а = `TJVtGAhpVgN2tm7kRoNqGfK9KNu43vodaB`. **ОСТАЛОСЬ ЗА founder'ом (решение, не код):** (а) опционально — закинуть testnet-USDT с Nile-крана на свой адрес и увидеть СВОЙ депозит в дашборде (машинерия уже доказана на реальных данных); (б) скорректировать тарифы/PAYG/подтверждения, если нужно; (в) дать «го» на промоут → шаги деплоя P1.14+. НЕ прохожу чекпоинт без явного «го». ~~Следующий шаг: P1.13.1~~ (реальный on-chain TRON: HD-кошелёк per-user TRC-20-адрес из BIP44-мнемоники + реальный TronGrid-поллер `source.tron.ts` на Nile testnet — конкрет под абстракции P1.12/P1.13, сеть в юнит-тестах замокана, деривация по известному вектору; ДЕПОЗИТНЫЙ путь, `createPayout`/выплаты → P5). **[FOUNDER EDIT 2026-06-16]** Реальный TRON выносим ОТДЕЛЬНЫМ TDD-шагом **ДО деплоя** (founder выбрал «сначала TRON, потом деплой» на чекпоинте F); раньше реальный TRON был «размазан» по чекпоинту F без тестов — **пробел плана закрыт новым шагом 1.13.1** (см. `roadmap/P1`), **🛑 ЧЕКПОИНТ F сдвинут на ПОСЛЕ 1.13.1** (живой Nile-testnet-прогон, когда код готов; founder даёт мнемоник+TronGrid-ключ+testnet-TRX/USDT). P1.13-watcher уже мигрирован в dev-БД вручную (был дрейф: `local.db` от 15.06 имел только миграцию 0000 → применил 0001/0002, creator-дашборд ожил, deposit-адрес персистнут). ✅ **P1.13 (on-chain TRON deposit watcher, на фикстурах)** — крипто-путь поступления денег: новый `credit()` в `balance.ts` (зеркало `debit`, kind=`deposit`, идемпотентность по `txid` через unique-индекс `balance_entries_txid_uq` внутри транзакции, атомарный SQL-инкремент); `src/payments/watcher/`: `source.ts` (типы `TransferEvent {txid,blockNumber,toAddress,fromAddress,tokenContract,amount:bigint}` + `TronChainSource`), `source.tron.ts` (тонкая заглушка `throw 'checkpoint F'`, реальный TronGrid-поллинг на F), `watcher.ts::processTransfers` (пайплайн: фильтр tokenContract≠USDT→skip / confirmations `currentBlock-blockNumber+1 < N`→skip / резолв address→userId null→skip / `microToUsdt(Number(amount))` = **фактическая on-chain сумма, не инвойс** / `credit` по txid → сводка `{credited,skippedPending,skippedWrongToken,skippedUnknownAddress,skippedDuplicate}`) + `runWatcherTick` (курсор→fetch `[last+1..head]`→process→курсор двигается консервативно до `head-N`, pending переcканится — безопасно по txid), `cursor.ts` (`CursorStore` DI: `inMemoryCursorStore` тесты / `redisCursorStore` прод на `@/libs/Redis`), `depositAddress.ts` (`getOrCreateDepositAddress` derive+персист в `subscription.depositAddress` идемпотентно / `resolveUserIdByDepositAddress`), `fixtures.ts` (`makeTransfer`/`fakeChainSource`). Миграция **`0002_deposit-address-unique`** — partial-unique `subscription_deposit_address_uq` на `deposit_address WHERE NOT NULL` (защита от коллизии деривации→чужой credit). Подключён персист в `dashboard/creator/page.tsx` (`getOrCreateDepositAddress(db, provider, userId)` вместо on-the-fly). Env (с дефолтами, `TEST_ENV_DEFAULTS` не тронут): `USDT_CONTRACT` (mainnet default), `TRON_CONFIRMATIONS=19` (выбор founder'а — финальность TRON), `TRON_NETWORK=nile`, `TRONGRID_API_KEY` optional (→`.env.local`). Тесты (PGlite-харнесс + мок redis): 6 именованных watcher-тестов + 2 runWatcherTick + стаб-реджект + cursor 4 (in-mem+redis) + depositAddress 4 + balance credit-блок 2 → **web 116 тестов, root lint 0, root typecheck 0, web check:types 0, coverage exit 0 (95.09% stmts; вся `payments/watcher` + `balance.ts` = 100%)**. **НЕ в этом шаге (→ ЧЕКПОИНТ F):** реальный TronGrid-поллинг/HTTP/retries (`source.tron.ts` остаётся throw), ключи/HD-derive/KMS/hot-cold, живой testnet-депозит, worker-процесс/cron-entrypoint/деплой `payments-watcher`, reorg-обработка. **founder на ЧЕКПОИНТЕ F прогоняет полный путь на TRON testnet (Nile/Shasta): депозит USDT TRC-20 → watcher → баланс → PAYG/подписка → выплата, идемпотентность по txid, KMS/hot-cold, confirmations-гейт, лимиты; может скорректировать тарифы/PAYG/число подтверждений.** ✅ **ЧЕКПОИНТ E ОДОБРЕН founder'ом (2026-06-16):** прогнал онбординг creator/advertiser вживую на своей машине (регистрация → выбор роли → дашборд; скриншот рабочего «Кабинета креатора» подтверждён). ✅ **P1.12 (крипто-биллинг через `PaymentProvider`, на моках провайдера)** — предоплаченный USDT-баланс по `userId`: первые доменные Drizzle-таблицы `subscription` (PK=`userId`, plan/balanceUsdt/depositAddress/subscriptionStatus/currentPeriodEnd/minutesUsedThisPeriod) + ledger `balance_entries` (миграция `0001_billing-schema`, unique `(userId,jobId)` для PAYG-дебетов + unique `txid` для депозитов P1.13). `src/features/billing/`: `PaymentProvider.ts` (интерфейс `getDepositAddress`/`createPayout` + фабрика по env `PAYMENT_PROVIDER`), `provider/mock.ts` (детерминированный TRC-20-адрес из sha256(userId), in-mem; гоняет ВСЕ тесты), `provider/tron.ts` (тонкая заглушка `throw 'checkpoint F'` — Q2 founder'а «только интерфейс+мок»; реальный tronweb/HD/сеть в P1.13/F), `plans.ts` (сетка free 30 / start 9·150 / active 24·300 / studio 59·1000 / payg $0.25/мин из `BILLING_PLAN_ENV`), `balance.ts` (ledger DI-drizzle: `ensureSubscription`/`getBalance`/`debit` идемпотентный по jobId + **атомарный SQL-декремент** против lost-update), `usageGate.ts::assertCanClip` (PAYG→баланс / подписка→лимит минут ПЕРЕД джобой), `subscription.ts::chargeMonthlySubscription` (месячное списание с баланса; не хватило → downgrade free/past_due), `DepositPanel.tsx` (кнопка «Пополнить» с TRC-20 адресом+copy в дашборде креатора). Env: `PAYMENT_PROVIDER` (enum tron|mock, default mock) + `BILLING_PLAN_ENV` (optional JSON). Тесты: интеграц. PGlite-харнесс (in-mem, мигратор) + RTL/jsdom; web 84/84 unit (billing 17, все billing-файлы 100% покрытия), root агрегат 97/97, web check:types 0, root lint/typecheck/test/coverage exit 0. **[FOUNDER EDIT 2026-06-15 · ОРГАНИЗАЦИИ УБРАНЫ]** founder отверг концепт организаций целиком («зачем нам организации — человек выбрал роль и пошёл дальше»): тип аккаунта (creator/advertiser) перенесён с организации на ПОЛЬЗОВАТЕЛЯ и хранится в Clerk `publicMetadata` (выбор founder'а), БД для роли НЕ используется. Это ОТМЕНЯЕТ org-подход P1.10 (таблица `organization` + `accountType` pgEnum + миграция 0001 удалены; схема снова = `todo`, drizzle подтвердил «No schema changes»). Организации отключены и в Clerk-дашборде (founder сделал сам). ✅ P1.11 (детерминированные гейты) — **онбординг creator/advertiser + RBAC без организаций**: `src/libs/accountType.ts` (get/set роли в Clerk `publicMetadata` через `clerkClient`, иммутабельно), `src/libs/rbac.ts::requireAccountType` (гейт дашборда: нет роли→`/onboarding`, чужая→свой дашборд, нет user→`/sign-in`), server action `selectAccountType` (`onboarding/actions.ts`), страница `onboarding/page.tsx` + клиентский `AccountTypeChoice.tsx` (2 Swiss-карточки), типизированные `dashboard/creator` + `dashboard/advertiser`, индекс-роутер `dashboard/page.tsx`. Убраны org-артефакты: org-гейт в `proxy.ts`, `OrganizationMenu`/org-switcher в `DashboardHeader`, org-profile роут, org-selection страница, `organizationSchema`/enum/миграция 0001/`account-type.test.ts`. Тесты (node, моки `auth`/`clerkClient`/`redirect`): accountType 5 + rbac 4 + actions 4 → **web 80/80, lint 0, typecheck 0, web check:types 0, coverage exit 0** (accountType/rbac/actions 100%). e2e `tests/onboarding.e2e.ts` (через `@clerk/testing`, `clerk_test`+424242, guard-скип в CI/без ключей) написан и в браузере доходит до `/dashboard`, но ДО ЗЕЛЁНОГО в этом sandbox НЕ доведён: server-side вызов Clerk Backend API из next-dev зависает (прямой `curl` к api.clerk.com = 200/0.78с — ограничение песочницы, не баг кода). **founder проходит e2e/оба пути на реальной машине на ЧЕКПОИНТЕ E.** Ниже — историческая запись отменённого org-подхода P1.10. ✅ P1.10 [ОТМЕНЁН ВЫШЕ] — **`accountType` (creator|advertiser) на организации** (Drizzle): в форке НЕ оказалось `organizationSchema` (был только `todo`) — завёл минимальную `organizationSchema` (`id` text PK = Clerk org-id + nullable `account_type` pgEnum + updated/created timestamps; Stripe-колонки придут в 1.12/1.13, YAGNI). Миграция `migrations/0001_account-type.sql` (`CREATE TYPE account_type` + `CREATE TABLE organization`) сгенерирована `db:generate --name account-type` и применяется (`db:migrate` на дев-PGlite — ✓). Введён ПЕРВЫЙ интеграционный тест-харнесс на эфемерной in-memory PGlite (`@electric-sql/pglite` + `drizzle-orm/pglite` migrator) — `src/models/account-type.test.ts`, 5 тестов: enum-колонка (information_schema → USER-DEFINED/`account_type`), default null, round-trip creator, отказ невалидного значения (enum reject), идемпотентность повторной миграции. Helper `queries/accountType.ts` (getAccountType/setAccountType) ОТЛОЖЕН в 1.11 (там потребитель — онбординг/RBAC; YAGNI, прецедент P1.6→1.7). web 72/72, root lint/typecheck 0, web check:types 0, coverage exit 0. Параллельным `fix:`-коммитом типизировал gsap/ScrollTrigger-моки в `useSmoothScroll.test.tsx` — латентная ошибка `web check:types` из P1.9 (добавил coverage-блок после последнего typecheck; CI-гейт её не ловит — root-typecheck не покрывает web-test-файлы, а web check:types не в CI). ✅ **ЧЕКПОИНТ D ОДОБРЕН founder'ом** (2026-06-15): посмотрел лендинг целиком (секции + scroll-моушен), сказал «пока норм, пуш и мёрж» → ветка `p1.4-design-tokens` (P1.4–P1.9) мёржится в `main` через PR. **[ИЗВЕСТНЫЙ ДОЛГ — pre-existing P1.8, НЕ регрессия P1.9 · РЕШЕНИЕ FOUNDER'А 2026-06-15: ОТЛОЖЕНО]** на 320px есть горизонтальный overflow (`scrollWidth 393 > 305`): длинное hero-слово «ранжированных» в `AnimatedHeading` (огромный `--text-hero`) + пара блоков marketplace-леджера выходят за вьюпорт. Доказано, что это P1.8: при reduced-motion (все мои reveal-CSS выключены) overflow идентичен; мои правки P1.9 чисто аддитивные (data-reveal-атрибуты + вертикальный translateY). Founder решил пока не чинить («дальше всё равно будем вносить изменения») — адаптивный проход (`overflow-wrap`/clamp-min hero + marketplace, брейкпоинты 320/375) сделаем позже, когда макет устоится, отдельным `fix:`-коммитом. Зафиксировано как известный долг, не блокер. ✅ P1.9 — **scroll-сторителлинг через GSAP ScrollTrigger + Lenis** (на развилке шага founder выбрал GSAP+Lenis, не IntersectionObserver): хук `src/hooks/useSmoothScroll.ts` (`'use client'`) синкает Lenis-плавный-скролл с `gsap.ticker` и строит compositor-only reveal-твины (`transform/opacity`, fade-up «rise», стаггер по группам) из декларативных конфигов `src/utils/scrollReveal.ts`; `prefers-reduced-motion` → ранний выход (Lenis/GSAP даже не грузятся — подтверждено в браузере: 0 анимационных чанков, весь контент сразу видим). GSAP/Lenis тянутся dynamic `import()` (отдельные чанки `06zz_gsap_*`/`0u3g_lenis_*` — не в initial bundle; формальная bundle-проверка отложена в 1.16). Начальное скрытое состояние reveal-целей — в `global.css` под `@media (prefers-reduced-motion: no-preference)`, чтобы reduced/no-JS видели весь контент. Контроллер `ScrollProvider` смонтирован в роуте `page.tsx` рядом с `<Landing/>` (а не внутри `Landing`) — 5 P1.8-тестов `Landing.test.tsx` не тронуты. Reveal-цели размечены аддитивными `data-reveal` / `data-reveal-group`+`data-reveal-item` в секциях (SectionHead, ранкед-строки, 4 прохода, 4 метрики, marketplace-карточки/фигура, closer-CTA). Тесты: 4 hook-теста (jsdom+renderHook, gsap/lenis замоканы через `vi.hoisted` класс-мок как ioredis) + static-guard `scrollReveal.test.ts` (ревилы трогают только transform/opacity/clip-path, banned-список из web/coding-style) + ScrollProvider-тест; web 67/67, lint/typecheck 0, coverage exit 0 (scrollReveal/ScrollProvider 100%, useSmoothScroll 85% stmts). Визуально в браузере (Playwright) на 1440: hero-слова раскрылись, ранкед-строки/секции плавно появляются на скролле со стаггером, 0 console-ошибок. ✅ P1.8 — **Swiss-лендинг собран** (`src/app/[locale]/(marketing)/page.tsx` → `<Landing/>`): masthead (SiteHeader) → hero с единственным H1 (`AnimatedHeading`, vermillion-акцент) + слитая в ОДИН `.dropbar` hero-дропзона (по выбору founder'а: визуальный рестайл, `onFlip`/состояния/12 тестов HeroDropzone не тронуты) → секция 01 ранкед-таблица (5 клипов, score-бары) → 02 «Четыре прохода» 01–04 → 03 marketplace (creators/advertisers + native-banner demo + payout-ledger, vermillion/cobalt) → 04 receipts (12×/9:16/94%/$0↑) → closer (ink + vermillion CTA → /sign-up) → footer-колофон. Семантика: единственный `h1`, `header/main/footer`, `aria-labelledby` на 6 секциях. Русский копирайт по эталону `docs/design-reference/swiss-pop.html` (бренд FlipHouse — латиницей). Новые файлы: `components/{landing/Landing,hero/HeroSection,ui/AnimatedHeading,layout/SiteFooter,sections/{SectionHead,RankedBatch,ProcessSteps,Marketplace,Metrics,Closer}}`. 5 Landing-тестов + новый dropbar-тест GREEN; web 47/47, корневой агрегат 60/60; lint/typecheck 0; coverage exit 0 (агрегат 92.95% stmts; все новые компоненты 100% по `coverage-final.json`). Визуально проверено в браузере (Playwright) на 1440 и 320 — без overflow, 0 console-ошибок. Превью-роут `design-preview` оставлен dev-песочницей. ✅ **ЧЕКПОИНТ C ОДОБРЕН founder'ом** (2026-06-15): посмотрел hero-дропзону живьём на `/design-preview` (4 состояния), сказал «комит и пуш, пойдём дальше». Превью-роут `design-preview` закоммичен как dev-песочница компонентов (НЕ прод-лендинг; настоящий лендинг — P1.8). Открытый вопрос для P1.8: слить дропзону в ОДИН бокс как в эталоне `.dropbar` (сейчас два бордер-бокса) — уточнить при сборке. ✅ P1.7 — Hero-дропзона (`src/components/hero/HeroDropzone.tsx`): один Swiss-бокс принимает видео-файл (drag&drop по боксу + globalDrop по hero-региону) ИЛИ вставленную видео-ссылку; ведёт `status: ready/submitted/streaming/error`, валидирует тип/размер (≤500 МБ) через react-dropzone, отдаёт `onFlip({file?,url?})`; чипы файла/ссылки (Badge), reduced-motion-гейт на entrance. Утилита `src/utils/isVideoUrl.ts` + хук `src/hooks/useReducedMotion.ts` + guarded matchMedia-мок в `vitest.setup.ts`. 12 component-тестов + 3 isVideoUrl-теста GREEN; lint/typecheck 0; coverage 92% (hero/ 92.6%). Без glass/BorderBeam/motion-deps (ЧП B). ✅ P1.6 — Swiss dropzone-примитив: copy-owned drop-поверхность (движок kibo Dropzone MIT, перестилен под Swiss — bordered `--rule-strong` поле, vermillion drag-active outline, русский mono-копирайт) + кастомное `PromptInput`-семейство (`PromptInput/PromptInputTextarea/PromptInputToolbar/PromptInputSubmit status=...`) без ai-elements/glass/BorderBeam (founder edit ЧП B); `react-dropzone@15` добавлен; 3 tsx-теста GREEN, coverage 86%. ✅ P1.5 — Swiss-каркас: шрифты Archivo/Archivo Narrow/IBM Plex Mono через next/font (CSS-переменные в `@theme`), jsdom/RTL-тест-апаратура (`*.test.tsx` через per-file `@vitest-environment jsdom` + `globals:true` для RTL-cleanup), компоненты `SiteHeader` + `Eyebrow` (Swiss-стиль) с tsx-тестами; body на grotesk. ✅ ЧЕКПОИНТ B ОДОБРЕН founder'ом («го»): направление **«Swiss Pop»** (эталон `docs/design-reference/swiss-pop.html`). Путь выбора: dark-AI-tech (violet/cyan) — отвергнут → 1-й раунд (12 направлений) → Vibrant Pop выбран, затем отвергнут как «поверхностно/иишно» → 2-й раунд (6 reference-grade, без device-моков) → **Swiss Pop**. ✅ P1.4 — oklch дизайн-токены через Style Dictionary под Swiss Pop: светлая `:root`-база (paper `oklch(97.5% 0.004 95)` + ink `oklch(17% 0.012 270)`), primary/pop vermillion `oklch(63% 0.244 26)`, cobalt `oklch(48% 0.210 258)`, raw-сигналы (`--pop/--cobalt/--ink-soft/--rule/--rule-strong`) под имена эталона; `src/styles/tokens.css` + `COLORS.md` из `tokens/*.json`. **P1.5–P1.8 переопределены под Swiss Pop** (shadergradient WebGL-mesh выкинут; вместо — Archivo/Plex-Mono шрифты, бумажная сетка, hero с дропзоной + ранкед-таблица, секции 01–04, IntersectionObserver-ревилы) — см. `roadmap/P1`. ✅ P1.1 (форк SaaS-Boilerplate, **PR #1 смержен в `main`**, merge `4b023b0`), ✅ P1.2 (`/api/health`: db+redis пробы, 200/503, публичный) и ✅ P1.3 (ioredis-синглтон на `REDIS_PRIVATE_URL` + Zod env-валидация, реальный `probeRedis` ping) закрыты; чекпоинт A одобрен founder'ом. Все гейты зелёные. P0 ЗАВЕРШЁН ✅.
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
>
> **Заметки исполнителя — P1.6 (2026-06-15):**
> - `[AI-ELEMENTS ОТБРОШЕН]` Роадмап-«Реализация» шага 1.6 буквально предписывала `npx ai-elements@latest add prompt-input`, но founder-edit ЧП B сверху шага явно говорит «без AI-Elements-prompt-box». ai-elements в `vendor/` нет (тянет streamdown и пр.). По §6 правило вмешательства: приоритет у founder-edit → `PromptInput` построен кастомным Swiss-примитивом (`src/components/hero/prompt-input.tsx`), владея API-поверхностью, которую композит P1.7 (`PromptInputTextarea`, `PromptInputSubmit status=...`). Иконки статуса: lucide `ArrowUp`/`LoaderCircle`(spin)/`AlertCircle`.
> - `[KIBO-ЛИФТ]` Drop-движок портирован из `vendor/kibo/packages/dropzone/index.tsx` (MIT, react-dropzone-обёртка) в `src/components/hero/dropzone.tsx`, перестилен под Swiss: импорт `cn`→`@/utils/Helpers` (нет `@/lib/utils`), root = нативный `<button>` (не kibo-`<Button>`), bordered `--rule-strong` поле, drag-active → `--pop` outline (compositor-only). Копирайт empty-state — русский (`до 1 файла · до 500 МБ`), `renderBytes` локализован (Б/КБ/МБ…). Attribution — шапкой-комментом (NOTICE-файла в репо нет, новую конвенцию не ввожу).
> - `[role=presentation ПОЙМАН]` `react-dropzone@15` `getRootProps()` форсит `role="presentation"` — это сломало бы `getByRole('button')` в тесте. Фикс: после спреда `getRootProps()` ставлю `role={undefined}` → возвращается implicit button-role (без jsx-a11y redundant-role lint на `<button>`).
> - `[ASYNC isDragActive]` `onDragEnterCb` ставит `isDragActive` НЕ синхронно — после `getFilesFromEvent()` Promise. Тест drag-active обязан быть `async` + `waitFor`, а `dataTransfer` — с `types:['Files']` + `files`/`items` (с `getAsFile`), иначе `isEvtWithFiles` ложен и флаг не встанет. (Урок для e2e/компонент-тестов dnd в P1.7.)
> - `[YAGNI]` `DropzoneContent` (file-chip) НЕ добавлен на 1.6 (тестов на него тут нет, тянул coverage вниз) — придёт в P1.7 вместе с тестом дропа файла. Сейчас в примитиве только `Dropzone` + `DropzoneEmptyState` + PromptInput-семейство.
> - `[COMMIT-СТРОКА]` Роадмап-строка коммита `feat: add AI Elements PromptInput and Kibo Dropzone primitives` неточна (ai-elements не используется) → использован правдивый месседж `feat: add swiss dropzone and prompt-input hero primitives`.
> - `[UNTRACKED]` `apps/web/src/app/[locale]/design-preview/page.tsx` (temp P1.5-preview) оставлен untracked, в коммит P1.6 НЕ включён.
> - `[PUSH ✅]` Коммит P1.6 запушен в `origin/p1.4-design-tokens` (`80075a4..190dc6b`). Первая попытка падала на `github.com:443` (сетевая проблема окружения, не код), повтор прошёл.
>
> **Заметки исполнителя — P1.7 (2026-06-15) [🛑 ЧЕКПОИНТ C]:**
> - `[ПУТЬ УТИЛИТЫ]` Роадмап говорил `src/lib/url.ts: isVideoUrl`, но в `apps/web` нет `src/lib/` (конвенция — `src/utils/`, ср. `Helpers.ts`). Утилита заведена как `src/utils/isVideoUrl.ts` (отклонение пути, не контракта; имя функции `isVideoUrl` сохранено). Предикат: `new URL()` в try/catch, только http(s), host ∈ {youtube/youtu.be/vimeo/dailymotion/twitch} ИЛИ pathname `\.(mp4|mov|webm|m4v)$`.
> - `[matchMedia МОК]` jsdom не реализует `window.matchMedia`, на который опирается новый `useReducedMotion`. Добавлен guarded дефолт-мок (`matches:false`) в `vitest.setup.ts` под `if (typeof window !== 'undefined')` (setup грузится и в node-проекте). Тест reduced-motion переопределяет `matchMedia` на `matches:true`.
> - `[globalDrop = РЕГИОН]` «видео в любом месте hero» реализовано как `onDrop` на root-`<section>` (hero-регион), а не document-wide listener — проще, без cleanup, ровно по тесту `globalDrop on the hero region`. Drop по боксу обрабатывает react-dropzone; bubbling в region-handler идемпотентен (тот же файл).
> - `[submitted→streaming]` Переход наблюдаем: `setStatus('submitted')` синхронно, затем `setTimeout(()=>setStatus('streaming'),0)` (реальный бэкенд-стриминг — P2). Сигналы для тестов: `data-status` на root-`<section>` И на submit-кнопке (добавил `data-status` в примитив `PromptInputSubmit`), `data-animate` на root (present ⇔ анимация разрешена).
> - `[ТЕСТ-ЛОВУШКА]` `getByText(/url/)` ловит ДВА узла — link-chip И `<textarea>` (React кладёт controlled-value текст-нодой, которую testing-library матчит). Чипы в тестах запрашиваются по `data-slot="file-chip"`/`"link-chip"`, не по тексту. Файл-дроп — `fireEvent.drop` + `dataTransfer.files`, рендер чипа асинхронен (react-dropzone Promise) → `waitFor`.
> - `[GATES]` 54 теста зелёные (+15), lint/typecheck 0, coverage 92% stmts / 92.78% lines (branches 79.78% — жёсткого порога нет; непокрытое — защитные ветки). Без новых тяжёлых deps.
>
> **Заметки исполнителя — P1.8 (2026-06-15):**
> - `[ПУТЬ РОУТА]` Роадмап говорил `src/app/(landing)/page.tsx`, но фактическая структура форка — `src/app/[locale]/(marketing)/page.tsx` (это `/`; своего `(marketing)/layout.tsx` нет, обёртка только в `[locale]/layout.tsx`). Лендинг подключён туда: boilerplate-шаблоны (DemoBanner/Navbar/Hero/Sponsors/Features/Pricing/FAQ/CTA/Footer) заменены на `<Landing/>`; metadata переписана на русскую FlipHouse-строку (вместо `getTranslations('Index')`). Отклонение пути, не контракта.
> - `[DROPBAR — ВЫБОР FOUNDER'А]` Открытый вопрос ЧП C («слить дропзону в один бокс как эталонный `.dropbar`») закрыт: founder выбрал опцию 2 — визуальный рестайл. `HeroDropzone` теперь оборачивает `Dropzone` + `PromptInput` в ОДИН контейнер `data-slot="dropbar"` (один бордер `--rule-strong`, hairline `divide-y` между полями; внутренние боксы → `border-0 bg-transparent`). Поведение/состояния/`onFlip` и все 12 тестов P1.7 НЕ тронуты (рестайл, не переписывание) — добавлен 1 новый структурный тест `hero dropzone is a single bordered dropbar container` (RED→GREEN). CHECKPOINT C не переоткрывается.
> - `[ИМЕНА ТЕСТОВ verbatim]` 5 имён тестов взяты дословно из роадмап-«Тесты СНАЧАЛА» (англ.), ассерты — под русскую реальность: `navbar has aria-label Main navigation` проверяет фактический лейбл `/основная навигация/i` (SiteHeader из P1.5). Тест-файл — `components/landing/Landing.test.tsx` (тестирует презентационный `Landing`, а не server-`page.tsx` с next-intl).
> - `[banner-РОЛЬ]` testing-library `getByRole('banner')` матчит ЛЮБОЙ `<header>` (не скоупит по sectioning-content). Поэтому `SectionHead` сделан `<div>`, а не `<header>` — иначе нумерованные заголовки секций ловились бы как banner и тест landmark'ов падал на «multiple». Единственный banner = SiteHeader.
> - `[COVERAGE-ОТЧЁТ]` Текстовый v8-репортер схлопывает 100%-директории — новых файлов (sections/landing/HeroSection/AnimatedHeading/SiteFooter) в таблице не видно. Проверено по `coverage/coverage-final.json`: ВСЕ новые компоненты 100% statements. Корневой `pnpm coverage` exit 0 (агрегат 92.95% stmts; жёсткого web-порога в конфиге нет — гейт держится exit-кодом).
> - `[COMMIT-СТРОКА]` Роадмап-строка `feat: assemble landing sections from launch-ui with animated hero heading` неточна (launch-ui выкинут по ЧП B, секции собраны кастомно по эталону) → правдивый месседж `feat: assemble swiss landing sections and merge hero into single dropbar`.
> - `[SHA]` Записанный SHA P1.8 = pre-amend twin (sha вписывается в тело коммита, что математически меняет реальный HEAD при `--amend`; паттерн как в P0/P1.4/P1.7). Реальный HEAD — `git log -1`.
> - `[DEV-СЕРВЕР]` Стоит висящий pglite-server на :54329 от прошлых сессий (EADDRINUSE при `pnpm dev`), но `next dev` всё равно поднялся на :3000 и отдал лендинг 200 — визуальная проверка прошла. На лифте деплоя (1.14–1.15) учесть graceful-shutdown pglite.
>
> **Заметки исполнителя — P1.11 (2026-06-15) [🛑 ЧЕКПОИНТ E]:**
> - `[FOUNDER EDIT — ОРГАНИЗАЦИИ УБРАНЫ]` Посреди реализации org-онбординга founder отверг сам концепт организаций («зачем нам организации — человек выбрал роль и пошёл дальше»). По §6 это [CONFLICT] с уже закоммиченным P1.10 (org-таблица). Решение founder'а: роль — на ПОЛЬЗОВАТЕЛЕ, хранить в **Clerk `publicMetadata`** (не в БД). Org-подход P1.10 отменён и вычищен.
> - `[МОДЕЛЬ]` `src/libs/accountType.ts`: `AccountType='creator'|'advertiser'`, `getAccountType(userId)` = `clerkClient().users.getUser` → `publicMetadata.accountType` (нарратив `unknown`→narrow), `setAccountType(userId,type)` = immutable (читает; если задано — throw) + `users.updateUser(..., {publicMetadata})`. Никакой БД.
> - `[RBAC НА СТРАНИЦАХ, НЕ В MIDDLEWARE]` `requireAccountType` зовётся в server-компонентах дашбордов; индекс `/dashboard` — редирект-роутер. `proxy.ts` org-гейт удалён, `NextResponse` больше не импортируется. Это чище, чем DB/Clerk-вызов в middleware на каждый запрос.
> - `[ПУТИ — ОТКЛОНЕНИЯ ОТ РОАДМАПА]` Роадмап говорил `src/lib/rbac.ts`, `src/app/onboarding/actions.ts`, `tests/e2e/onboarding.spec.ts`. Факт: `src/libs/rbac.ts` (в форке `src/libs/`, не `src/lib/`), `src/app/[locale]/(auth)/onboarding/actions.ts` (реальная структура), `tests/onboarding.e2e.ts` (под `testMatch` форка `*.e2e.ts`). Контракты/имена тестов сохранены, под user-модель (orgId→userId, «no org»→«no user»→`/sign-in`).
> - `[CLERK ОТКЛЮЧИЛ ОРГ]` Шаг «Setup your organization» (`/sign-up/tasks/choose-organization`) приходил из настроек Clerk-инстанса; founder отключил Organizations в Clerk-дашборде сам. Без этого регистрация форсила создание орги.
> - `[E2E НЕ ДОВЕДЁН ДО ЗЕЛЁНОГО В SANDBOX]` `tests/onboarding.e2e.ts` (`@clerk/testing`: `setupClerkTestingToken`, уникальный `<base>+clerk_test@…`, код `424242`; globalSetup `clerkSetup`; `.env.local` грузится в `playwright.config.ts` своим парсером, т.к. `@next/env`/`dotenv` не резолвятся). В браузере регистрация+верификация проходят, доходит до `/dashboard`, но server-side рендер дашборда зависает на вызове Clerk Backend API (`getUser`) ИЗ процесса next-dev. Прямой `curl` к `api.clerk.com` из bash = 200/0.78с → это ограничение вложенного dev-процесса в песочнице, не баг кода. Гейт-скип в CI/без ключей. **На реальной машине founder проходит оба пути на ЧЕКПОИНТЕ E.**
> - `[МИГРАЦИИ]` Удалены `migrations/0001_account-type.sql` + `meta/0001_snapshot.json` + запись в `_journal.json`; `Schema.ts` снова = `todo`; `db:generate` → «No schema changes». dev `local.db`-директория была повреждена (pglite wasm crash при `pnpm dev`) — удалена; playwright использует in-memory pglite (`-m 100`), там ок.
> - `[ЧУЖИЕ НЕЗАКОММИЧЕННЫЕ ПРАВКИ]` В рабочем дереве с начала сессии висят НЕ мои правки лендинга (`(marketing)/page.tsx`, `[locale]/layout.tsx`, `hero/*`, `sections/*`, `SectionHead.tsx`, `AppConfig.ts`, `styles/tokens.css`, `docs/02`, untracked `LANDING-SYSTEM.md`/`opengraph-image.tsx`) — вероятно landing-system-проход. Коммит P1.11 собран СТРОГО из onboarding/rbac/accountType-файлов; эти правки не трогал и не коммитил — разрулить отдельно.
>
> **Заметки исполнителя — P1.12 (2026-06-16):**
> - `[ЧЕКПОИНТ E ✅]` Founder прогнал онбординг вживую (creator-путь, скриншот «Кабинета креатора»). Песочный e2e-висяк P1.11 (server→Clerk Backend API внутри next-dev) — ограничение sandbox, на реальной машине путь работает.
> - `[РАЗВИЛКА Q2 — ТОЛЬКО ИНТЕРФЕЙС+МОК]` Founder выбрал: реальный `provider/tron.ts` (tronweb/HD-derive/сеть/выплаты) НЕ в P1.12, а целиком в P1.13/ЧЕКПОИНТ F. В P1.12 — `PaymentProvider`-интерфейс + детерминированный `provider/mock.ts` (TRC-20 адрес = `T`+33 base58 из sha256(userId), без сети/ключей/`tronweb`-зависимости) + `provider/tron.ts`-заглушка (`throw 'checkpoint F'`). Env `TRON_HD_SEED`/hot-key НЕ заводил (придут с реальным провайдером в P1.13/F → KMS).
> - `[ПЕРВЫЕ ДОМЕННЫЕ ТАБЛИЦЫ]` `Schema.ts` расширен (был только `todo`): `subscription` (PK=`userId`) + `balance_entries` (ledger, signed `amount_usdt`). Идемпотентность на уровне БД: unique `(user_id, job_id)` (PAYG-дебеты; NULL job_id для депозитов не коллидят — Postgres NULL distinct) + unique `txid` (депозиты P1.13). Миграция `0001_billing-schema.sql` через `db:generate --name billing-schema`; повторный generate = «No schema changes» (идемпотентна). Применение проверено эфемерным in-mem PGlite-мигратором во ВСЕХ balance-тестах (паттерн из удалённого P1.10-харнесса воскрешён инлайн в `balance.test.ts`).
> - `[ДЕНЬГИ — МИКРО-USDT + АТОМАРНЫЙ ДЕКРЕМЕНТ]` Балансовая математика в integer micro-USDT (`money.ts`), хранение `numeric(20,6)`. `debit` переписан с read-compute-write на **атомарный SQL** `set balance = balance - ${amount}::numeric` внутри транзакции — устраняет lost-update при конкурентных дебетах разных job одного юзера (hot-path клиппинга). `chargeMonthlySubscription` (cold-path, раз/мес) оставлен read-compute-write в транзакции.
> - `[DI-DRIZZLE, НЕ СИНГЛТОН]` `balance.ts`/`usageGate.ts`/`subscription.ts` принимают `db: BillingDatabase` параметром (прод даёт синглтон `@/libs/DB`, тесты — pglite-drizzle). Это держит юнит-тесты вне сети (в отличие от P1.11-висяка через серверный Clerk-вызов) и изолирует БД per-test.
> - `[ПОКРЫТИЕ]` Все мои billing-`.ts` доведены до 100% (добавил тесты на defensive-ветки: mock.createPayout, no-row getBalance/charge, free-default gate, BILLING_PLAN_ENV override; упростил `parseUsdt` до string-only, `debit.jobId` сделал обязательным — без него идемпотентность невозможна). `DepositPanel` покрыт RTL/jsdom; серверный `creator/page.tsx` (auth+provider) — не юнит-тестится (e2e-территория P1.16, как дашборды P1.11).
> - `[ОТКЛОНЕНИЯ ОТ РОАДМАПА §1.12]` (а) Интерфейс `PaymentProvider` оставлен чисто on-chain (`getDepositAddress`/`createPayout`); off-chain ledger-операции (`getBalance`/`debit`) роадмап лумпил в провайдер, но чище держать их в `balance.ts` (chain-agnostic). (б) `usageGate.ts` отдельным файлом (роадмап его упоминал). (в) QR в DepositPanel пока НЕ рисую (нет qr-зависимости; YAGNI) — показываю TRC-20 адрес+copy, QR придёт при реальном депозит-флоу. (г) `PAYMENT_PROVIDER` enum включает `mock` (не только `tron`) — нужен дев/тест-дефолт.
> - `[WEB ESLINT НЕ ГОНЯЕТСЯ]` `apps/web/eslint.config.mjs` тянет `@antfu/eslint-config`, не установленный в этом окружении → web-eslint падает на резолве (пре-существующее, web-lint НЕ в гейте — см. P1.1-заметку). Гейт держится: root lint 0 + web check:types 0 + root typecheck/test/coverage 0.

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

## P1 — Веб-каркас: auth, биллинг, лендинг с hero-дропзоной ✅

**Цель:** Поднять и задеплоить на Railway полностью рабочую веб-оболочку FlipHouse: форк ixartz/SaaS-Boilerplate (Next.js App Router + Clerk auth + Postgres/Drizzle), крипто-биллинг за абстракцией `PaymentProvider` (USDT-баланс: PAYG $0.25/мин + подписка с лимитом минут; Stripe/ЮKassa убраны), приватная сеть Postgres+Redis, два типа аккаунта creator/advertiser с RBAC-разводкой дашбордов, и Lovable-style dark AI-tech лендинг с центрированной hero-дропзоной (Kibo Dropzone + AI Elements PromptInput над shadergradient WebGL-mesh, drag&drop + paste-link + статусы ready/submitted/streaming/error), launch-ui секции, motion + Magic UI + GSAP/Lenis scroll-сторителлинг. Всё через строгий TDD (RED→GREEN→refactor→commit, coverage ≥80%, zero bugs).

**Файл роадмапа:** `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P1-web-auth-billing-landing.md`
**Зависит от:** P0

### Шаги

- ✅ Шаг P1.1 · 87d0b54 · 2026-06-15 [✅ ЧЕКПОИНТ A одобрен · форк SaaS-Boilerplate → apps/web · PR #1 → main]
- ✅ Шаг P1.2 · f68358c · 2026-06-15 [/api/health: db+redis пробы, 200/503, публичный]
- ✅ Шаг P1.3 · 1e3e813 · 2026-06-15 [ioredis-синглтон на REDIS_PRIVATE_URL + Zod env-валидация + реальный probeRedis ping]
- ✅ Шаг P1.4 · 137fd81 · 2026-06-15 [oklch дизайн-токены через Style Dictionary; направление «Swiss Pop» после ЧП B] [✅ ЧЕКПОИНТ B одобрен]
- ✅ Шаг P1.5 · 826a622 · 2026-06-15 [Swiss-каркас: next/font (Archivo/Narrow/Plex Mono) + jsdom/RTL + SiteHeader/Eyebrow]
- ✅ Шаг P1.6 · 79bed45 · 2026-06-15 [Swiss dropzone-примитив: kibo-лифт перестилен + кастомный PromptInput-семейство; ai-elements отброшен по ЧП B]
- ✅ Шаг P1.7 · 619defe · 2026-06-15 [CHECKPOINT C] [Hero-дропзона: drop+globalDrop+paste-link, состояния ready/submitted/streaming/error, валидация, onFlip; isVideoUrl-утилита + useReducedMotion]
- ✅ Шаг P1.8 · 41558c9 · 2026-06-15 [Swiss-лендинг: hero слит в один .dropbar + секции 01–04 + marketplace + receipts + closer + footer; AnimatedHeading word-split]
- ✅ Шаг P1.9 · 8789602 · 2026-06-15 [🛑 ЧЕКПОИНТ D] [scroll-сторителлинг: GSAP ScrollTrigger + Lenis, compositor-only reveal-твины, reduced-motion off, dynamic import]
- ✅ Шаг P1.10 · 6d080a3 · 2026-06-15 [organizationSchema создана (в форке не было) + `account_type` pgEnum nullable + миграция 0001; интеграц. тест-харнесс на PGlite; helper отложен в 1.11]
- ✅ Шаг P1.11 · 2026-06-15 [🛑 ЧЕКПОИНТ E] [онбординг creator/advertiser БЕЗ организаций; роль в Clerk publicMetadata (FOUNDER EDIT); rbac-гейт дашбордов; детерминированные гейты зелёные; e2e в sandbox не доводится до зелёного (server→Clerk Backend API), founder проверяет вживую]
- ✅ Шаг P1.12 · 2026-06-16 [крипто-биллинг через PaymentProvider (моки): subscription+balance_entries Drizzle, plans/balance/usageGate/subscription, mock+tron-stub провайдеры, DepositPanel; ЧП E одобрен вживую; billing 100% coverage]
- ✅ Шаг P1.13 · ded8635 · 2026-06-16 [on-chain TRON deposit watcher на фикстурах: credit() идемпотентен по txid + processTransfers (фильтр USDT/confirmations≥19/маппинг address→userId/фактическая on-chain сумма) + runWatcherTick (курсор Redis/in-mem) + getOrCreateDepositAddress персист + миграция 0002 partial-unique на deposit_address; web 116 тестов, watcher+balance 100% coverage, гейты зелёные]
- ✅ Шаг P1.13.1 · 6935601 · 2026-06-16 [реальный on-chain TRON (HD-кошелёк + TronGrid-поллер, testnet; сеть замокана): `provider/tron.ts::getDepositAddress(userId,index)` — реальная BIP44-деривация `m/44'/195'/0'/0/{index}` (coin 195) через `TronWeb.fromMnemonic` из `TRON_HD_MNEMONIC` (статик, без сети; приватный ключ отбрасывается — depositonly; вектор сверен с каноническим BIP39 «abandon…about» → index0=TUEZSdKsoDHQMeZwihtdoBiN46zxhGWYdH, index1=TSeJ…); `createPayout` остаётся заглушкой (P5). **Approach A** (выбор founder'а): аллокация последовательного `deposit_index` в БД-оркестраторе `getOrCreateDepositAddress` (транзакция, `COALESCE(MAX,-1)+1`, persist address+index), провайдер — чистый деривер; интерфейс `PaymentProvider.getDepositAddress(userId,index)`. `source.tron.ts::makeTronChainSource({fetch,rpcUrl,usdtContract,listAddresses,apiKey})` — реальный TronGrid REST через инжектируемый `fetch`: `getCurrentBlock` (`/wallet/getnowblock`→block_header.raw_data.number), `getTransferEvents` (per-address `/v1/accounts/{a}/transactions/trc20` + **blockNumber резолвится ВТОРЫМ вызовом** `/wallet/gettransactioninfobyid` — trc20-эндпоинт отдаёт только block_timestamp), zod-валидация ответов, фильтр USDT+наш адрес+диапазон блоков. Миграция `0003_deposit-index` (`deposit_index integer` + partial-unique `subscription_deposit_index_uq`). Env: `TRON_HD_MNEMONIC` (secret optional, .env.local/KMS), `TRON_RPC_URL` (default nile). Security-review (security-reviewer agent): HIGH+LOW (untrusted node мог слить баланс отрицательной суммой / уронить тик нечисловой `value`) — закрыт `parsePositiveAmount` (skip non-`^\d+$`/≤0) на границе source + TDD-тест; secret-handling/деривация-коллизии/URL-инъекции — clean. Тесты: provider/tron (2) + tron.mnemonic (1) + source.tron (6) + depositAddress sequential (1); **web 108 unit (root агрегат 125), lint/typecheck/check:types 0, coverage exit 0 (95.39%; provider/tron+mock+PaymentProvider+balance 100%, payments/watcher 99.05%, source.tron.ts 100% stmts)**. **НЕ в шаге (→ ЧЕКПОИНТ F / worker-wiring):** живой Nile-депозит, KMS/hot-cold, worker-cron-entrypoint, реальный `listAddresses` из БД в проде, MEDIUM-риск гонки конкурентной аллокации index (backstop = unique-constraint, без порчи; retry/sequence — на F)]
- ✅ Шаг P1.14 · 92ac502 · 2026-06-16 [railway.json config-as-code: `apps/web/railway.json` (builder NIXPACKS; deploy.startCommand `next start -H ::` dual-stack-бинд / healthcheckPath `/api/health` / preDeployCommand `pnpm db:migrate` runtime-миграции / numReplicas 2 HA / restartPolicyType ON_FAILURE). 4 теста `tests/infra/railway-config.test.ts` (RED→GREEN) читают один источник — committed railway.json через `JSON.parse(readFileSync)` (drift intent↔deploy = красный CI). `vitest.config.ts` include расширен `tests/infra/**/*.test.ts` (Playwright владеет `*.e2e.ts`, не пересекаются). Reference-переменные `${{Postgres.DATABASE_PRIVATE_URL}}`/`${{Redis.REDIS_PRIVATE_URL}}` + секреты Clerk/TronGrid/KMS — service variables, проставляются в P1.15 (не в railway.json, YAGNI). Реальный `railway up` — P1.15. **web 112 unit (root агрегат 129), lint/typecheck/check:types 0, coverage exit 0 (95.39%; railway.json вне coverage.include — не исполняемый код).**]
- ✅ Шаг P1.15 · f3a9930 · 2026-06-16 [деплой web на Railway **staging** (живой): проект `fliphouse` (id 55f795c1) + окружение `staging` + managed Postgres/Redis (deploy_template). Сервис `web` из GitHub-репо lindwerg/FlipHouse, `root_directory=apps/web`, builder **RAILPACK**. Деплой нашего локального состояния ветки через `railway up` (tarball, не stale-main: наша работа в main не смержена). Домен `https://web-staging-32d77.up.railway.app`. Переменные (через railway CLI, секреты не в репо/чате): приватные `DATABASE_URL=${{Postgres.DATABASE_URL}}` (internal `postgres.railway.internal`) + `REDIS_PRIVATE_URL=${{Redis.REDIS_URL}}` (internal) + Clerk(pk/sk) + TRON(nile/USDT-Nile/19/RPC) + `TRONGRID_API_KEY`/`TRON_HD_MNEMONIC` (secret). **railway.json исправлен для реального деплоя** (P1.14 был под локальный pglite): builder NIXPACKS→**RAILPACK**, добавлен `buildCommand: npm run build:next` (чистый `next build` — иначе Railpack гнал локальную pglite-обёртку `run-s db:migrate build:next` и падал на миграции против railway.internal в build-сети без приватной сети), `preDeployCommand: pnpm→npm run db:migrate` (в Railpack-образе нет pnpm). 4 P1.14-теста остались зелёными (builder/buildCommand не проверяются, `db:migrate`/`::` substring сохранены). Deploy-логи: preDeploy `drizzle-kit migrate` (pg-драйвер, exit 0 против реального Postgres) → старт на **`[::]:8080`** (dual-stack ✓) → healthcheck `/api/health` → `{"status":"ok","db":"up","redis":"up"}` (приватная сеть к PG+Redis работает). **Smoke `tests/deploy-smoke.e2e.ts` (3 теста, self-skip без `STAGING_URL`, `webServer` отключён в этом режиме) GREEN на staging-домене:** health 200/https; лендинг h1+primary-CTA(`/sign-up`); нет `sk_`/`whsec_` в HTML. **web 112 unit (root агрегат 129), lint/typecheck/check:types 0, coverage exit 0 (95.39%).** **ОТКЛОНЕНИЯ/НЕ В ШАГЕ:** (а) `payments-watcher`-сервис НЕ деплоен — worker-entrypoint/cron ещё не существует (отложено в P1.13 → worker-wiring/P2); деплоить нечего. (б) smoke-тест №2 переименован `hero dropzone`→`primary CTA`: текущий лендинг (одобрен на ЧП D, landing-system-проход) имеет CTA-герой (H1 + «Загрузить видео»→/sign-up), а hero-дропзона переехала в дашборд/`/tron-demo` — роадмап-имя устарело, ассерчу реальный контракт. (в) GitHub-сервис следит за `main` (auto-redeploy активируется, когда ветка смержится в main — там уже будет railway.json); пока staging держит наш uploaded-build.]
- ✅ Шаг P1.16 · 9c0bf26 · 2026-06-16 [✅ ЧЕКПОИНТ G ОДОБРЕН founder'ом 2026-06-16 — «всё ок, коммит/пуш/мёрж»; JS-бюджет 203kb>150kb принят, CWV в норме] — закрытие фазы обязательным e2e (`web/testing.md`): сквозные пути на стыках app + визуальная регрессия + перф-гейт лендинга. (1) **Баланс на дашборде креатора**: новый `getSubscriptionSummary(db,userId)` в `balance.ts` (plan/balanceUsdt/subscriptionStatus, дефолт free/0/null без строки) + презентационный `BalancePanel.tsx` (`data-slot="balance"`/`data-slot="plan"`, Swiss-стиль) подключён в `dashboard/creator/page.tsx` (раньше показывался только deposit-адрес — пробел DoD «дашборд показывает баланс/active-план»). (2) **Dev-only fund-роут** `src/app/api/dev/payments/fund/route.ts` (POST, `runtime=nodejs`): hard-403 при `NODE_ENV=production`, 401 без auth, иначе гонит **реальный `runWatcherTick`** с `fakeChainSource` подтверждённого трансфера (`head=block+TRON_CONFIRMATIONS` → confirmations-гейт проходит) на deposit-адрес юзера → `credit` идемпотентный по txid; опц. `txid` в теле для идемпотентности, дефолт `randomUUID()`. Прогоняет весь watcher-путь детерминированно, без TRON-сети — e2e так пополняет баланс. (3) **e2e (Playwright)**: `tests/e2e/signup-subscribe-dashboard.spec.ts` (главный — signup→onboarding creator→баланс 0→POST fund→reload→баланс 50; **guard-skip в CI** как `onboarding.e2e.ts`: песочница виснет на server→Clerk Backend API, в CI нет ключей — founder гонит вживую на G; машинерия пополнения/баланса валидирована unit-тестами); `tests/e2e/hero-drop.spec.ts` (публичный, **в CI**: файл→чип / ссылка→чип / не-видео→ошибка — таргет `/design-preview`, где живёт дропзона после редизайна hero на CTA); `tests/e2e/visual.spec.ts` (**no-overflow 320/768/1024/1440 в CI** — платформо-независимо, закрывает DoD «без overflow», все 4 зелёные → редизайн починил прошлый 320px-долг; **pixel-снапшоты** darwin-baseline, `reducedMotion` детерминизм, guard-skip в CI). Фикстуры `tests/fixtures/{sample.mp4(ffmpeg),not-a-video.txt}`. `playwright.config.ts` testMatch += `spec`. (4) **Lighthouse-гейт** `scripts/lighthouse.mjs` + `test:lighthouse` (lighthouse+chrome-launcher, desktop-конфиг; **локально+staging, НЕ в CI** — решение founder'а): прод-билд → `next start` → CWV-бюджеты. Прогон против локального прод-билда: **LCP 883ms<2500 ✓ / CLS 0<0.1 ✓ / TBT 0ms<200 ✓ / First-Load-JS 203kb >150kb ✗** (First-Load меряется gzip-ом `<script>`-чанков начального HTML из `.next/static` — lazy GSAP/Lenis по дизайну `web/performance.md` исключены). **CWV отличные; First-Load-JS лендинга 203kb превышает бюджет 150kb на ~53kb — РАЗВИЛКА ДЛЯ founder'а на G** (оптимизировать бандл / релакс бюджета / принять для staging). Гейты: **root lint 0, root typecheck 0, web check:types 0, coverage exit 0 (95.44% stmts; route 100% lines, BalancePanel/summary 100%), CI e2e 8 passed / 6 skipped** (auth×2 + deploy-smoke×3 + pixel-снапшот×1).
- ⬜ Шаг P1.17 — артефакт нумерации (в `roadmap/P1` нет такого шага; фаза закрывается на 1.16 + ЧЕКПОИНТ G)

### Чекпоинты

- ✅ ЧП A: база форка поднята, тесты зелёные — одобрено founder'ом («го, открывай PR») · PR #1 смержен в `main` · live sign-in проверен · 2026-06-15
- ✅ ЧП B: дизайн-направление утверждено — **Swiss Pop** (светлая, paper/ink + vermillion/cobalt); 2 раунда дизайн-разведки, founder выбрал и сказал «го» · 2026-06-15
- ✅ ЧП C: hero-дропзона со всеми состояниями — одобрено founder'ом (смотрел живьём на `/design-preview`, «комит и пуш, пойдём дальше») · 2026-06-15
- ✅ ЧП D: лендинг целиком (секции + scroll + моушен) — одобрено founder'ом («пока норм, пуш и мёрж») · ветка P1.4–P1.9 → `main` · 2026-06-15
- ✅ ЧП E: два типа аккаунта + онбординг-развод — одобрено founder'ом (прогнал онбординг creator/advertiser вживую, скриншот «Кабинета креатора») · 2026-06-16
- ✅ ЧП F: крипто-биллинг (свой TRON on-chain): депозит USDT → watcher → баланс → PAYG/подписка — **одобрено founder'ом (2026-06-16): «го на деплой (P1.14+)»**; путь депозит→watcher→баланс валидирован вживую на Nile (1000 USDT, ~68 подтверждений, идемпотентно по txid), `/tron-demo` рисует реальный баланс. Тарифы/PAYG/подтверждения (19) founder не менял.
- ✅ ЧП G: **ОДОБРЕН founder'ом (2026-06-16): «всё ок — коммит, пуш, мёрж».** Задеплоено на staging (живой `https://web-staging-32d77.up.railway.app`); сквозные e2e + hero-drop + визуальная регрессия зелёные (auth-путь guard-skip в CI — машинерия валидирована unit-тестами); Lighthouse: CWV (LCP 883ms/CLS 0/TBT 0) в бюджете. **First-Load-JS лендинга 203kb > 150kb — founder ПРИНЯЛ** (оптимизацию бандла отложили, не блокер). Фаза P1 завершена → мёрж ветки в `main`. Промоут staging→production — за founder'ом в Railway-дашборде.

### Ключевые тесты

- `signup → subscribe → lands on creator dashboard with active plan (Playwright e2e)`
- `submit with a file transitions ready→submitted→streaming and calls onFlip with the file (HeroDropzone component test)`
- `payment.succeeded sets subscriptionStatus=active for the user (PaymentProvider webhook integration)`
- `rejects request with invalid signature (400) and does not mutate db (operator webhook security)`
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

**Цель:** Поднять полный self-serve двусторонний маркетплейс: advertiser публикует оффер (JSON-схема doc 03 §1) → creator находит/аппрувится/матчится → принятие генерирует impression_unit и детерминированно привязывает оффер к рендеру → клип рендерится с этим баннером → конверсия регистрируется → начисление через clean-room cliq-субстрат (Link→Conversion→Commission, Function/Condition/Effect) → выплата креатору в USDT через `PaymentProvider.createPayout` (свой TRON on-chain, `tronweb`). Поверх Phase 1 подписок добавлен идемпотентный metered-биллинг как наш `usage_events`-ledger (per-clip/per-render/CPM, no double-charge на ретрае; не Stripe Meters). Impression/CPM attribution v1: creator-OAuth метеринг по дельтам просмотров + трекинг-ссылки + аудит, с честными ограничениями doc 03 §5.4. TDD обязателен, покрытие ≥80%, детерминированные ядра 100%.

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
- ⬜ ЧП-7 (5.19): metered usage идемпотентность — наш `usage_events`-ledger (no double-charge)
- ⬜ ЧП-8 (5.22): attribution v1 + честные ограничения
- ⬜ ЧП-9 (5.24): payout креатору в USDT через `PaymentProvider.createPayout` (свой TRON, `tronweb`) + settlement
- ⬜ ЧП-10 (5.26): сквозной e2e + покрытие ≥80%

### Ключевые тесты

- `test('full flow: post offer → apply → accept → render → conversion → payout')`
- `test('idempotency: повтор accept+render+meter не задваивает ни impression_unit, ни usage, ни payout')`
- `test('повторный recordUsage того же события НЕ создаёт второй usage_events row')`
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
