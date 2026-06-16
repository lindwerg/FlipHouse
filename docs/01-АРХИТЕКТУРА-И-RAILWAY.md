# FlipHouse — Архитектура системы и развёртывание на Railway

> Документ №01. Полная системная архитектура FlipHouse: топология сервисов на Railway, GPU-стратегия, хранилище, очереди, FFmpeg-рантайм и карта «продуктовый слой → выбранный форк» с заметками по file-lift.

FlipHouse — это конвейер «длинное видео → вертикальные клипы (Shorts / Reels / TikTok)» с вшитыми баннерами и стилизованными субтитрами, поверх которого работает SaaS-биллинг (creator / advertiser) и маркетплейс офферов. Это greenfield: на момент проектирования в репозитории только лендинг. Решения ниже приняты декларативно и обоснованы исследованием.

---

## 0. Главные инварианты архитектуры (читать первыми)

Эти факты определяют всю топологию. Они не обсуждаются — на них опирается всё остальное.

1. **На Railway НЕТ GPU.** Это не опция тарифа, а отсутствие SKU. GPU-нагрузка (Whisper-транскрипция, ASD) выносится на внешних провайдеров (Replicate / Modal / fal) через webhook-паттерн. См. §3.
2. **Контейнеры Railway эфемерны.** Локальный диск исчезает при редеплое. Любое долгоживущее состояние — только в Postgres, Redis или объектном хранилище (R2). Railway Volume — это исключительно scratch-диск воркера, не durable storage. См. §4.
3. **FFmpeg-рантайм собирается сами, LGPL-only, CPU.** `jrottenberg/ffmpeg` нельзя использовать как есть (`--enable-gpl` тянет x264, `--enable-nonfree` делает бинарь нераспространяемым). H.264 — через `libopenh264`. См. §6.
4. **Идемпотентность по content-hash.** SHA-256 загруженного видео = и PK в Postgres-леджере, и `jobId` в BullMQ. Повторная загрузка тех же байтов переиспользует прошлый результат. См. §5.
5. **Защита внешней GPU-квоты — двухслойная.** `Queue.setGlobalConcurrency(N)` (Redis-enforced потолок на весь кластер) + `concurrency: 1` на воркер. Работает независимо от того, до скольких реплик Railway отмасштабирует воркер. См. §5.
6. **R2 — единственное объектное хранилище.** Нулевой egress решает: продукт «download/publish-heavy», R2 ~60× дешевле S3 на egress-доминантном профиле. См. §4.

---

## 1. Продуктовые слои и их форки (карта file-lift)

FlipHouse собирается из проверенных репозиториев. Для каждого слоя — выбранный источник, правовой статус и режим переноса (lift verbatim / rewrite / clean-room / discard).

