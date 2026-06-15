# FlipHouse — Мастер-документ

> Стратегический мастер-файл. Единая точка входа в архитектуру, экономику и план сборки.
> Версия 1.0 · 2026-06-14 · Деплой-цель: Railway (Pro)

---

## 1. Видение продукта (одним абзацем)

**FlipHouse — это не инструмент нарезки, который ты арендуешь, а монетизационный рельс, в который ты подключаешь свой длинный контент.** Креатор загружает длинное видео → ИИ нарезает вертикальные клипы → ИИ автоматически вставляет в кадр *подобранный рекламный оффер* (продукт на столе, нижний колонтитул-купон, end-card CTA) → рекламодатель платит → креатор получает деньги, без агентства-посредника и без «армии нарезчиков». Слоган: **«Клип, который сам себя окупает».** Ты не платишь FlipHouse — платят рекламодатели, а ты делишь выручку. Это превращает то, что у конкурентов является ежемесячным счётом (Opus/Klap/Submagic) или корпоративным гейтом «Request Demo» (Rembrand), в один self-serve цикл для длинного хвоста креаторов.

---

## 2. Полный стек (слой → форк → лицензия → Railway-сервис)

| Слой | Выбранный форк / библиотека | Лицензия | Railway-сервис |
|---|---|---|---|
| **Лендинг / маркетинг** | `launch-ui/launch-ui` (Next.js 16, React 19, Tailwind v4, shadcn) | MIT | `web` |
| **Анимации лендинга** | `magicuidesign/magicui` + Aceternity UI (free) + `ibelick/motion-primitives` | MIT | `web` |
| **Motion-движок** | `motiondivision/motion` (ex-Framer Motion, `motion/react`) | MIT | `web` |
| **Scroll-сторителлинг** | GSAP + ScrollTrigger + `darkroomengineering/lenis` | GSAP no-charge (free commercial) / MIT | `web` |
| **SaaS-каркас (auth/биллинг/мульти-тенант)** | `ixartz/SaaS-Boilerplate` (Clerk, RBAC, next-intl) | MIT | `web` |
| **AI-чат / ассистент UI** | `vercel/ai-chatbot` (centered greeting, multimodal input) | Apache-2.0 | `web` |
| **Фронт-сервер (SSR/API-роуты)** | Next.js standalone | MIT | `web` |
| **Резюмируемая загрузка видео** | `tusproject/tusd` (`-hooks-http` → `web /api/tus-hooks`) | MIT | `tusd` |
| **Очередь задач (оркестрация)** | BullMQ воркер (Node) | MIT | `bullmq-worker` |
| **Нарезка длинного видео → клипы** | `mutonby/openshorts` — только `main.py` (engine), CPU-only, **Gemini → OpenRouter swap** | MIT (форк); *prompt CTA вырезать* | `ai-render-worker` |
| **Транскрипция** | `faster-whisper` (`base`, device=cpu, int8) | MIT | `ai-render-worker` |
| **Реврейм 9:16 + трекинг спикера** | MediaPipe FaceDetection + YOLOv8n fallback + PySceneDetect (внутри `main.py`) | Apache-2.0 / AGPL-осторожно (см. риски) | `ai-render-worker` |
| **LLM выбор хайлайтов** | OpenRouter (`google/gemini-2.5-flash`, OpenAI-совместимый, text→JSON) | коммерч. API | внешний API |
| **Video inpainting / вставка оффера в кадр** | `lixiaowen-xw/DiffuEraser` (temporal consistency) | **Apache-2.0** | внешний GPU (Replicate) |
| **Tracking поверхностей для вставки** | `zrporz/AutoSeg-SAM2` (mask propagation) | MIT | внешний GPU (Replicate) |
| **GPU-инференс (inpainting/diffusion)** | Replicate (Railway без GPU — см. риски) | коммерч. API | внешний |
| **Оверлей рекламного баннера (ffmpeg)** | `ad_banner.py` — клон `hooks.py:add_hook_to_video` | MIT (наш код) | `ai-render-worker` |
| **Matching-движок (клип ↔ оффер)** | transcript embeddings ↔ offer vectors (наш код, наш data-moat) | наш | `bullmq-worker` |
| **Реляционная БД** | Railway Postgres plugin (`DATABASE_PRIVATE_URL`) | managed | `Postgres` (+ volume) |
| **Кэш / очередь брокер** | Railway Redis plugin (`REDIS_PRIVATE_URL`) | managed | `Redis` |
| **Объектное хранилище (видео/клипы)** | S3 / Cloudflare R2 (tusd пишет туда напрямую) | коммерч. | внешний |
| **Скретч-диск рендера** | Railway Volume `/work` на `ai-render-worker` ($0.15/GB/мес) | — | `ai-render-worker` |
| **Биллинг / выплаты** | `PaymentProvider` → **свой on-chain приёмник USDT TRC-20** (HD-кошелёк + TRON-узел/TronGrid + `tronweb`; без чужого процессора): предоплаченный USDT-баланс, PAYG $0.25/мин + подписка с лимитом минут; выплаты креаторам в USDT в P5. Stripe/ЮKassa убраны. | коммерч. | `web` + `payments-watcher` |

