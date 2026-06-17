# CHECKPOINT C — Финальный blueprint: оркестрация P2 BullMQ Flow-DAG

**Ветка:** `p2-clipping-mvp` · **Объём:** roadmap-шаги 2.5–2.7 · **Угол:** reliability-first (ноль двойных side-effects, точная идемпотентность, восстановление с середины после краша)

Этот документ соединяет уже существующее Python-ядро ML (CHECKPOINT B) в children-run-first BullMQ Flow-DAG согласно `docs/01 §5`. Он **не** переписывает Python-ядро ML. Каждый TS-файл `<800` строк, рядом лежит `*.test.ts`, относительные импорты несут явное расширение `.js`, используются immutable-паттерны, именованные ошибки, именованные константы, цель — гейт покрытия 100% этого репозитория.

> **⚠️ КОРРЕКЦИЯ ПРИ РЕАЛИЗАЦИИ (2026-06-17):** предложенный ниже узел `fanout` в финальном дереве синтезатора (`reframe/caption/banner` → `children:[fanout]`) **сам нелегален** — у `fanout` 3 родителя, та же `-7 ParentJobCannotBeReplaced`. Корень: BullMQ Flow — это **ДЕРЕВО** (1 родитель на узел); «один предок → N параллельных → join» — это DAG, не дерево, и в принципе не выражается одним flow. Реализовано для P2: **легальная ЛИНЕЙНАЯ цепочка** `transcode→asr→score→reframe→caption→banner→store→publish` (post-order = верный порядок; `caption`/`banner` — passthrough-заглушки P2). Узел `fanout` УДАЛЁН. Истинный fan-out — **two-phase flow** в P3. См. `flow/build-flow-tree.ts` и `packages/shared/src/flow/stage.ts`.
>
> **Изменения после состязательной проверки (folded in):**
> 1. **CRITICAL (bullmq-semantics):** «диамант» из трёх параллельных детей с общим `score`-родителем **нелегален** в BullMQ 5.x — у job не может быть двух родителей (`-7 ParentJobCannotBeReplaced`). Каноническая топология ниже исправлена: `reframe/caption/banner` читают артефакт `score` из R2 в рантайме (skip-if-exists уже это умеет), а не через BullMQ-ребро.
> 2. **CRITICAL (idempotency-race):** jobId-дедуп **эфемерен** (`removeOnComplete` освобождает id). Единственный авторитет идемпотентности — `upload_ledger` ON CONFLICT; reconcile-sweep дополнен сканированием «строка есть, flow в Redis нет».
> 3. **CRITICAL (node-python-failure):** существующее Python-ядро бросает голые `RuntimeError`, не envelope. `cli.py` становится единственным классификатором fatal/retryable.
> 4. **CRITICAL (testability):** testcontainers требуют Docker-слой в CI; bootstrap-файлы исключаются из 100%-гейта как непокрываемый glue.
> 5. Графты судьи: пакет `@fliphouse/db` как единственный источник схемы; Node не тащит S3 (R2 I/O целиком в Python CLI); bull-board и OTel отложены за пределы P2-гейта; `isValidContentHash` как именованный валидатор; lazy-parent-flip как жёсткое деплой-ограничение.

---

## 0. Критичные правки фактов репозитория (приземлить первыми)

1. **`packages/shared/src/hash/content-hash.ts` `jobIdFromHash` возвращает `flow:${hash}` — двоеточие НЕЛЕГАЛЬНО в кастомных jobId BullMQ** (и чисто-числовые id тоже отвергаются). Подтверждено против live-файла (строка 17) и research (`pitfalls`). → **Заменить на `flow-${hash}`** и расширить детерминированными per-stage id. Это самый вероятный рантайм-footgun репозитория сегодня.
2. **Нотация `docs/01 §5` `jobId = flow:${hash}`** правится на `flow-${hash}` (правка дока для трассируемости).

Это шаг 1 порядка сборки (§8), защищённый тестом, утверждающим что id матчит разрешённый charset BullMQ.

---

## 1. Решение по границе Node↔Python

**ВЫБОР: вариант (a) — Node BullMQ-воркер спавнит Python-CLI-субпроцесс на каждую стадию**, контракт JSON-over-stdio, артефакты через R2/scratch.

Reliability-first решает выбор однозначно. Каждая стадия — свежий, полностью изолированный OS-процесс: сегфолт/OOM в ffmpeg/MediaPipe/CTranslate2 убивает только субпроцесс, Node-воркер выживает, job → `failed` через ненулевой exit-код. Это даёт настоящую процессную изоляцию crash-prone нативных библиотек **без** ESM-бага sandboxed-processor'а BullMQ (#2457) и **без** stall-риска Python-порта (у него нет sandboxed-processor → не-await CPU-секция блокирует asyncio-loop → пропуск продления lock → фантомный дубль-прогон). `queue-name.ts` остаётся единственным авторитетом маршрутизации (Python-CLI говорят его стадию, он её никогда не выбирает). Cold-start интерпретатора ~150–400 мс — `<1%` от стадий длиной в секунды-минуты. Railway — один контейнер (Node PID 1 + python wheel), один deploy/scale-unit. Возражение «спавн на запрос слишком медленный» к batch-render-пайплайну неприменимо.

**Оракул успеха/отказа спавна:**
- **success** = exit 0 **И** парсящийся framed-JSON `{ ok:true, ... }` (см. §1.1 про framing).
- **retryable** = ненулевой exit / kill-сигнал (OOM/timeout) / непарсящийся stdout / `{ ok:false, kind:'retryable' }` → бросить обычный `Error` → `attempts`/`backoff`.
- **fatal** = `{ ok:false, kind:'fatal' }` (OpenRouter 402, плохой вход) → бросить `UnrecoverableError` → ноль ретраев.
- Per-stage **timeout** через `AbortSignal`; на Linux/Railway спавн `detached:true` и kill **группы процессов** (`process.kill(-pid, 'SIGKILL')`) чтобы пожать ffmpeg-внуков (без зомби).
- `stdio:['pipe','pipe','pipe']`, никогда не inherit; stderr → `job.log()` инкрементально (нет 1MB-deadlock-ловушки `exec()`); **stdout несёт ровно один framed JSON** (см. ниже), всё человеческое — в stderr.