| Продуктовый слой | Источник | Лицензия | Режим переноса | Что именно берём |
|---|---|---|---|---|
| **Выбор хайлайтов (LLM-«мозг»)** | `mutonby/openshorts` → `main.py` | MIT | **Lift + edit** | Весь движок `transcribe → get_viral_clips → cut → reframe`. Единственный LLM-вызов в clipping-пути — `get_viral_clips` (`main.py:794/803`), plain text→JSON, тривиально свопается на OpenRouter |
| **8-сигнальный virality-фреймворк** | `SamurAIGPT/AI-Youtube-Shorts-Generator` → `highlights.py` | **НЕТ (all rights reserved)** | **Clean-room** | НЕ копировать код. Реимплементировать дизайн: 8 ранжированных сигналов, chunking (1200s окна, 60s overlap, порог 1800s), dedupe (>50% overlap), `llm_fn` injection |
| **9:16 reframe + speaker-tracking** | `mutonby/openshorts` → `process_video_to_vertical` | MIT | **Lift verbatim** | `SmoothedCameraman` (L78), `SpeakerTracker` (L165), MediaPipe FaceDetection, YOLOv8n fallback, blur-pad general path |
| **Active Speaker Detection (точный)** | `Junhua-Liao/LR-ASD` → `Columbia_test.py` | (проверить) | **Wrap, не форкать** | Запускаем как есть → `tracks.pckl` + `scores.pckl`. Тонкий post-processor выдаёт `asd_frames.json` → `crop_keyframes.json`. **CUDA-required → выносится на GPU-провайдера** |
| **Стилизованные субтитры (karaoke)** | `unconv/captacity` | MIT | **Lift + patch** | Word-timestamps → MoviePy burn-in. **Обязательный патч**: `position` kwarg — no-op TODO; хардкод `text_y_offset = video.h//2` надо заменить на safe-zone-aware placement |
| **Баннер-оверлей (ad insertion)** | FFmpeg `overlay` + `enable='between(t,a,b)'` | (нативный FFmpeg) | **Build** | PNG/RGBA `overlay`, fade через `format=rgba,fade:alpha=1` на `-loop 1` входе. Прототип в openshorts `hooks.py:add_hook_to_video` (L171) |
| **SaaS-биллинг + auth + RBAC** | `nextjs/saas-starter` | MIT | **Lift + extend** | Кастомный JWT/bcrypt auth, Drizzle-схема, webhook/checkout. Биллинг — за абстракцией `PaymentProvider` → свой TRON on-chain приёмник (USDT TRC-20-баланс, `tronweb`; без чужого процессора; Stripe-код не используем). Расширяем: metered usage (per-clip / per-render / CPM) как наш ledger, роль creator/advertiser в Clerk `publicMetadata` |
| **Маркетплейс: атрибуция + комиссии** | `org-quicko/cliq` | **НЕТ (all rights reserved)** | **Clean-room (blueprint only)** | НЕ копировать код. Реимплементировать модель Link→Conversion→Commission, Function/Condition/Effect engine |
| **Маркетплейс: правила / бюджеты / кампании** | `medusajs/medusa` Promotion | MIT | **Adopt pattern** | Формы `PromotionRule(attribute, operator, values)` для eligibility и `CampaignBudget(limit, used)` для спенд-капов |
| **Каталог офферов + apply/match + payouts** | — | net-new | **Build** | Ни один репозиторий этого не даёт. Крупнейший build-кусок: payout/ledger/KYC (cliq останавливается на accrual, денег не двигает) |
| **Resumable upload** | `tus/tusd` (`tusproject/tusd`) | MIT | **Lift verbatim** | S3-multipart прямо в R2, hooks → hook-receiver |
| **Очереди / оркестрация** | `taskforcesh/bullmq` + `felixmosh/bull-board` | MIT | **Lift verbatim** | FlowProducer DAG, global concurrency, rate-limit, pause/resume |

### Правовые красные флаги (CRITICAL)

- **`SamurAIGPT/...` и `org-quicko/cliq` — без лицензии.** Default copyright = all rights reserved. Вендорить код **нельзя**. Оба используются строго как **референс-дизайн** и реимплементируются clean-room. Модель данных и поток событий не охраняются авторским правом — конкретный код охраняется.
- **OpenShorts `editor.py`/`saasshorts.py`/`thumbnail.py` — discard.** Они используют Gemini File API (video understanding) и Gemini image-gen, которых нет в OpenRouter. Это вторая причина их выбросить (первая — они не нужны для clipping-only).

---

## 2. Поток данных в конвейере (стадии и контракты)

Конвейер преимущественно линейный, но три стадии (`reframe`, `caption`, `banner`) — параллельные сиблинги после `score`. Контракты между стадиями (все имена полей прослежены к исходникам):