**Ключевой Railway-факт:** клиппинг-пайплайн (whisper+YOLO+ffmpeg) — **CPU-only, ~1.5–2.5 ГБ RAM/задача**, деплоится как обычный контейнер. **GPU-тяжёлое inpainting выносится на Replicate**, потому что Railway не имеет GPU. Все сервисы биндятся на `::`/`0.0.0.0` (dual-stack), приватная сеть через `*.railway.internal`, ссылки на БД/Redis через `_PRIVATE_` URL (нулевой egress).

---

## 3. Индекс суб-документов

| Док | Тема | Источник |
|---|---|---|
| [`01-COMPETITOR-EDGE.md`](./01-COMPETITOR-EDGE.md) | Рынок, attack surface, ров, GTM, pricing | `ad:competitor-edge` |
| [`02-OPENSHORTS-INTEGRATION.md`](./02-OPENSHORTS-INTEGRATION.md) | Извлечение `main.py`, swap Gemini→OpenRouter, реврейм, ad-banner hook | `dissect:openshorts` |
| [`03-RAILWAY-TOPOLOGY.md`](./03-RAILWAY-TOPOLOGY.md) | Сервисы, приватная сеть, volumes, healthcheck, `railway.json` | `rw:topology` |
| [`04-DESIGN-STACK.md`](./04-DESIGN-STACK.md) | Лендинг-шаблоны, motion-либы, GSAP/scroll, лицензии | `design:*` verifications |

---

## 4. ПОЧЕМУ МЫ ЛУЧШИЕ НА РЫНКЕ (ров)

На рынке существуют **три раздельных бизнеса**, и никто не владеет швом между ними:

| Слой | Кто играет | За что берут | Чего НЕ делают |
|---|---|---|---|
| **A. AI-нарезка (SaaS)** | Opus.pro, Klap, Vizard, Submagic | $15–39/мес, метрика по *исходным* минутам | НЕ монетизируют, НЕ связывают с рекламодателями, НЕ вставляют офферы. Чистый cost center. |
| **B. Армии нарезчиков (агентства)** | Whop, Vyro, Clipping LA | $2–8 CPM, агентства $2.5k–10k/мес | «Реклама» = ссылка в подписи. Никакого native-оффера в кадре, view-фрод. |
| **C. AI-вставка рекламы в кадр** | **Rembrand** (реальная угроза), Keek (patent-pending, не запущен) | CPM, креатор получает 75% net | Rembrand продаётся брендам (PepsiCo, L'Oréal), demo-gated, уходит в CTV. НЕ self-serve, НЕ генерит клипы, НЕ обслуживает длинный хвост. |

**Шов, которым владеет FlipHouse:** никто не сливает **A + B + C** в один self-serve цикл. Три структурных клина:

1. **Связываем cost center с revenue center.** У конкурентов слоя A — ежемесячный счёт. У нас тот же акт (генерация клипа) = момент монетизации. Причина пользоваться Opus — «вдруг завирусится»; причина пользоваться FlipHouse — «мне платят за клип, гарантированный пол + CPM-апсайд».

2. **Self-serve двусторонний маркетплейс для длинного хвоста, который Rembrand игнорирует.** Rembrand требует demo и гонится за PepsiCo. У нас — self-serve онбординг выплат для креатора с 5k подписчиков и DTC-бренда с бюджетом $500. Matching-движок (оффер ↔ тема/аудитория клипа через transcript-эмбеддинги) **и есть продукт**. Это и есть «убираем посредника»: без агентства, без 3-недельных переговоров, без армии нарезчиков.

3. **Native-вставка оффера в кадр, а не ссылка в bio.** Diffusion video inpainting (`DiffuEraser` + SAM2) размещает продукт/оффер *внутри кадра* — механика Rembrand, но автоматически на этапе генерации клипа и выбранная маркетплейс-матчем. Это технический ров.

**Компаундящиеся ров-фичи:**
- **Data-flywheel качества матчинга** — единственная компания с fused-данными клип-уровня + рекламодатель-уровня + перформанса. У Rembrand данные брендов; у Opus — данные клипов; только FlipHouse джойнит их.
- **Слой расчёта по verified-views** — решаем проблему №1 клиппинга (фрод >5%, «no view verification» = сигнал скама) через API-сверку просмотров TikTok/YouTube/IG до выплаты. Рана индустрии → ров доверия.
- **Brand-safety / consent-гейтинг** — авто-скрининг, какой рекламодатель попадает в чей кадр; FTC-дисклеймер встроен в пайплайн как несъёмная фича (а не afterthought).
- **Self-serve консоль рекламодателя** — именно то, что Rembrand прячет за «Request Demo». Self-serve под бюджеты <$1k — это позиционный ров.

**Pricing-клин:** креаторы — **бесплатно нарезают**, получают до **80% спенда рекламодателя** (бьём 75% Rembrand), мы зарабатываем на объёме + insertion-tech. Рекламодатели — CPM / per-accepted-clip, self-serve бюджет как Meta Ads. Структурно дешевле для креатора, чем любой инструмент слоя A (плоский ежемесячный счёт), и дешевле для рекламодателя, чем $300/UGC-видео + наценка агентства.

---

## 5. План сборки по фазам (под Railway-деплой)

### Phase 0 — Каркас и инфра (недели 0–2)
- Railway-проект: окружения `production` + `staging`, план Pro.
- Поднять сервисы: `web` (форк `ixartz/SaaS-Boilerplate` + `launch-ui` лендинг), `Postgres` (+volume), `Redis`.
- Приватная сеть: все биндятся на `0.0.0.0`/`::`, ссылки через `_PRIVATE_` URL.
- `railway.json` config-as-code: healthcheck `/api/health`, миграции в `preDeployCommand`, 2 реплики `web`.
- TRON testnet (Nile/Shasta) + TronGrid, Clerk auth.

### Phase 1 — Клиппинг-движок MVP (недели 2–5)
- Вендорить `mutonby/openshorts` → **только `main.py`** + `Dockerfile` + `hooks.py` + `fonts/`.
- Swap Gemini → OpenRouter (`get_viral_clips`, `main.py:794`, text→JSON, `response_format=json_object`).
- Вырезать hardcoded CTA из промпта (`main.py:55`).
- Развернуть `ai-render-worker` (CPU, ≥2 ГБ RAM, `MAX_CONCURRENT_JOBS=1`), Volume `/work`.
- tusd-сервис → R2/S3; `bullmq-worker` для оркестрации.
- API: `POST /clips` → `GET /clips/{job_id}` (мирроринг `app.py:run_job`).

### Phase 2 — Ad-insertion: баннер-оверлей (недели 5–8)
- `ad_banner.py` (клон `hooks.py:add_hook_to_video`): ffmpeg `overlay` после реврейма.
- Порядок пассов: реврейм → ad-banner → субтитры/hook.
- **FTC/ASA дисклеймер встроен как несъёмный оверлей** (требование ToS платформ).
- Консьерж-режим: вручную брокерим первые 50 сделок (concierge MVP), AI делает вставку+нарезку. Сидим обе стороны, тренируем matching на реальных accept/reject.

### Phase 3 — Native in-frame insertion (недели 8–14)
- Replicate-деплой `DiffuEraser` + `AutoSeg-SAM2` (GPU вне Railway).
- Пайплайн: SAM2 находит поверхность (стол/стена/экран) → DiffuEraser temporally-consistent вставка продукта.
- `ai-render-worker` вызывает Replicate API, поллит, склеивает результат, грузит в R2.
- ⚠️ Очистить лицензию `COCOCO`/Video-Inpaint-Anything (нет LICENSE) перед коммерцией — иначе только DiffuEraser+SAM2.

### Phase 4 — Self-serve маркетплейс (недели 14–22)
- Matching-движок: transcript-эмбеддинги ↔ offer-векторы. Auto-match + auto-insert.
- Консоль рекламодателя: бюджет + креатив + таргетинг (как Meta Ads).
- Креатор подключает соцсети, опт-инит клипы в пул.
- **Guaranteed-floor модель** (фикс per-accepted-clip + CPM-бонус) — убивает view-фрод-стимул.
- Niche-first: финансы/трейдинг ИЛИ фитнес/добавки ИЛИ SaaS/AI-тулзы (высокий CPM, DTC-бренды, длинный контент).

### Phase 5 — Trust-слой и масштаб (недели 22+)
- Verified-views settlement: API-сверка TikTok/YouTube/IG до выплаты.
- Brand-safety категорийные исключения, consent-гейтинг.
- Land-grab спенда слоя A: прямой питч против Opus («хватит платить $29/мес — нарезай бесплатно и получай деньги»).
- Масштаб реплик `ai-render-worker`, мульти-регион Railway, наблюдаемость (метрики/дашборды).

---

## 6. Топ-риски

| Риск | Суть | Митигация |
|---|---|---|
| **Лицензия SamurAIGPT** | `SamurAIGPT/AI-Youtube-Shorts-Generator` (★3.8k) — **нет лицензии** = all-rights-reserved. | Использовать **только как архитектурный референс**. Прод-нарезку строим на `openshorts` (MIT) — она уже покрывает пайплайн. Не копировать код SamurAIGPT. |
| **Нет GPU на Railway** | Diffusion-inpainting требует GPU; Railway его не предоставляет. | GPU-инференс (DiffuEraser/SAM2) **выносим на Replicate**. На Railway остаётся только CPU-пайплайн (whisper+YOLO+ffmpeg, ~2 ГБ RAM). Никаких GPU-шаблонов Railway. |
| **AGPL-репозитории** | YOLOv8 (Ultralytics) — **AGPL-3.0**: при сетевом использовании обязывает открыть исходники. `COCOCO`/Video-Inpaint-Anything — **нет LICENSE** вовсе. | Для YOLO: либо коммерческая лицензия Ultralytics, либо заменить детектор на MIT/Apache-альтернативу (YOLO используется только как fallback, когда лицо не найдено — заменимо). `COCOCO` — **не использовать в проде** без явного гранта; строить на DiffuEraser (Apache-2.0) + SAM2 (MIT). Адаптеры adrianhajdin/olivierlarose (no-license) — **только референс, не копировать**. |
| **Anti-block при публикации** | Авто-вставленная реклама без дисклеймера → TikTok/YouTube/Meta банят аккаунты. | **FTC/ASA-дисклеймер встроен в insertion-пайплайн как несъёмная фича** (Phase 2), а не опция. Категорийные исключения + consent-гейтинг (Phase 5). |
| **Rembrand — реальный конкурент** | Хорошо профинансирован ($68.5M, The Trade Desk + L'Oréal BOLD). Догонит insertion-tech. | Бьём не технологией вставки, а **self-serve + длинный хвост + бандл генерации клипа**. Это позиционный, а не технический бой. |
| **Cold-start маркетплейса** | Двусторонность убивает стартапы (chicken-and-egg). | **Concierge/агентство-first** (Phase 2): сами БУДЕМ нарезчик-агентством минус комиссия. Сидим обе стороны вручную, потом автоматизируем (Phase 4). |
| **Ephemeral-диск Railway** | Контейнеры эфемерны, клипы теряются. | Volume `/work` только для скретча рендера; финальные клипы → R2/S3 с возвратом URL. tusd пишет в объектное хранилище, не на volume (реплики не шарят диск). |

---

*Конец мастер-документа. Детали — в суб-документах 01–04.*