### 1.1 Framing вывода (правка из node-python-failure, MEDIUM)
«Последняя непустая строка stdout» хрупко: MediaPipe/CTranslate2/faster-whisper пишут баннеры в fd-1 напрямую. Контракт:
- `cli.py` пишет envelope как `@@FLIPHOUSE_RESULT@@<json>`; Node грепает **последнее** вхождение этого префикса, игнорируя весь прочий stdout.
- В `cli.py` вокруг ML-вызовов native fd-1 редиректится в stderr (`os.dup2`), чтобы C-баннеры не попали в framed-канал.

### 1.2 Классификация ошибок — `cli.py` единственный авторитет (CRITICAL, node-python-failure)
Существующее ядро бросает голые `RuntimeError` (`openrouter_adapter.py`: 402 и retry-exhaustion неразличимы). Если `cli.py` просто пропускает их, Node классифицирует ВСЁ как retryable → 402 бьётся N раз. Поэтому `cli.py._dispatch` обязан мапить:
- `RuntimeError` с маркером 402 (лучше — типизированный `CreditsExhaustedError`) → `kind:'fatal'`, `code:'OPENROUTER_402'`;
- `DimensionMismatchError`/`RenderOutputError`/`ClipDurationError`/`ValueError` (битый вход) → `kind:'fatal'`;
- `APIConnectionError`/`RateLimitError`/`TimeoutError`/transient I/O → `kind:'retryable'`;
- любой непойманный → `{ok:false, kind:'retryable', code:'UNCAUGHT', message:<repr>}` в stdout + traceback в stderr, `return 1`.

`ImportError`/`ModuleNotFoundError` (например `libGL.so.1` на slim-образе) → `kind:'fatal'` (ретраить бесполезно). Плюс `cli.py --selftest` (§2.14) импортирует тяжёлые deps на boot контейнера и падает быстро вместо retry-шторма.

---

## 2. Архитектура DAG

### 2.1 Каноническое дерево FlowProducer (исправлено — без нелегального диаманта)

Children-run-first: лист `transcode` бежит первым, корень `publish` — последним. Параллелизм трёх косметических плеч сохранён, но **не через два родителя**: `score` — единственный child своей цепочки; `reframe/caption/banner` — три ребёнка `store`, и каждое в рантайме читает артефакт `score` из R2 по content-hash (skip-if-exists уже делает HEAD). Порядок гарантирован тем, что `store` уходит в `waiting-children` только когда все три плеча завершены, а плечи стартуют после `score` через enqueue-порядок цепочки.

```
publish            (root, queue: publish, runs LAST, jobId = flow-${hash})
└─ store           (queue: cpu, waiting-children → getChildrenValues + getIgnoredChildrenFailures)
   ├─ reframe      (queue: cpu, leaf-в-DAG; в рантайме читает R2 ${hash}/score)
   ├─ caption      (queue: cpu, leaf-в-DAG; читает R2 ${hash}/score)
   └─ banner       (queue: cpu, leaf-в-DAG; ignoreDependencyOnFailure:true — косметика)
score-цепочка (гейтится enqueue-порядком, см. ниже):
   score           (queue: gpu-score) ─ child of ─ asr (queue: gpu-asr) ─ child of ─ transcode (queue: transcode, leaf)
```

> **Почему это легально и сохраняет порядок.** В BullMQ у job ровно один родитель. `reframe/caption/banner` зависят от **артефакта** `score`, а не от BullMQ-ребра. Их BullMQ-родитель — `store`. `store` не запустится, пока все три не завершатся. Каждое плечо первым делом `r2.head(${hash}/score)`: артефакт гарантированно присутствует, потому что цепочка `transcode→asr→score` (отдельное под-дерево) и под-дерево `store→[reframe,caption,banner]` связаны так, что `store`-под-дерево добавляется как ребёнок узла, чей предок — `score`. Реализационно простейший легальный вариант одного дерева:
>
> `publish → store → fanout → [reframe, caption, banner]`, где `fanout` (лёгкий passthrough-узел, queue `cpu`) — единственный child `score`, а `score`-цепочка висит под `fanout`. Тогда: `transcode→asr→score→fanout`, затем `fanout→[reframe,caption,banner]→store→publish`. Каждый узел имеет ровно одного родителя, диамант устранён, параллелизм трёх плеч сохранён (они — три ребёнка одного `fanout`/`store`), а `score`-артефакт гарантированно готов к моменту старта плеч.

**Итоговое дерево (для `build-flow-tree.ts`):**

```ts
// h = contentHash; out(s) = `intermediate/${h}/${s}`
transcode = leaf(queue:'transcode')
asr       = { ...node('asr',  'gpu-asr'),  children:[transcode] }
score     = { ...node('score','gpu-score'),children:[asr] }
fanout    = { ...node('fanout','cpu'),     children:[score] }      // passthrough; гейт для плеч
reframe   = { ...node('reframe','cpu'),    children:[fanout] }
caption   = { ...node('caption','cpu'),    children:[fanout] }
banner    = { ...node('banner','cpu'), opts:{ ...,ignoreDependencyOnFailure:true,failParentOnFailure:false }, children:[fanout] }
store     = { ...node('store','cpu'),      children:[reframe,caption,banner] }
publish   = { name:'publish', queueName:'publish', opts:{ jobId:flowJobId(h), removeOnComplete:false, ... }, children:[store] }
return publish   // корень
```