```
source.mp4 (в R2 ingest/)
   │
   ├─(A) ASR / транскрипция ───────────► word_segments.json
   │     faster-whisper shape:                [{start,end,words:[{word,start,end}]}]
   │     (внимание: captacity требует ВЕДУЩИЙ ПРОБЕЛ в каждом word)
   │
   └─(B) LR-ASD pipeline ──────────────► asd_frames.json (25fps frame units)
              │                                {fps, frame_w, frame_h, frames:[{frame,t,faces:[...]}]}
              │                                score = signed logit, порог 0 (НЕ probability!)
              └─(C) reframe planner ────► crop_keyframes.json
                                               EMA-сглаживание + min-hold 12 кадров (анти-whip-pan)
(D) reframe + crop ◄────────────────────────────┘ → 1080×1920.mp4
   │
(E) highlight select ◄── LLM (OpenRouter) — get_viral_clips: transcript → JSON
   │                       {shorts:[{start,end,title,hook,captions}], cost}
   │
(F) cut (ffmpeg) → per-clip 9:16
   │
(G) caption burn-in (PATCHED captacity) ◄── word_segments.json + safe_zones.json
   │
(H) ad-banner compositor ◄── safe_zones.json (banner strip)
   │
   ▼
final_9x16_with_captions_and_ad.mp4 (в R2 clips/)
```

**Порядок наложения (идемпотентные ffmpeg-пассы):** `reframe → banner → captions`. Баннер первым — чтобы субтитры были поверх рекламы. **Safe-zones — единый source of truth**: `caption_band` ⊂ `content_safe` и `caption_band ∩ banner = ∅` (CI-проверяемый инвариант: `1180+420=1600 ≤ 1640`). Reframe обязан держать лицо спикера выше `banner.y`.

---

## 3. GPU-стратегия (на Railway нет GPU)

Весь GPU-конвейер — цепочка коротких bursty-джобов, вызываемых из Node/BullMQ-воркера. Этот паттерн вознаграждает per-second биллинг + нативные async-вебхуки + готовый каталог моделей.

### Решение по провайдерам

| Стадия | Провайдер | Обоснование | Стоимость |
|---|---|---|---|
| **Транскрипция (Whisper)** | **fal Wizper** (primary) | $0.50 / 1000 audio-min, ~250× realtime, нативный `webhookUrl` | ~$0.0005/мин |
| ↳ fallback 1 | Replicate `incredibly-fast-whisper` | public model = no cold-start charge | ~$0.003/мин |
| ↳ fallback 2 (degraded) | faster-whisper CPU на Railway | блокирует воркер (~3× realtime large-v3); только `small`/`medium` при тотальном отказе GPU | $0 GPU |
| **ASD + reframe (кастом)** | **Modal** (primary) | bring-your-own-container для TalkNet ASD + YOLO/MediaPipe. Нет готовой public-модели для true ASD + face-tracked 9:16 | ~$0.03–0.10 / 3-мин видео |
| ↳ fallback | Replicate `luma/reframe-video` | generative reframe, ≤30s/720p — не замена landmark-точному ASD на long-form | — |

**Итог по стоимости GPU:** ~$0.03–0.10 на 3-минутное исходное видео, доминирует ASD/reframe-плечо. Транскрипция почти бесплатна.

### Паттерн вызова (BullMQ ⇄ webhook)

Жёсткое правило: **никогда не блокировать BullMQ-воркер ожиданием GPU.** Submit-and-park: воркер отправляет джобу провайдеру, сохраняет `provider_request_id → bullmq_jobId` в Redis, переходит в `waiting-on-callback`. Отдельный HTTP-сервис (`webhook-receiver`, не воркер) принимает колбэк, верифицирует подпись (Replicate HMAC из `/v1/webhooks/default/secret`), находит джобу по id, продвигает state-machine.

Требования: идемпотентные хендлеры (вендоры ретраят, дедуп по prediction id), per-step fallback по цепочке провайдеров, верификация подписи **до** мутации состояния.

> **Caveat:** Replicate куплен Cloudflare (2026) — Modal держать как реальный fallback, не бумажный. Для ASD нет public one-call модели → это custom-код на Modal, бюджетируем инженерное время, не только GPU-доллары.

---

## 4. Хранилище и доставка

### Объектное хранилище: Cloudflare R2 (единственное)

Решающий фактор — **нулевой egress**. Профиль FlipHouse egress-доминантный («клипы много качают/публикуют»). На 2 TB at-rest + 20 TB/мес egress: R2 ≈ $30/мес, S3 ≈ $1826/мес, B2 ≈ $154/мес (3× egress-cap ломает B2 на publish-heavy). R2 ~60× дешевле S3.

**Railway Volume дисквалифицирован как durable storage** жёсткими ограничениями: один volume на сервис, **реплики несовместимы с volume**, нельзя шарить между сервисами, потолок 1 TB, плюс $0.05/GB Railway egress. Volume — только scratch-диск ffmpeg-воркера.

### Раскладка bucket (один bucket, prefix-driven lifecycle)

```
fliphouse-media/
├── ingest/{uploadId}/        # tusd пишет сюда (S3 multipart). Transient.
│                             #   lifecycle: abort incomplete MPU > 1d; delete > 2d
├── intermediate/{jobId}/     # ffmpeg-артефакты, proxies, segments, thumbs. Transient.
│                             #   lifecycle: delete > 3d
└── clips/{clipId}/           # финальные клипы + постеры. Durable, hot.
    ├── master.mp4            #   lifecycle: Standard → Infrequent Access после 90d
    ├── 720p.mp4 / 1080p.mp4
    └── poster.jpg
```

### tusd → R2 (критичная деталь)

R2 требует **`-s3-min-part-size == -s3-part-size`** (все multipart-части кроме последней одинакового размера). Для крупного видео поднять обе до 64–128 MiB. Креды R2 (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, `AWS_REGION=auto`) — через Railway env, никогда не в коде.

### Доставка

- **Приватные клипы** → presigned GET URL (`@aws-sdk/s3-request-presigner` на R2-endpoint), TTL ~15 мин, подписываются server-side.
- **Публичные/опубликованные клипы** → custom-domain через Cloudflare CDN: edge-кэш, не трогают origin и счёт.

---

## 5. Очереди и оркестрация (BullMQ)

**Решение: BullMQ (MIT) + bull-board (MIT) + Railway Redis.** НЕ Trigger.dev (4–5-сервисная платформа, операционно тяжело) и НЕ self-hosted Inngest (SSPL сегодня, не permissive). Все нужные примитивы есть в OSS BullMQ: per-worker concurrency, **per-queue global concurrency** (GPU-клапан), worker rate-limit, manual `rateLimit()` + `RateLimitError` для 429, per-job retries с backoff, pause/resume для backpressure.

### Flow-DAG (children-run-first)

BullMQ Flow моделирует зависимости как дерево: дети выполняются первыми, родитель — последним. Гибрид: вложенная цепочка где есть истинная зависимость, параллельные сиблинги где можно fan-out.

```
publish                              ← parent (выполняется ПОСЛЕДНИМ; queue: publish)
└─ store                             ← child  (queue: cpu)
   └─ [banner, caption, reframe]     ← 3 ПАРАЛЛЕЛЬНЫХ сиблинга (queue: cpu)
      └─ score                       ← child  (queue: gpu-score)
         └─ asr                      ← child  (queue: gpu-asr)
            └─ transcode             ← leaf, выполняется ПЕРВЫМ (queue: cpu)
```

`store` входит в `waiting-children`, пока все три сиблинга не завершатся, затем `getChildrenValues()` отдаёт ему три artifact-ref. Это и есть реальный выигрыш Flows над ручной цепочкой.

### Очереди и их гарды

| Queue | Стадии | Worker | concurrency/реплика | Global cap | Rate-limit |
|---|---|---|---|---|---|
| `transcode` | transcode | cpu-worker | 4 | — | — |
| `gpu-asr` | asr | gpu-asr-worker | **1** | `setGlobalConcurrency(2)` | — |
| `gpu-score` | score | gpu-score-worker | **1** | `setGlobalConcurrency(2)` | — |
| `cpu` | reframe, caption, banner, store | cpu-worker | 8 | — | — |
| `publish` | publish | cpu-worker | 4 | — | `{max:30, duration:1000}` |
| `orchestrate` | Flow parent | orchestrator-worker | 16 | — | — |