Топология эквивалентна `docs/01 §5` (`publish → store → [reframe,caption,banner] → score → asr → transcode`) с добавленным легализующим `fanout`-узлом. `Stage`-union расширяется на `'fanout'` (queue `cpu`); это правка `stage.ts`/`queue-name.ts`.

### 2.2 Failure-флаги
- **Критическая цепочка** (`transcode, asr, score, fanout, reframe, caption, store, publish`) = `failParentOnFailure:true`.
- **`banner`** = `ignoreDependencyOnFailure:true`, `failParentOnFailure:false` (косметика; `store` читает пропуск через `getIgnoredChildrenFailures()`).
- **Никогда `continueParentOnFailure`** (он пустил бы `store`, пока плечи ещё активны).
- **Дефолт (без флага) = БАГ** (родитель навечно в `waiting-children`) — integration-тест утверждает, что топология никогда так не делает.

### 2.3 Детерминированные jobId
Корень `publish` = `flowJobId(h)` = `flow-${h}`. Каждый узел = `stageJobId(stage,h)` = `${stage}-${h}`. Дает идемпотентный реюз при повторном add **пока job жив в Redis** (см. §3 — это лишь быстрый guard, не авторитет).

### 2.4 GPU submit-and-park seam (CPU-stub в P2, GPU-ready)
- **P2 (CPU):** `asr`/`score`/`reframe` вызывают `runPythonStage` in-process (faster-whisper CPU, Gemini-via-OpenRouter, MediaPipe/blur-pad). **Без park.** GPU-вентиль `setGlobalConcurrency(2)` всё равно ставится на `gpu-asr`/`gpu-score` (seam соблюдён и проверяется на boot).
- **GPU-ready:** перевод стадии на GPU = изменить ТОЛЬКО её handler: submit провайдеру → `state/park.ts` пишет `park:${providerRequestId} → jobId` в Redis → `job.moveToWaitingChildren(token)` (воркер НИКОГДА не блокируется). Без изменения DAG/топологии.
- **webhook-receiver:** публичный домен → `handle-callback.ts`: (1) HMAC-verify сырого тела **до** любой мутации, (2) **атомарный** дедуп по prediction-id (`GETDEL`/Lua compare-and-delete — правка из idempotency-race MEDIUM), (3) `resumeParkedJob` двигает state-machine через тот же forward-only `setStatus(validFrom:[...])`.
- 429: `queue.rateLimit(retryAfterMs)` (НЕ deprecated `worker.rateLimit` — правка bullmq-semantics MEDIUM) + `throw Worker.RateLimitError()` (не жжёт attempt) + статический `limiter:{max:30,duration:1000}` на gpu-очередях.

---

## 3. Идемпотентность и exactly-once

Три независимых слоя; **Postgres — durable-авторитет**, Redis jobId — быстрый in-flight guard.