**GPU-защита двухслойная:** per-worker `concurrency:1` (один GPU-джоб на процесс, нет VRAM-contention) **плюс** `setGlobalConcurrency(2)` (Redis enforce ≤2 джоба на весь кластер, даже если Railway отмасштабирует до 10 реплик). Docs подтверждают: worker concurrency не переопределяет global — global это потолок. Это единственный способ не дать автомасштабированию переподписать фиксированный GPU-пул.

### Failure-семантика

- `failParentOnFailure: true` на GPU-стадиях и `store`/`reframe`/`caption` — упавший transcode/ASR/score должен завалить весь flow (публиковать незачем).
- `ignoreDependencyOnFailure: true` только на косметических стадиях (`banner` опционален) — flow всё равно публикуется, пропущенное смотрим через `getIgnoredChildrenFailures()`.
- `attempts`/`backoff` per-stage: GPU мало попыток (дорого), CPU больше.

### Идемпотентность по content-hash

tusd даёт upload ID (random) + `.info` sidecar — **не** content-hash. Хеш считается: либо клиент стримит SHA-256 при загрузке и шлёт как tus-метаданные (`Upload-Metadata: sha256 ...`), либо server-verified (tiny `hash`-джоб стримит R2-объект). `jobId = flow-${hash}` — BullMQ дедупит, добавление существующего jobId = no-op. (Префикс через `-`, НЕ `:` — двоеточие нелегально в кастомном jobId BullMQ: оно ломает разбор Redis-ключа `bull:<queue>:<jobId>`. Каждый узел flow получает детерминированный `${stage}-${hash}`. См. `packages/shared/src/hash/content-hash.ts`.) Плюс Postgres-леджер:

```
upload_ledger(content_hash PK, first_upload_id, flow_job_id, status, result_url, created_at)
```

Логика hook-receiver: `INSERT ... ON CONFLICT (content_hash) DO NOTHING RETURNING` — если строки нет, контент уже в обработке → skip enqueue, вернуть existing `result_url`.

### Прогресс на фронт: SSE, не WebSocket

Однонаправленный server→client прогресс. Воркеры эмитят `job.updateProgress(pct)` + публикуют в **Redis pub/sub по jobId**. SSE-эндпоинт на API подписан на канал. Pub/sub (не in-memory EventEmitter) **обязателен**, т.к. у API несколько реплик и любая должна обслужить любого клиента.

### tusd → BullMQ: нужен посредник

tusd hooks **не** «энкьюят BullMQ» нативно — tusd HTTP-hook просто POST'ит на ваш эндпоинт. Нужен тонкий **hook-receiver** (Node), владеющий `FlowProducer` и транслирующий `post-finish` POST в `flowProducer.add(...)`. Там же живёт идемпотентность.

---

## 6. FFmpeg-рантайм (LGPL-only, CPU)

### Решение: собирать свой образ, НЕ jrottenberg/ffmpeg

`jrottenberg/ffmpeg:latest` нарушает требования: `--enable-gpl` (тянет GPL-x264), `--enable-nonfree` (libfdk-aac → бинарь нераспространяем). Два хард-блокера.

**Энкодер:** LGPL запрещает x264. Выбор — **`libopenh264`** (Cisco, BSD-2-Clause) для H.264 + нативный AAC. TikTok/Reels/Shorts ждут H.264/AAC для совместимости. Если quality-per-bit openh264 окажется неприемлем — единственный чистый путь оставить x264 — коммерческая лицензия x264 (это бизнес-решение, не техническое; молча GPL-x264 не шипить).

### Dockerfile (multi-stage, LGPL-subset)

Сборка из исходников FFmpeg 7.1 с caption-стеком. Ключевые `configure`-флаги (БЕЗ `--enable-gpl`, `--enable-nonfree`, `--enable-version3`):

```
--enable-fontconfig --enable-libass --enable-libfreetype --enable-libfribidi \
--enable-libharfbuzz \      # полный стек стилизованных субтитров (+ shaping не-латиницы)
--enable-libopenh264 \      # LGPL-safe H.264
--enable-libopus --enable-libvorbis --enable-libvpx --enable-libdav1d \
--enable-openssl --disable-static --enable-shared
```

В runtime-стейдж ставятся `libass9 libfreetype6 libfontconfig1 libfribidi0 libharfbuzz0b`, `fonts-noto-cjk` (мультиязычная аудитория), **бренд-шрифт FlipHouse** + `fc-cache -f` (детерминированный резолв шрифтов, без runtime-загрузки). Воркер (queue consumer) живёт в том же образе и `exec`'ает ffmpeg локально.

### Тюнинг производительности (CPU, много коротких клипов)

- **Threading — главный рычаг.** НЕ давать одному клипу все ядра (скейлинг сублинейный после ~4 тредов, libass сериализуется). Запускать **N параллельных ffmpeg, каждый на 2 треда** (`-threads 2 -filter_threads 2`). Concurrency очереди = `floor(vCPU / 2)`.
- **Rate control:** ~6–8 Mbps CBR/VBV для 1080×1920, `-g 48` (keyframe каждые 2с при 24fps). Без 2-pass (бессмысленно для клипов <60с).
- **Один filtergraph на клип:** `scale=1080:1920:force_original_aspect_ratio=...,setsar=1` → banner `overlay` → `ass=subs.ass`. Не передекодировать исходник на каждый caption-стиль.
- **Keyframe pre-cut:** для fan-out «длинное видео → много клипов» делать быстрый stream-copy keyframe pre-cut (`-c copy`), затем re-encode только оставленных сегментов. Избегает декодирования всего исходника N раз.
- `-movflags +faststart` для web/social доставки.

### Безопасность баннер-движка (filtergraph injection — реальна)

Наивная интерполяция недоверенных offer-данных в filter-строку позволяет `,;:=[]'\%` вырваться из параметра и инжектить фильтры (доказано: `overlay=x=0,split` ломает граф). Спека митигации:

1. **Clamp/whitelist каждый числовой вход** до интерполяции (координаты, длительности, padding → parse to int, reject non-numeric, clamp в `[0, dimension]`).
2. **Никогда не класть недоверенный graph-текст в shell/`-filter_complex` арг.** Использовать **`-filter_complex_script FILE`** — граф читается из файла, минуя shell.
3. **Для текста** — `drawtext=textfile=FILE` (грузит сырой текст литерально) или, лучше, рендерить текст → PNG out-of-band и `overlay`. `position` — enum-only из фиксированной таблицы, никогда сырое выражение от пользователя. `fontfile` валидировать по allowlist.

### Стоимость рендера (Railway, проверено)

CPU $0.000463/vCPU-мин, RAM $0.000231/GB-мин. Клип 45с, openh264 ~veryfast-class, ~30с wall-clock на 2 vCPU + 1.5 GB ≈ **$0.00064/клип** ≈ $0.0051/видео (8 клипов). 100k клипов/мес ≈ **$64/мес compute** — sub-cent, тривиально против egress/storage. Реальные драйверы стоимости: bandwidth (→ R2/CDN) и idle-время воркера (→ scale-to-zero на queue depth между бёрстами).

---

## 7. Топология сервисов на Railway

**Один проект, окружения `production` + `staging`, тариф Pro.** Приватная сеть изолирована per-environment (staging↔prod не пересекаются). Все сервисы биндятся на `::`/`0.0.0.0` (legacy-окружения IPv6-only). Internal-трафик по `*.railway.internal` — бесплатный, шифрованный, **runtime-only** (не на build). Reference-переменные `${{Service.VAR}}`, приватные URL для Postgres/Redis.

### Компонентная диаграмма