1. **Content-hash jobId (быстрый, эфемерный):** каждый узел `${stage}-${hash}`, корень `flow-${hash}`. Повторный add живого flow = тихий no-op. **НЕ durable** — `removeOnComplete` освобождает id; **никогда не авторитет**.
2. **`upload_ledger` ON CONFLICT (durable-авторитет, ЕДИНСТВЕННЫЙ enqueue-gate):** `INSERT … ON CONFLICT (content_hash) DO NOTHING RETURNING`. Пустой RETURNING → гонка проиграна → follow-up SELECT за `result_url`/`status` → пропуск enqueue. **Все** add-пути (hook-receiver, reconcile-sweep, resume) сначала делают guarded `setStatus(hash,'queued',validFrom:[terminal])` в той же транзакции, что решает enqueue — только владелец строки enqueue'ит (правка idempotency-race CRITICAL #1).
3. **Корень `flow-${hash}` не освобождается:** `removeOnComplete:false` на узле `publish`; отдельный bounded GC по `ledger.status='done'`, не по age-eviction Redis (правка idempotency-race CRITICAL #1) — id остаётся живым dedup-guard на реалистичное окно повторной доставки.
4. **Artifact skip-if-exists с маркером завершения (resume + правка node-python-failure HIGH):** стадия не доверяет голому `head()` (битый multipart/обрезанный mp4 дают ложный 200). Каждая multi-file-стадия после загрузки всех артефактов+manifest пишет **один sentinel** `r2.put(${hash}/${stage}/_COMPLETE.json)` (содержит clip_count + sha манифеста) **последним**. Skip-if-exists проверяет ТОЛЬКО sentinel. Порядок: артефакты → sentinel → durable-строка ledger.
5. **Детерминированный ключ клипа:** `deriveClipKey(contentHash, rank)` в `@fliphouse/shared`, используется и writer'ом, и `publish`. `manifest.path` — голое имя файла (`clip_000.mp4`), НЕ R2-ключ; маппинг тестируется. `clip_url` — чистая функция от `(hash, rank)`, поэтому re-publish UPDATE'ит ту же строку, не плодит orphan (правка idempotency-race HIGH).
6. **Без двойного debit:** `balance_entries` `INSERT … ON CONFLICT (user_id, job_id) DO NOTHING`, `job_id = flow-${hash}` (content-derived, НЕ per-attempt). `debitOnce` **бросает `UnrecoverableError` при null/пустом jobId** (NULL в Postgres DISTINCT → молчаливый дубль); partial-unique/CHECK требует `job_id NOT NULL` для kind payg/subscription (deposits держат NULL, дедуп по `txid`). Сумма — из durable `ledger.durationSec`, не из transient ffprobe. Debit на `publish` после успеха (правка idempotency-race HIGH + §9).
7. **Lost-enqueue recovery (правка idempotency-race CRITICAL #2):** reconcile-sweep сканирует ДВА предиката: (a) R2-объект без строки ledger; (b) строка ledger в pre-terminal статусе, чей `flow-${hash}` **отсутствует** в Redis (`flowProducer.getFlow(...) === null`) дольше grace-TTL → idempotent re-drive enqueue. Закрывает дыру «commit ledger, краш до flowProducer.add».
8. **Server-verified hash fallback:** когда клиент не прислал `sha256` — Python-CLI-стадия `hash` стримит R2-объект чанками по 64KB (никогда весь 2ч-видео в память), затем тот же ledger-insert. Оба пути сходятся на `flow-${hash}`.
9. **Дубликат tusd POST:** поглощается ledger ON CONFLICT + jobId no-op; всегда 200 на durable-обработку.
10. **Partial-failure resume:** повторный enqueue того же flow → завершённые upstream-стадии бьют sentinel-skip и мгновенно возвращают cached-ref; пересчитывается только упавшая стадия + потомки.

---

## 4. Семантика отказов

- **Taxonomy** (`errors/classify.ts`): retryable → обычный `Error` → `attempts`/`backoff`; fatal → `UnrecoverableError` (ноль ретраев). Зеркалит `cli.py`-классификацию (§1.2). **Бросок неверного типа — load-bearing** (fatal-as-Error бьёт 402 N раз) — обе ветки тестируются.
- **Per-stage retry** (`STAGE_RETRY`): transcode/store/publish = 2 (большинство — fatal-вход); asr/score = 5, expo `delay:2000` (пережить 429/5xx); reframe/caption/banner/fanout = 3.
- **Parent-on-child-failure:** критическая цепочка `failParentOnFailure:true` → реальный отказ валит весь flow быстро. `banner` `ignoreDependencyOnFailure:true`. **Дефолт без флага = баг** (testcontainers-тест #14 утверждает оба: что флаг реально пробрасывает, и что без флага родитель застревает в `waiting-children`).
- **Lazy-parent-flip (правка bullmq-semantics HIGH + графт судьи):** `failParentOnFailure` ленив — родитель флипается только когда воркер его обрабатывает. **Деплой-ограничение: воркеры orchestrator-очередей (`publish` И `cpu`/`store`) держат `min:1`, никогда scale-to-zero**, иначе пропагация отказа застрянет. Watchdog-sweep детектит корни, застрявшие в wait/waiting-children дольше TTL → force-fail + запись `flow_failures`, чтобы пропавший воркер деградировал в залогированный отказ, не тихий stall.
- **Stalled recovery:** `lockDuration = 15min` (> самой долгой стадии) + lock-extension-таймер в `make-worker.ts`. **Инвариант (правка node-python-failure HIGH): `timeoutMs(stage) < LOCK_DURATION_MS` для каждой стадии** (unit-тест), чтобы Node-abort всегда срабатывал раньше stall-recovery и не было дабл-прогона. `maxStalledCount=1`. `stalled` — first-class состояние дашборда, не тихий ретрай.
- **Внутренний ffmpeg timeout (правка node-python-failure HIGH):** все `subprocess.run` в Python-ядре получают `timeout=max(60, span*REALTIME_FACTOR)`, чтобы зависший ffmpeg умер чисто внутри Python (envelope `retryable`), а не только через SIGKILL группы.
- **DLQ:** у BullMQ нет DLQ-объекта — per-queue FAILED-set ЕСТЬ dead-letter (bounded `removeOnFail:{age:86400}`); projector зеркалит fatal-отказы в durable `flow_failures` (переживает eviction/redeploy).
- **Graceful shutdown:** SIGTERM → `worker.close()` (drain, не force) + close QueueEvents/FlowProducer/connection.

---

## 5. Прогресс и наблюдаемость

- **Per-stage progress:** `job.updateProgress({ stage, pct, detail })` (структурный объект); ffmpeg `-progress pipe:1` парсится в суб-прогресс.
- **Flow-aggregate:** у BullMQ нет whole-flow %. `progress/flow-progress.ts` = чистая взвешенная модель над фиксированным 9-узловым DAG (`computeFlowProgress`), 100% unit-покрытие.
- **Cluster-events:** `progress/projector.ts` — один `QueueEvents` на очередь (`waitUntilReady()`/`close()` в lifecycle), маппит `jobId → flow-${hash}`, **персистит aggregate в Postgres `upload_ledger.status`** (durable; Next.js дашборд читает таблицу через SWR/poll, не Redis). Зеркалит fatal-отказы в `flow_failures`.
- **OTel и bull-board — ОТЛОЖЕНЫ за пределы P2-гейта (графт судьи):** для CPU-only P2 дашборд читает `upload_ledger` из Postgres напрямую; два always-on Railway-сервиса и их coverage-поверхность срезаны без ослабления гарантий идемпотентности/отказов. Когда вернёмся: один общий `BullMQOtel({tracerName:'fliphouse',enableMetrics:true})` на КАЖДЫЙ Queue/Worker/FlowProducer; bull-board read-only (`readOnlyMode:true`, `allowRetries:false`, basic-auth, `hideRedisDetails:true`).
- **Status-enum (forward-only):** `queued, hashing, transcoding, transcribing, scoring, reframing, captioning, rendering, storing, publishing, done, failed, duplicate`.

---

## 6. Пофайловый план

### 6.1 `@fliphouse/db` — НОВЫЙ workspace-пакет (графт судьи: единственный источник схемы)
Владеет drizzle-схемой `upload_ledger`/`clips`/`flow_failures` и репозиторием. `apps/web` и `apps/worker-node` потребляют его — устраняет дублирование DDL и worker→web-связность.
- **`packages/db/src/schema.ts`** *(new, ~180 строк)* — drizzle-таблицы (§7).
- **`packages/db/src/client.ts`** *(new, ~60)* — `drizzle-orm` + `pg` Pool, injectable.
- **`packages/db/src/ledger-repo.ts`** *(new, ~180)* — репозиторий:
  ```ts
  claimUpload(row): Promise<{ claimed: boolean; existing?: UploadRow }>       // INSERT ON CONFLICT DO NOTHING RETURNING + fallback SELECT
  setStatus(hash, to, validFrom[]): Promise<boolean>                          // guarded UPDATE WHERE status IN (...)
  upsertClips(hash, clips[]): Promise<void>                                   // ON CONFLICT (content_hash, rank) DO UPDATE
  finishUpload(hash, resultUrl, manifestUrl, engine): Promise<void>
  recordFailure(hash, stage, code, message): Promise<void>
  debitOnce(userId, jobId, amountUsdt, reason): Promise<boolean>             // throws UnrecoverableError при пустом jobId
  findStuckFlows(graceTtlMs): Promise<UploadRow[]>                            // для reconcile-sweep предиката (b)
  ```
  Каждая ветка достижима single-connection через pglite (предварительный INSERT перед `claimUpload` бьёт пустой-RETURNING путь) — гейт 100% держится без Docker (правка testability MEDIUM).

### 6.2 `packages/shared` (типы + id)
- **`hash/content-hash.ts`** *(changed)* — `sha256Hex` (unchanged); `flowJobId(h)→flow-${h}`; `stageJobId(stage,h)→${stage}-${h}`; `BULLMQ_JOBID_RE=/^[a-zA-Z0-9._-]+$/` + guard, бросающий если id не матчит; `isValidContentHash(s)=/^[0-9a-f]{64}$/` (графт судьи). **`jobIdFromHash` удаляется** (clean rename — его зовёт только собственный тест; правка testability HIGH).
- **`flow/stage.ts`** *(new, ~35)* — `Stage`/`QueueName`-union (владелец); `queue-name.ts` импортирует отсюда. Добавлен `'fanout'`.
- **`contract/stage-io.ts`** *(new, ~120)* — wire-контракт Node↔Python + Zod:
  ```ts
  interface StageRequest { stage; contentHash; inputs:Record<string,string>; outputPrefix; params }
  type StageResult = { ok:true; outputs:ArtifactRef[]; metrics } | { ok:false; kind:'fatal'|'retryable'; code; message }
  STAGE_REQUEST_VERSION = 1
  ```
- **`manifest/manifest-schema.ts`** *(new, ~120)* — Zod-зеркало `manifest.py` `ClipEntry`/`RenderManifest`; экспортирует `ENGINE_NAME` и `MANIFEST_SCHEMA_VERSION` как именованные константы (правка testability LOW), `deriveClipKey(hash,rank)`.

### 6.3 `apps/worker-node/src/queues/`
- **`queue-name.ts`** *(changed)* — импорт `Stage`/`QueueName` из `@fliphouse/shared`; `STAGE_TO_QUEUE` расширен `fanout:'cpu'`; `resolveQueue` как есть.
- **`queues/queue-config.ts`** *(new, ~90)* — `GPU_GLOBAL_CONCURRENCY=2`, `CPU_WORKER_CONCURRENCY=1`, `LOCK_DURATION_MS=15*60*1000`, `STALLED_INTERVAL_MS=30_000`, `MAX_STALLED_COUNT=1`, `RETENTION`, `STAGE_RETRY: Record<Stage,StageRetryPolicy>`, `STAGE_TIMEOUT_MS: Record<Stage,number>` + assert-helper `assertTimeoutsBelowLock()`.
- **`redis/connection.ts`** *(new, ~70)* — `createRedisConnection(env)` → ioredis `maxRetriesPerRequest:null` + TLS; `setGpuValve(queue)` → `setGlobalConcurrency` + лог `getGlobalConcurrency()`. Injectable.

### 6.4 `apps/worker-node/src/flow/`
- **`flow/build-flow-tree.ts`** *(new, ~150)* — чистая функция, строящая дерево §2.1 с детерминированными jobId и флагами. Без Redis, 100% offline.
- **`flow/flow-producer.ts`** *(new, ~90)* — обёртка над `FlowProducer` (`add`/`getFlow`/`close`); `enqueueFlow(args)=add(buildFlowTree(args))`. Injectable connection + clock.

### 6.5 `apps/worker-node/src/python/`
- **`python/spawn.ts`** *(new, ~160)* — `runPythonStage(req, opts)`: спавн `python -m fliphouse_worker.cli <stage>`, JSON в stdin, stderr line→`onStderrLine`, `detached:true`, abort→`process.kill(-pid,'SIGKILL')`, парс framed `@@FLIPHOUSE_RESULT@@`-строки через Zod. **Полностью unit-тестируем через инъекцию `_spawn`** (fake EventEmitter-child: exit 0/≠0/signal/parse-fail/ENOENT/abort→kill с negated pid) — без реального процесса, без платформенной зависимости (правка testability HIGH). Один real-fixture-смоук (§8) — integration-tagged.
- **`python/resolve-entry.ts`** *(new, ~40)* — резолв python + `-m fliphouse_worker.cli` из `FLIPHOUSE_PYTHON` env.

### 6.6 `apps/worker-node/src/stages/`
- **`stages/handler-contract.ts`** *(new, ~70)* — `StageContext { job; contentHash; ownerId; r2; db:LedgerRepo; runStage }`; `type StageHandler = (ctx)=>Promise<StageResult>`. (Node НЕ имеет S3-зависимости — `r2` это тонкий HEAD/sentinel-checker; реальный R2-I/O в Python-CLI — графт судьи.)
- По одному файлу на стадию (~80–140): `transcode.ts`, `asr.ts`, `score.ts`, `fanout.ts`, `reframe.ts`, `caption.ts`, `banner.ts`, `store.ts` (читает плечи через `getChildrenValues()`+`getIgnoredChildrenFailures()`), `publish.ts` (парс `manifest.json` через Zod, `upsertClips`, `finishUpload`, `debitOnce`).
- Тело skip-if-exists: `1) if (await r2.headSentinel(${hash}/${stage})) return cached; 2) res=await runStage(req); 3) if(!res.ok) throw classifyStageError(res); 4) durable-строка ПОСЛЕ sentinel; 5) return res`.
- **`stages/registry.ts`** *(new, ~40)* — `Record<Stage,StageHandler>` + `resolveHandler(stage)` (throw на unknown).

### 6.7 `apps/worker-node/src/worker/`
- **`worker/make-worker.ts`** *(new, ~120)* — фабрика `new Worker(...)`; processor: stage из `job.name` → handler → `updateProgress`-проекция + lock-extension-таймер + классификация ошибок; SIGTERM → `worker.close()`.
- **`worker/run-workers.ts`** *(new, ~90, bootstrap — coverage-excluded)* — boot всех воркеров в одном cpu-процессе для P2; ставит GPU-вентиль; **сначала `cli.py --selftest`** (правка node-python-failure MEDIUM); SIGTERM-handler; close QueueEvents/FlowProducer/connection.

### 6.8 `apps/worker-node/src/errors/`
- **`errors/classify.ts`** *(new, ~80)* — `classifyStageResult(res)→'fatal'|'retryable'`; `toBullError(c,code,msg)→UnrecoverableError|Error`; `classifyStageError(res)`. Обе ветки 100%.

### 6.9 `apps/worker-node/src/progress/`
- **`progress/flow-progress.ts`** *(new, ~120)* — чистая взвешенная модель над 9 узлами; `computeFlowProgress`.
- **`progress/projector.ts`** *(new, ~150)* — `QueueEvents` на очередь, `jobId→flow-${hash}`, персист aggregate в Postgres, зеркало fatal→`flow_failures`. Injectable.

### 6.10 `apps/worker-node/src/state/`
- **`state/transitions.ts`** *(new, ~90)* — forward-only; `validTransition(from,to)`; назад только `→failed`; `→duplicate` только при ON CONFLICT-skip.
- **`state/park.ts`** *(new, ~110)* — `park:${providerRequestId}→jobId`; `parkJob(job,id)` через `moveToWaitingChildren`; `resumeParkedJob(id,result)` через **атомарный GETDEL/Lua** (правка idempotency-race MEDIUM). В P2 CPU-путь не паркует, seam существует.

### 6.11 `apps/hook-receiver/` — НОВЫЙ сервис (владелец FlowProducer + idempotency)
- **`src/server.ts`** *(new, ~120, bootstrap — coverage-excluded)* — минимальный HTTP (Fastify/Hono), маршрут `POST /tus/post-finish`.
- **`src/handle-post-finish.ts`** *(new, ~160)* — `handlePostFinish(payload, deps)`: валидация `Type==='post-finish'`; извлечь `Event.Upload.{ID,Size,MetaData.sha256,Storage.{Bucket,Key}}`; резолв hash (fast-path `isValidContentHash(MetaData.sha256)`, иначе `hash`-job); `setStatus`-guarded claim + enqueue ТОЛЬКО владельцем строки; 200 на durable, 5xx только на transient.
- **`src/reconcile-sweep.ts`** *(new, ~120)* — repeatable job: ДВА предиката (R2-без-строки + ledger-stuck-без-Redis-flow); idempotent replay.
- **`src/tusd-types.ts`** *(new, ~70)* — Zod-схема post-finish envelope (все MetaData — строки).

### 6.12 `apps/webhook-receiver/` — НОВЫЙ сервис (GPU-callbacks, P2-dormant но контракт полон)
- **`src/server.ts`** + **`src/handle-callback.ts`** *(new, ~140 суммарно)* — публичный домен, HMAC-verify **до** мутации, атомарный дедуп по prediction-id, `resumeParkedJob`. В P2 трафика нет.

### 6.13 Python CLI seam (GAP — минимум)
- **`services/ai-worker-python/fliphouse_worker/cli/_dispatch.py`** *(new, ~140, ЧИСТЫЙ, 100%-coverable)* — `_dispatch(stage, req)->dict` диспатчит в существующие функции (`render_vertical_clips`, `select_clips`, `select_provider().transcribe`, `score_clip`) + envelope-билдеры + классификационная таблица (§1.2). **ML-логика не переезжает.**
- **`services/ai-worker-python/fliphouse_worker/cli/__main__.py`** *(new, ~80, импурный — coverage-omit)* — argparse, stdin/stdout, R2-клиент (boto3), `--selftest`, `__main__`-guard, framing `@@FLIPHOUSE_RESULT@@` + fd-1-редирект.
- **`pyproject.toml`** *(changed)* — `[project.scripts] fliphouse-stage = "fliphouse_worker.cli.__main__:main"`; добавить `fliphouse_worker.cli` в `[tool.setuptools] packages`; `[tool.coverage.report] omit` для `__main__.py`/R2-glue (правка testability HIGH). Pytest `--cov-fail-under=100` держится на `_dispatch`.

---

## 7. Схема БД (`packages/db/src/schema.ts`)

Соблюдает идиомы существующего `Schema.ts` (pgEnum, text-PK, numeric, `$onUpdate`, uniqueIndex для идемпотентности).

```ts
export const uploadStatusEnum = pgEnum('upload_status', [
  'queued','hashing','transcoding','transcribing','scoring','reframing',
  'captioning','rendering','storing','publishing','done','failed','duplicate']);

export const uploadLedger = pgTable('upload_ledger', {
  contentHash: text('content_hash').primaryKey(),        // = jobId-core, ON CONFLICT gate
  ownerId: text('owner_id').notNull(),
  firstUploadId: text('first_upload_id').notNull(),
  tusObjectKey: text('tus_object_key').notNull(),
  status: uploadStatusEnum('status').default('queued').notNull(),
  flowJobId: text('flow_job_id'),
  sizeBytes: integer('size_bytes'),
  durationSec: integer('duration_sec'),
  resultUrl: text('result_url'),
  manifestUrl: text('manifest_url'),
  engine: text('engine'),
  error: text('error'),
  attempts: integer('attempts').default(0).notNull(),
  createdAt: timestamp('created_at',{mode:'date'}).defaultNow().notNull(),
  updatedAt: timestamp('updated_at',{mode:'date'}).defaultNow().$onUpdate(()=>new Date()).notNull(),
});

export const clips = pgTable('clips', {
  id: serial('id').primaryKey(),
  contentHash: text('content_hash').notNull(),           // FK → upload_ledger.content_hash
  rank: integer('rank').notNull(),                       // 0 = лучший
  score: numeric('score',{precision:6,scale:4}).notNull(),
  subScores: jsonb('sub_scores').notNull(),              // hook/emotion/payoff/visual/audio/pacing
  confidence: integer('confidence').notNull(),
  startTime: numeric('start_time',{precision:10,scale:3}).notNull(),
  endTime: numeric('end_time',{precision:10,scale:3}).notNull(),
  durationS: numeric('duration_s',{precision:10,scale:3}).notNull(),
  width: integer('width').notNull(),                     // 1080
  height: integer('height').notNull(),                   // 1920
  clipUrl: text('clip_url').notNull(),                   // = deriveClipKey(hash,rank), чистая функция
  title: text('title').notNull(),
  usedVideo: boolean('used_video').notNull(),
  modelUsed: text('model_used').notNull(),
  modalitiesUsed: jsonb('modalities_used').notNull(),
  manifestSchemaVersion: integer('manifest_schema_version').notNull(),
  engine: text('engine').notNull(),
  createdAt: timestamp('created_at',{mode:'date'}).defaultNow().notNull(),
}, (t)=>({ hashRankUq: uniqueIndex('clips_hash_rank_uq').on(t.contentHash, t.rank) }));

export const flowFailures = pgTable('flow_failures', {    // durable DLQ-зеркало
  id: serial('id').primaryKey(),
  contentHash: text('content_hash').notNull(),
  stage: text('stage').notNull(),
  code: text('code').notNull(),
  message: text('message').notNull(),
  createdAt: timestamp('created_at',{mode:'date'}).defaultNow().notNull(),
});
```

Миграция `packages/db/migrations/0004_flow-dag.sql` (drizzle-kit generate). Для `balance_entries`: добавить partial-unique/CHECK `job_id NOT NULL` для kind payg/subscription (правка idempotency-race HIGH). `apps/web` переключает импорт схемы на `@fliphouse/db`. `clips_hash_rank_uq` делает re-publish идемпотентным.

---

## 8. TDD-план

**Unit (offline, Vitest):**
1. `flowJobId/stageJobId` → матч `BULLMQ_JOBID_RE`, без `:`, не чисто-числовой (обе ветки guard) — *ловит баг `flow:`*.
2. `buildFlowTree` → точная топология §2.1 (с `fanout`), детерминированные jobId, `failParentOnFailure` на критической цепочке, `ignoreDependencyOnFailure` только на banner, корень `flow-${hash}`, `removeOnComplete:false` на publish.
3. `resolveHandler` throw на unknown.
4. `classifyStageResult`/`toBullError` → fatal→`UnrecoverableError`, retryable→`Error` (обе ветки).
5. `spawn.runPythonStage` через инъекцию `_spawn` (fake child): success framed-JSON, exit≠0, signal, abort→kill(negated pid), parse-fail, ENOENT, шум в stdout до/после framed-envelope + fd-1-шум.
6. `computeFlowProgress` → монотонна, 0→100 по 9 узлам.
7. `validTransition` → forward-only, `→failed` ok, назад reject.
8. `handlePostFinish` (deps mocked) → claimed→enqueue; not-claimed→skip+existing; bad-sha256→hash-path; 200 durable / 5xx transient.
9. Каждый stage-handler skip-if-exists → sentinel present → cached без `runStage` (assert call-count 0).
10. `assertTimeoutsBelowLock` → каждый `STAGE_TIMEOUT_MS < LOCK_DURATION_MS`.
11. `ledger-repo` на pglite single-connection → пустой-RETURNING ветка (pre-INSERT), `debitOnce` null-jobId → throw, guarded `setStatus` reject вне validFrom.
12. `_dispatch` (pytest, 100%) → каждый stage в нужную функцию; каждый тип исключения → корректный envelope `kind`; один framed-JSON.
13. Cross-language contract: Python golden `manifest.json` парсится TS-Zod `RenderManifest`, поле-в-поле; `ENGINE_NAME`/`MANIFEST_SCHEMA_VERSION` TS == Python golden (правка testability MEDIUM).

**Integration (testcontainers Redis+Postgres — отдельный CI-job, НЕ в 100%-гейте; правка testability CRITICAL):**
14. **Flow add не бросает** — `flowProducer.add` полного дерева на реальном брокере, assert НЕТ `-7/ParentJobCannotBeReplaced` (ловит нелегальный диамант, который offline-тест #2 пропустил бы).
15. **Порядок стадий** — `transcode` < `asr` < `score` < `fanout` < плечи < `store` < `publish`.
16. **post-finish enqueue** — POST → ровно один flow, корень `flow-${hash}`.
17. **Idempotency over jobId-eviction** — завершить flow, force-remove завершённые jobs, повторный add → ВТОРОЙ add отклонён ledger-gate'ом, не jobId (правка idempotency-race CRITICAL #1).
18. **Lost-enqueue sweep** — ledger-строка 'queued' без Redis-flow → sweep создаёт ровно один flow, повторный sweep — ноль (правка idempotency-race CRITICAL #2).
19. **failParentOnFailure** — упавший `transcode` валит весь flow до `publish=failed` (при живом publish-воркере); и без-флага-ребёнок оставляет родителя в `waiting-children` (footgun-guard); и lazy-flip: без publish-воркера publish сидит в `:wait` (документирует min:1).
20. **No double-debit** — дубль tusd POST + re-enqueue → ровно одна `balance_entries` строка для `(user_id, flow-${hash})`.
21. **ON CONFLICT** — конкурентный `claimUpload` → ровно один победитель.
22. **Clips 1080×1920 ranked** — `publish` парсит manifest, `upsertClips` пишет `width=1080,height=1920`, `clips_hash_rank_uq` enforce'ит; re-publish UPDATE не дубль.
23. **Sentinel-skip** — kill стадии после 1 артефакта, re-run → финальный R2-набор полон и sentinel-гейтнут (правка node-python-failure HIGH).

### Порядок сборки (TDD)
1. Fix jobId (`flow-${hash}` + `stageJobId` + `isValidContentHash`, удалить `jobIdFromHash`, test #1) + правка `docs/01 §5`. *(Push.)*
2. CI: добавить `integration:` job на `ubuntu-latest` (Docker preinstalled) для testcontainers-vitest-project; исключить integration-specs из coverage-include; внести в branch-protection required-checks (правка testability CRITICAL).
3. `@fliphouse/db` пакет: schema + миграция `0004` + `ledger-repo` (unit pglite #11, потом testcontainers #21); `apps/web` → `@fliphouse/db`.
4. Shared: `stage.ts` (+`fanout`), `stage-io.ts`, `manifest-schema.ts` (+ контракт-тест #13), per-package vitest.config с coverage-excluded bootstrap + meta-тест гейта (правка testability CRITICAL #2).
5. ESLint `import/extensions: always` для `.js` на относительных импортах (правка testability MEDIUM ESM).
6. `queue-config.ts` (+#10) + `redis/connection.ts`.
7. `errors/classify.ts` (#4).
8. `python/spawn.ts` + `resolve-entry.ts` (#5).
9. `cli/_dispatch.py` + `cli/__main__.py` + pyproject scripts/omit (#12).
10. `flow/build-flow-tree.ts` (#2) + `flow/flow-producer.ts`.
11. `stages/*` + `registry.ts` (#9, #3).
12. `worker/make-worker.ts` + `run-workers.ts` (+selftest, lock-extension, graceful close).
13. `state/transitions.ts` (#7) + `state/park.ts`.
14. `progress/flow-progress.ts` (#6) + `projector.ts`.
15. `apps/hook-receiver` (#8) + reconcile-sweep (двойной предикат).
16. `apps/webhook-receiver` (HMAC + атомарный дедуп, P2-dormant).
17. testcontainers-сьют #14–#23.
18. Один multi-stage Dockerfile для `cpu-worker` (python wheel + extras + `libgl1` apt-слой + node-bundle; Node PID 1 спавнит python).
19. *(Отложено за P2-гейт:)* `apps/bull-board`, OTel-инструментация.

---

## 9. Открытые решения для founder'а

1. **Размещение hook-receiver** — отдельный `apps/hook-receiver` vs route в `apps/web`. **Рекомендация: отдельный** (чистое владение FlowProducer, нет Next-cold-start на enqueue-пути), но +1 Railway-сервис. Вопрос стоимости.
2. **`lockDuration = 15min`** — выставлено против самой долгой стадии на каноне 2ч `tinkov-plata.mp4`. **Нужен замер worst-case transcode/render** с CHECKPOINT B; до него — placeholder. Инвариант `timeoutMs < lockDuration` обязателен независимо.
3. **Тайминг PAYG-debit** — на `publish` (после успеха, не биллим упавшие jobs) vs на `score`. **Рекомендация: на `publish`**; подтвердить против `scoring/pricing.py` (заметка: PAYG считается от `durationSec`, не от LLM-токен-стоимости).
4. **testcontainers в CI** — нужен Docker-job на required-check `ci`. **Рекомендация: отдельный `integration:` job на `ubuntu-latest`**, integration-тесты вне 100%-coverage-гейта. Подтвердить, что CI-runner это тянет.
5. **Каденс reconcile-sweep** — интервал sweep потерянных post-finish + stuck-flows. **Рекомендация: каждые 5 мин.** Ops-предпочтение.
6. **Retention `flow_failures`** — вечно (аудит) vs prune. **Рекомендация: вечно** (дёшево, durable DLQ-аудит).
7. **`fanout`-узел** — добавление легализующего passthrough-узла слегка раздувает топологию. **Рекомендация: принять** (единственный чистый способ сохранить параллелизм трёх плеч при one-parent-ограничении BullMQ; альтернатива — полностью линейный DAG с потерей параллелизма). Подтвердить.
8. **Графт `@fliphouse/db`** — выносит схему из `apps/web` в новый пакет; затрагивает web-импорты. **Рекомендация: да** (убирает дублирование DDL и worker→web-связность). Подтвердить.

---

**Ключевые файлы (абсолютные):**
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/shared/src/hash/content-hash.ts` (ДОЛЖНО: `flow:` → `flow-`, удалить `jobIdFromHash`)
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/apps/worker-node/src/queues/queue-name.ts` (reuse + `fanout`)
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/clipping/manifest.py` (контракт clips-таблицы)
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/pyproject.toml` (`[project.scripts]` + `cli` + coverage omit)
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/packages/db/` (НОВЫЙ пакет: schema + migration + ledger-repo)
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/docs/01-АРХИТЕКТУРА-И-RAILWAY.md` §5 (правка `flow:` → `flow-`, добавить `fanout`-узел)
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/roadmap/P2-checkpoint-c-orchestration.md` (этот документ)