```
                              ИНТЕРНЕТ (HTTPS)
                                    │
              ┌─────────────────────┼──────────────────────┐
              │                     │                      │
       ┌──────▼───────┐      ┌──────▼───────┐       browser uploads
       │  web         │      │  tusd        │◄──── (resumable PUT/PATCH)
       │  Next.js     │      │  upload edge │
       │  public+HC   │      │  public+HC   │
       │  replicas:2  │      │  replicas:1-3│──┐ S3-multipart
       └──┬───┬───┬───┘      └──────┬───────┘  └──────────────┐
          │   │   │                 │ -hooks-http             │
          │   │   │   ┌─────────────┘ (post-finish)           ▼
          │   │   │   │                              ┌─────────────────┐
          │   │   │   ▼                              │  Cloudflare R2   │
          │   │ ┌─▼──────────────┐                   │  fliphouse-media │
          │   │ │ hook-receiver  │ владеет           │  (EXTERNAL,      │
          │   │ │ FlowProducer + │ FlowProducer      │   не Railway)    │
          │   │ │ идемпотентность│                   │  ingest/         │
          │   │ └─┬──────────────┘                   │  intermediate/   │
          │   │   │ flowProducer.add()               │  clips/          │
          │   │   ▼                                  └─────────▲────────┘
   private│   │ ┌──────────┐  ┌──────────┐                     │
          │   └►│  Redis   │◄─┤ webhook- │                     │
          │     │ BullMQ + │  │ receiver │◄── GPU-провайдеры   │
          │     │ pub/sub  │  │ (HMAC    │    колбэки          │
          │     │ no volume│  │  verify) │    (fal/Replicate/  │
          │     └────▲─────┘  └──────────┘     Modal)          │
          │          │                                          │
     ┌────▼─────┐    │ enqueue / consume                        │
     │ Postgres │    │                                          │
     │ леджер + │    ├──────────────┬──────────────┬───────────┤
     │ dedupe   │    │              │              │           │
     │ volume   │ ┌──▼─────────┐ ┌──▼──────────┐ ┌─▼────────┐ │
     │ replicas:1│ │ cpu-worker │ │gpu-asr-     │ │gpu-score-│ │
     └──────────┘ │ transcode/ │ │worker       │ │worker    │ │
                  │ reframe/   │ │ submit→fal  │ │ submit→  │ │
                  │ caption/   │ │ (park)      │ │ Modal    │ │
                  │ banner/    │ │ conc:1      │ │ (park)   │ │
                  │ store/     │ │ global:2    │ │ conc:1   │ │
                  │ publish    │ │ NO GPU здесь│ │ global:2 │ │
                  │ FFmpeg     │ └─────────────┘ └──────────┘ │
                  │ /work vol  │                               │
                  │ replicas:N │   ┌──────────────────┐        │
                  └─────┬──────┘   │ orchestrator-     │        │
                        │          │ worker (Flow      │        │
                        └─ читает/пишет R2 ◄───────────┼────────┘
                                   │ parent, min:1     │
                                   └──────────────────┘
                  ┌──────────────┐
                  │ bull-board   │ read-only дашборд за auth, все очереди
                  │ web, no vol  │
                  └──────────────┘
```

### Сервисы (по одному, с обоснованием)

| Сервис | Public | Volume | Replicas | Назначение |
|---|---|---|---|---|
| **web** (Next.js) | ✅ домен + HC `/api/health` | нет | 2 (HA, zero-downtime) | SaaS-фронт, API, status, SSE-прогресс. Stateless → состояние в PG/Redis. Миграции `preDeployCommand` в runtime |
| **tusd** | ✅ домен + HC `/metrics` | нет (S3-backend) | 1–3 | Resumable upload edge. State в R2 → безопасно скейлить, sticky-сессии не нужны |
| **hook-receiver** | private HTTP | нет | 1+ | Владеет `FlowProducer`, идемпотентность (ON CONFLICT + jobId). Транслирует tusd post-finish → Flow |
| **webhook-receiver** | ✅ домен (GPU-колбэки) | нет | 1+ | Принимает колбэки fal/Replicate/Modal, HMAC-verify, продвигает state-machine. Отдельно от воркеров |
| **Postgres** | private | ✅ (template) | 1 (single-writer) | Леджер, dedupe-таблица, биллинг, маркетплейс. **Не скейлить горизонтально** (multi-mount заблокирован) |
| **Redis** | private | нет (ephemeral) | 1 | BullMQ broker + pub/sub + кэш. Джобы re-enqueueable → producers идемпотентны |
| **cpu-worker** | private | ✅ `/work` (scratch) | N (масштаб на burst) | transcode/reframe/caption/banner/store/publish. FFmpeg + remote-inference client. Brief downtime на редеплое (volume) |
| **gpu-asr-worker** | private | нет | 1 (+ global:2) | Submit→fal, park. НЕТ GPU на самом Railway — только оркестрация |
| **gpu-score-worker** | private | нет | 1 (+ global:2) | Submit→Modal (custom ASD), park |
| **orchestrator-worker** | private | нет | **min:1** | Flow parent. **Нельзя scale-to-zero** — иначе parent в `waiting-children` не продвинется |
| **bull-board** | ✅ за auth | нет | 1 | Read-only дашборд очередей |

### Wiring приватной сети

| From → To | Адрес |
|---|---|
| web → Postgres | `${{Postgres.DATABASE_PRIVATE_URL}}` |
| web → Redis | `${{Redis.REDIS_PRIVATE_URL}}` |
| tusd → hook-receiver | `http://${{hook-receiver.RAILWAY_PRIVATE_DOMAIN}}:8080/tusd-hooks` |
| воркеры → Redis/PG | приватные URL (reference) |
| воркеры → R2 | внешний (S3 API, R2-endpoint) |
| browser → web, tusd, webhook-receiver | публичные HTTPS-домены |

### Оценка стоимости (Pro, $20 база вкл. $20 usage)

| Сервис | Реплики | RAM | vCPU | Volume | $/мес |
|---|---|---|---|---|---|
| web | 2 | 1 GB | 0.6 | – | ~$22 |
| Postgres | 1 | 1 GB | 0.5 | 25 GB | ~$19 |
| Redis | 1 | 0.5 GB | 0.25 | – | ~$10 |
| tusd | 1 | 0.25 GB | 0.2 | – | ~$6.5 |
| cpu-worker | 1 | 2 GB burst | 1.0 burst | 75 GB | ~$31 + burst |
| gpu-*/orchestrator/hook/webhook | 1 each | ~0.5 GB | ~0.3 | – | ~$30 |

**Production starter: ~$100–140/мес** (база + usage), доминирует cpu-worker RAM/CPU при рендере + его volume. Рычаги: scale-to-zero cpu-worker между джобами (idle → только volume ~$11/мес); инференс на fal/Replicate держит воркер CPU-light; egress только публичный → через R2/CDN, не Railway egress ($0.05/GB).

---

## 8. Сводка решений

- **GPU:** на Railway нет → fal Wizper (транскрипция) + Modal (custom ASD) + Replicate (fallback), submit-and-park через webhook-receiver. Никогда не блокировать BullMQ-воркер.
- **Хранилище:** R2 — единственное (нулевой egress, ~60× дешевле S3). Railway Volume — только scratch на cpu-worker.
- **Очереди:** BullMQ + bull-board + Railway Redis. Flow-DAG (children-first, параллельные reframe/caption/banner). GPU-защита = `setGlobalConcurrency` + `concurrency:1`. Идемпотентность = content-hash как PK и jobId.
- **FFmpeg:** свой LGPL-образ (libopenh264, не x264), CPU, N×2-тред параллелизм, `-filter_complex_script` против injection.
- **Форки:** lift verbatim (openshorts reframe, captacity, tusd, bullmq, saas-starter), clean-room (SamurAI highlights, cliq — оба без лицензии), adopt-pattern (Medusa Promotion), build (каталог офферов, payouts/ledger/KYC, banner-движок).
- **Топология:** 11 сервисов, 1 проект, prod+staging, ~$100–140/мес старт.
