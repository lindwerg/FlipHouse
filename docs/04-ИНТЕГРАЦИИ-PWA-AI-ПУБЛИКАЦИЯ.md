# 04 — Интеграции: PWA, AI и публикация

> Интеграционный слой FlipHouse: PWA с web-push, AI-адаптер на OpenRouter, ingest и публикация в YouTube / TikTok / Instagram, мультиплатформенная модель OAuth-токенов.
>
> Стек: Next.js (App Router), Railway, Postgres. Все факты проверены по официальной документации (июнь 2026).

---

## Оглавление

1. [PWA: Serwist + web-push («Твои нарезки готовы»)](#1-pwa-serwist--web-push)
2. [AI-адаптер на OpenRouter (замена Gemini/OpenAI)](#2-ai-адаптер-на-openrouter)
3. [YouTube: ingest + публикация](#3-youtube-ingest--публикация)
4. [TikTok + Instagram: публикация и ANTI-BLOCK чеклист](#4-tiktok--instagram-публикация)
5. [Мультиплатформенная модель OAuth/токенов](#5-мультиплатформенная-модель-oauthтокенов)

---

## 1. PWA: Serwist + web-push

### 1.1 Что PWA реально даёт FlipHouse

FlipHouse — платформа AI-нарезки: пользователь загружает длинное видео → асинхронная задача рендерит вертикальные клипы со встроенным оффер-баннером. Ключевая PWA-фича — **повторное вовлечение по завершении долгого рендера** («Твои нарезки готовы»). Поэтому приоритет нестандартный:

> **push > installability > offline-оболочка**

Оффлайн-редактирование нереально (рендер на сервере), поэтому offline-история — это shell + экран «нет соединения», а не полноценное оффлайн-приложение.

### 1.2 Выбор библиотеки: Serwist (решено)

Используем **Serwist** (`@serwist/next` + `serwist`) — поддерживаемый преемник `next-pwa`, на который ссылается официальная документация Next.js.

| Альтернатива | Вердикт |
|---|---|
| `next-pwa` (shadowwalker) | **Мертва** — нет App Router / Next 14+. Не использовать. |
| Ручной service worker | Годится только для push; нет precache/offline shell, версионирование кэша руками. |
| `@ducanh2912/next-pwa` | Реальный форк, но Serwist — официальное продолжение того же автора. Берём Serwist. |
| **Serwist** | MIT, 1.4k★, активна (push 2026-05-13). **Выбор.** |

> ⚠️ **Критическое ограничение (проверено):** плагин Serwist для Next.js **требует Webpack**. Если перейти на Turbopack для прод-сборки — компиляция SW не запустится. Решение: **прод-сборка на Webpack** (`next build` по умолчанию), Turbopack — только для dev.

### 1.3 Архитектура

```text
app/
├── manifest.ts                 # MetadataRoute.Manifest (динамический манифест)
├── sw.ts                       # Serwist worker (precache + runtime cache + push)
├── (push)/actions.ts           # 'use server' subscribe/unsubscribe/send
├── ~offline/page.tsx           # оффлайн fallback shell
└── components/pwa/
    ├── InstallPrompt.tsx       # iOS A2HS-инструкции + beforeinstallprompt (Android)
    └── PushOptIn.tsx           # запрос разрешения (gated, НЕ на загрузке)
lib/
├── push/subscriptions.ts       # репозиторий PushSubscription в БД
└── push/send.ts                # webpush.sendNotification обёртка
```

Один `sw.ts` совмещает два слоя: Serwist (precache + runtime cache + offline fallback) и собственные слушатели `push` / `notificationclick`. `serwist.addEventListeners()` сосуществует с `self.addEventListener('push', …)`.

### 1.4 Установка и конфиг

```bash
npm i @serwist/next web-push
npm i -D serwist @types/web-push
npx web-push generate-vapid-keys   # одноразово
```

```ts
// next.config.ts
import withSerwistInit from "@serwist/next";

const withSerwist = withSerwistInit({
  swSrc: "app/sw.ts",
  swDest: "public/sw.js",
  additionalPrecacheEntries: [{ url: "/~offline", revision: "1" }],
  disable: process.env.NODE_ENV === "development",
});

export default withSerwist({
  async headers() {
    return [
      { source: "/sw.js", headers: [
        { key: "Content-Type", value: "application/javascript; charset=utf-8" },
        { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
      ]},
      { source: "/(.*)", headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      ]},
    ];
  },
});
```

### 1.5 Service worker (Serwist + push в одном файле)

```ts
// app/sw.ts
import { defaultCache } from "@serwist/next/worker";
import { Serwist } from "serwist";

declare const self: ServiceWorkerGlobalScope;

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: defaultCache,
  fallbacks: {
    entries: [{ url: "/~offline", matcher: ({ request }) => request.destination === "document" }],
  },
});
serwist.addEventListeners();

// --- FlipHouse push ("нарезки готовы") ---
self.addEventListener("push", (event) => {
  const data = event.data?.json() ?? {};
  event.waitUntil(
    self.registration.showNotification(data.title ?? "FlipHouse", {
      body: data.body,
      icon: "/icon-192x192.png",
      badge: "/badge.png",
      data: { url: data.url ?? "/clips" }, // deep-link к готовой задаче
      tag: data.jobId,                      // схлопывание дублей по задаче
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url ?? "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((clients) => {
      const open = clients.find((c) => "focus" in c);
      return open ? open.focus() : self.clients.openWindow(url);
    })
  );
});
```

Дополнительно: `tsconfig.json` → `"types": ["@serwist/next/typings"], "lib": ["webworker"]`, `"exclude": ["public/sw.js"]`; `.gitignore` → `public/sw*`, `public/swe-worker*`.

### 1.6 Манифест

```ts
// app/manifest.ts
import type { MetadataRoute } from "next";
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "FlipHouse", short_name: "FlipHouse",
    description: "AI-нарезка длинных видео в вирусные Shorts/Reels/TikTok",
    start_url: "/", id: "/", display: "standalone", orientation: "portrait",
    background_color: "#0a0a12", theme_color: "#0a0a12", // под --color-bg
    icons: [
      { src: "/icon-192x192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512x512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
```

### 1.7 Web-push: «Твои нарезки готовы»

**VAPID** хранится в Railway-переменных: `NEXT_PUBLIC_VAPID_PUBLIC_KEY` (должна быть на build-time — инлайнится в клиент), `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT=mailto:...`.

> ⚠️ **Подписки — в БД, а не в памяти.** Пример из доков Next.js хранит подписку в модульной переменной — это демо. На Railway (рестарты, несколько реплик) **обязательна персистентность в Postgres**.

```ts
// app/(push)/actions.ts
"use server";
import webpush from "web-push";
import { saveSubscription, deleteSubscription } from "@/lib/push/subscriptions";

webpush.setVapidDetails(
  process.env.VAPID_SUBJECT!,
  process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY!,
  process.env.VAPID_PRIVATE_KEY!
);

export async function subscribeUser(userId: string, sub: PushSubscriptionJSON) {
  await saveSubscription(userId, sub);   // upsert по endpoint
  return { success: true };
}
export async function unsubscribeUser(endpoint: string) {
  await deleteSubscription(endpoint);
  return { success: true };
}
```

**Реальный триггер — вебхук рендер-задачи, а не кнопка.** Когда GPU/Replicate-воркер закончил, push шлёт обработчик вебхука:

```ts
// lib/push/send.ts
import webpush from "web-push";
export async function notifyClipsReady(userId: string, jobId: string) {
  const subs = await getSubscriptionsForUser(userId);
  const payload = JSON.stringify({
    title: "🎬 Твои нарезки готовы",
    body: "AI закончил резать видео. Забирай клипы с оффером.",
    url: `/clips/${jobId}`, jobId,
  });
  await Promise.allSettled(subs.map((s) =>
    webpush.sendNotification(s, payload).catch((err) => {
      // 404/410 = просроченная подписка → удалить, иначе список гниёт
      if (err.statusCode === 404 || err.statusCode === 410) return deleteSubscription(s.endpoint);
      throw err;
    })
  ));
}
```

> **Главная операционная деталь, которую опускают туториалы:** push-сервисы возвращают **404/410** на просроченные подписки — их строки обязательно удалять при каждой отправке.

**Opt-in — gated, не на загрузке.** Не вызывать `Notification.requestPermission()` при загрузке. Запрашивать после осмысленного действия — например сразу после старта первого рендера («Прислать, когда нарезки будут готовы?»).

### 1.8 Ограничения iOS PWA (жёсткие, проверены)

| Ограничение | Реальность | Что делает FlipHouse |
|---|---|---|
| **Push только в установленной PWA** | Работает лишь после «На экран Домой», iOS 16.4+. Вкладка push не получает. | Opt-in за A2HS. Детект `display-mode: standalone`; если нет — сначала инструкция установки, потом push. |
| **Нет авто-промпта установки** | На iOS нет `beforeinstallprompt`. | `InstallPrompt` с явной инструкцией Share → «На экран Домой», только iOS. |
| **EU-ограничение** | В части конфигураций push на iOS недоступен в EU. | iOS push — best-effort; всегда дублировать через in-app state + email. |
| **Нет background sync, малый кэш** | Нет Background Sync API; жёстче квоты. | Не полагаться на background sync; precache держать тонким (shell + иконки + offline). |
| **Permission после жеста** | `requestPermission` только по тапу в установленной PWA. | Opt-in только по тапу, никогда в effect. |

> **Решение:** email / in-app polling — **источник истины** для «нарезки готовы»; push — улучшение, а не единственный канал.

### 1.9 Railway-специфика

1. Сборка эмитит `public/sw.js` — нужен реальный Webpack-build (`next build`), не Turbopack для прода. Проверить наличие `public/sw.js` в образе.
2. `/sw.js` отдаёт сам Next-сервер → no-cache заголовки из `next.config.ts` применяются напрямую.
3. `NEXT_PUBLIC_VAPID_PUBLIC_KEY` — на build-time; остальное — runtime.
4. Postgres-плагин Railway для подписок:

```sql
create table push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  endpoint text unique not null,
  p256dh text not null,
  auth text not null,
  created_at timestamptz default now()
);
create index on push_subscriptions (user_id);
```

5. Отправка идёт из вебхука, читающего БД (не из памяти) → горизонтальное масштабирование реплик безопасно.
6. HTTPS на Railway-домене по умолчанию — обязателен для SW и push.

### 1.10 Порядок сборки + риски

**Порядок:** манифест+иконки → Serwist offline shell → push-инфра (VAPID, БД, server actions, листенеры) → gated opt-in UI → вебхук → `notifyClipsReady()` → email/in-app fallback.

**Риски:** Serwist требует Webpack · подписки в памяти из доков — ловушка · 404/410 надо чистить · `NEXT_PUBLIC_VAPID_PUBLIC_KEY` нужен на build-time · iOS push best-effort · `/sw.js` обязан быть `no-cache`.

---

## 2. AI-адаптер на OpenRouter

### 2.1 Зачем OpenRouter

Два LLM-нагрузки FlipHouse имеют противоположные профили цена/качество — именно для этого нужен роутинг-шлюз:

| Нагрузка | Объём | Латентность | Качество | Выход |
|---|---|---|---|---|
| **Virality scoring** (оценка клипа 0–100 + теги) | Очень высокий | Низкая | Среднее, дёшево | Строгий JSON |
| **Offer matching** (подбор оффера под клип) | Средний | Средняя | Выше, важны edge-cases | Строгий JSON |

Один OpenAI-совместимый эндпоинт, выбор модели per-call, авто-fallback между провайдерами, единый structured-output. Дешёвая модель для scoring, эскалация на сильную только для спорных offer-matching.

### 2.2 API surface (проверено)

- **Base URL:** `https://openrouter.ai/api/v1` — совместим с OpenAI Chat Completions (drop-in для `openai` SDK через override `baseURL`).
- **Endpoint:** `POST /chat/completions`. **Auth:** `Authorization: Bearer $OPENROUTER_API_KEY`.
- **Заголовки атрибуции:** `HTTP-Referer: https://fliphouse.app` (нужен для app-рейтингов) + `X-OpenRouter-Title: FlipHouse` (`X-Title` тоже принимается для совместимости).
- **Бюджет-гард:** `GET /api/v1/key` → `{ data: { limit, limit_remaining, usage, is_free_tier, ... } }`.

> Используем **OpenAI-совместимый путь**, чтобы код чисто откатывался на сырой OpenAI/Gemini — это и есть требование «заменяет Gemini/OpenAI».

### 2.3 Роутинг и fallback (проверено)

- **Массив fallback** — `"models": ["primary","fallback1","fallback2"]` в порядке приоритета. Срабатывает на context-length, модерации, rate-limit, простой провайдера.
- **Provider preferences** — `provider.sort: "price"|"latency"|"throughput"`; шорткаты `:floor` (цена) / `:nitro` (throughput).
- **`provider.require_parameters: true`** — **критично для FlipHouse**: роутить только к провайдерам, реально поддерживающим `response_format` json_schema, иначе можно молча получить свободный текст.
- `openrouter/auto` **не использовать** в проде — нужны детерминированные cost-pinned модели.

```jsonc
// Virality scoring — дёшево, высокий объём, price-floor + fallback
{ "models": ["google/gemini-2.5-flash", "openai/gpt-5-mini", "deepseek/deepseek-chat"],
  "provider": { "sort": "price", "require_parameters": true } }

// Offer matching — сильная модель, эскалация на edge-cases
{ "models": ["anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro"],
  "provider": { "require_parameters": true } }
```

> Слаги моделей пинить в конфиг из `openrouter.ai/models` на build-time, не хардкодить в call-site (линейка моделей меняется).

### 2.4 JSON mode (проверено)

```jsonc
"response_format": {
  "type": "json_schema",
  "json_schema": {
    "name": "virality_score", "strict": true,
    "schema": {
      "type": "object",
      "properties": {
        "score": { "type": "number" }, "hook_strength": { "type": "number" },
        "tags": { "type": "array", "items": { "type": "string" } },
        "reason": { "type": "string" }
      },
      "required": ["score", "hook_strength", "tags", "reason"],
      "additionalProperties": false
    }
  }
}
```

- Два режима: `json_object` (только валидный JSON) и `json_schema` + `strict:true` (точная схема). Берём второй.
- Пара с `provider.require_parameters: true`.
- **Response Healing** чинит битый JSON на non-streaming `response_format` (заявлено −80% дефектов) — но `JSON.parse` + retry держим как backstop.

### 2.5 Cost-aware выбор: дёшево по умолчанию, эскалация по неуверенности

1. **Scoring** всегда на дешёвом тире (`:floor` / `sort:"price"`, Flash/mini; в dev — `:free`-варианты: 20 req/min, 50/день <10 кредитов, 1000/день ≥10).
2. **Эскалация offer-matching:** сначала дёшево; если `confidence < 0.7`, флаг brand-safety, или топ-2 оффера в узком зазоре → переезд на сильный тир.
3. **Бюджет-гард:** опрос `GET /api/v1/key` (`limit_remaining`); halt / downgrade-to-`:free` при нехватке.

**Prompt caching** (проверено): OpenAI/Gemini — автоматически; Anthropic — явные `cache_control: {"type":"ephemeral"}` брейкпоинты на большом статичном префиксе (рубрика + политика + каталог офферов + few-shots), транскрипт клипа — последним, без кэша. Reads ~0.25×–0.50× input. Sticky-routing держит follow-up на том же провайдере.

**Rate limits:** ~1 req/s на кредит, до 200 req/s глобально. `402` = отрицательный баланс, `429` = rate-limit. Token-bucket по тиру + экспоненциальный backoff с jitter.

### 2.6 Адаптер (Python sketch)

```python
# fliphouse/llm/openrouter_adapter.py
from __future__ import annotations
import json, os, time, random
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from openai import OpenAI, APIStatusError, RateLimitError, APIConnectionError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

class Profile(str, Enum):
    SCORING = "scoring"          # дёшево, высокий объём
    OFFER_MATCH = "offer_match"  # сильно, эскалация edge-case

@dataclass(frozen=True)
class RouteConfig:
    models: tuple[str, ...]      # порядок приоритета -> OpenRouter `models`
    provider: dict[str, Any]

# Слаги пинить из openrouter.ai/models в конфиг, не литералы в проде.
ROUTES: dict[Profile, RouteConfig] = {
    Profile.SCORING: RouteConfig(
        models=("google/gemini-2.5-flash", "openai/gpt-5-mini", "deepseek/deepseek-chat"),
        provider={"sort": "price", "require_parameters": True}),
    Profile.OFFER_MATCH: RouteConfig(
        models=("anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro"),
        provider={"require_parameters": True}),
}

@dataclass
class LLMResult:
    data: dict[str, Any]
    model_used: str
    raw_usage: dict[str, Any] = field(default_factory=dict)

class OpenRouterAdapter:
    """Drop-in замена вызовов Gemini/OpenAI в движке нарезки.
    Смена провайдера = только base_url + ключ в env."""
    def __init__(self, *, base_url=None, api_key=None,
                 app_url="https://fliphouse.app", app_title="FlipHouse", max_retries=4):
        self._client = OpenAI(
            base_url=base_url or OPENROUTER_BASE_URL,
            api_key=api_key or os.environ["OPENROUTER_API_KEY"],
            default_headers={"HTTP-Referer": app_url, "X-OpenRouter-Title": app_title})
        self._max_retries = max_retries

    def complete_json(self, *, profile: Profile, system: str, user: str,
                      schema_name: str, schema: dict[str, Any],
                      temperature: float = 0.2, cache_static_prefix: bool = False) -> LLMResult:
        route = ROUTES[profile]
        sys_content: Any = system
        if cache_static_prefix:  # Anthropic explicit cache; no-op для OpenAI/Gemini auto-cache
            sys_content = [{"type": "text", "text": system,
                            "cache_control": {"type": "ephemeral"}}]
        body = dict(
            model=route.models[0],
            extra_body={"models": list(route.models), "provider": route.provider},
            messages=[{"role": "system", "content": sys_content},
                      {"role": "user", "content": user}],
            temperature=temperature,
            response_format={"type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema}})
        resp = self._call_with_retry(body)
        choice = resp.choices[0].message.content
        try:
            data = json.loads(choice)
        except json.JSONDecodeError as e:
            raise ValueError(f"Non-JSON despite strict schema: {choice[:200]}") from e
        return LLMResult(data=data, model_used=getattr(resp, "model", route.models[0]),
                         raw_usage=getattr(resp, "usage", None).__dict__
                                   if getattr(resp, "usage", None) else {})

    def _call_with_retry(self, body):
        for attempt in range(self._max_retries):
            try:
                return self._client.chat.completions.create(**body)
            except (RateLimitError, APIConnectionError) as e:   # 429 / сеть
                self._backoff(attempt, e)
            except APIStatusError as e:                         # 402, 5xx
                if e.status_code == 402:
                    raise RuntimeError("OpenRouter credits exhausted (402)") from e
                if e.status_code and e.status_code >= 500:
                    self._backoff(attempt, e); continue
                raise
        raise RuntimeError("OpenRouter call failed after retries")

    @staticmethod
    def _backoff(attempt, err):
        time.sleep(min(2 ** attempt + random.random(), 30))

    def credits_remaining(self) -> dict[str, Any]:  # GET /api/v1/key — бюджет-гард
        return self._client.get("/key", cast_to=dict)  # type: ignore[attr-defined]
```

### 2.7 Адаптер (TypeScript sketch)

```ts
// src/llm/openrouterAdapter.ts
import OpenAI from "openai";
const OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";

export type Profile = "scoring" | "offer_match";
interface RouteConfig { models: string[]; provider: Record<string, unknown>; }

// Слаги — в конфиг, не литералы.
const ROUTES: Record<Profile, RouteConfig> = {
  scoring: { models: ["google/gemini-2.5-flash", "openai/gpt-5-mini", "deepseek/deepseek-chat"],
             provider: { sort: "price", require_parameters: true } },
  offer_match: { models: ["anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro"],
                 provider: { require_parameters: true } },
};

export interface LLMResult<T> { data: T; modelUsed: string; usage?: unknown; }

export class OpenRouterAdapter {
  private client: OpenAI;
  constructor(opts: { baseUrl?: string; apiKey?: string; appUrl?: string; appTitle?: string } = {}) {
    this.client = new OpenAI({
      baseURL: opts.baseUrl ?? OPENROUTER_BASE_URL,
      apiKey: opts.apiKey ?? process.env.OPENROUTER_API_KEY!,
      defaultHeaders: {
        "HTTP-Referer": opts.appUrl ?? "https://fliphouse.app",
        "X-OpenRouter-Title": opts.appTitle ?? "FlipHouse", // X-Title тоже принимается (legacy)
      },
    });
  }

  async completeJson<T>(args: {
    profile: Profile; system: string; user: string;
    schemaName: string; schema: Record<string, unknown>;
    temperature?: number; cacheStaticPrefix?: boolean; maxRetries?: number;
  }): Promise<LLMResult<T>> {
    const route = ROUTES[args.profile];
    const systemContent = args.cacheStaticPrefix
      ? [{ type: "text", text: args.system, cache_control: { type: "ephemeral" } }] // no-op для OpenAI/Gemini
      : args.system;
    const body = {
      model: route.models[0],
      messages: [
        { role: "system" as const, content: systemContent as any },
        { role: "user" as const, content: args.user },
      ],
      temperature: args.temperature ?? 0.2,
      response_format: { type: "json_schema",
        json_schema: { name: args.schemaName, strict: true, schema: args.schema } },
      models: route.models,        // OpenRouter routing fields едут как extra body
      provider: route.provider,
    } as any;
    const resp = await this.withRetry(
      () => this.client.chat.completions.create(body), args.maxRetries ?? 4);
    const content = resp.choices[0]?.message?.content ?? "";
    let data: T;
    try { data = JSON.parse(content) as T; }
    catch { throw new Error(`Non-JSON despite strict schema: ${content.slice(0, 200)}`); }
    return { data, modelUsed: (resp as any).model ?? route.models[0], usage: (resp as any).usage };
  }

  private async withRetry<T>(fn: () => Promise<T>, maxRetries: number): Promise<T> {
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try { return await fn(); }
      catch (err: any) {
        const status = err?.status ?? err?.response?.status;
        if (status === 402) throw new Error("OpenRouter credits exhausted (402)");
        const retryable = status === 429 || (status >= 500 && status < 600) || err?.code === "ECONNRESET";
        if (!retryable || attempt === maxRetries - 1) throw err;
        await new Promise((r) => setTimeout(r, Math.min(2 ** attempt * 1000 + Math.random() * 1000, 30_000)));
      }
    }
    throw new Error("OpenRouter call failed after retries");
  }

  async creditsRemaining(): Promise<unknown> { return (this.client as any).get("/key"); }
}
```

### 2.8 Чеклист миграции Gemini/OpenAI → OpenRouter

1. Добавить `OPENROUTER_API_KEY` (BYOK опционально).
2. Заменить конструкцию клиента на `OpenRouterAdapter` (только смена `base_url`).
3. Перевести scoring/offer-промпты на `response_format: json_schema strict` + `require_parameters:true`.
4. Вынести рубрику/политику/каталог офферов в кэшируемый статичный префикс (+ Anthropic `cache_control`).
5. Подключить `models` fallback-массивы из конфига.
6. Добавить gate эскалации cheap→strong на offer-matching.
7. Token-bucket по тиру + 429/5xx backoff (в адаптере) + бюджет-гард `GET /api/v1/key`.
8. Eval-gate перед катовером: прогнать фиксированный набор клипов old vs new, сравнить распределение score и согласованность offer-match.

> **Пинить на build-time:** слаги моделей; путь `models` (OpenAI-compat) vs `fallbacks` (Anthropic `/messages`, ≤3, не комбинируется с `models`); `require_parameters:true` — главный гард JSON.

---

## 3. YouTube: ingest + публикация

> ⚠️ Две недавние перемены переворачивают старые правила: **videos.insert упал ~1600 → ~100 units (2025-12-04)**, и **videos.insert + search.list разнесены по отдельным квота-бакетам (2026-06-01)**.

### 3.1 INGEST (источник длинных видео для нарезки)

Data API v3 **не отдаёт медиа-байты** — только метаданные. Легальный pipeline:

1. `channels.list?part=contentDetails` → playlist `uploads` (1 unit).
2. `playlistItems.list?part=snippet,contentDetails&playlistId={uploads}&maxResults=50` → ID видео (1 unit / 50). `channelId` тут не принимается — нужен playlistId.
3. `videos.list?part=snippet,contentDetails,status&id={ids}` → заголовки, длительности, наличие субтитров, лицензии (1 unit / 50).
4. `captions.download` — единственный ToS-чистый способ получить транскрипт, требует `youtube.force-ssl` и работает **только** на субтитрах, которыми владеет авторизованный пользователь.

> **API никогда не отдаёт байты видео.** Чтобы получить пиксели для нарезки — либо файлы самого автора, либо yt-dlp (ToS-риск).

**Легальность (решительно):**
- YouTube ToS прямо запрещает доступ к контенту иначе, чем через плеер/embed/«явно авторизованные средства» — yt-dlp вне их.
- API ToS отдельно запрещает скачивание/хранение сверх авторизованного. Продукт на yt-dlp-скрейпинге **чужих** каналов = двойное нарушение (платформа + копирайт) и главный экзистенциальный риск.

> **Решение по ingest:** строить только легальный путь — **авторы подключают свой канал по OAuth, FlipHouse тянет их собственные загрузки.** Не предлагать «вставь любой URL — нарежем» через серверный yt-dlp. Для произвольных URL — клиентская сторона + явное заявление прав пользователя.

### 3.2 PUBLISH (загрузка готовых Shorts)

**OAuth 2.0 (Web Server / Authorization Code).** Service accounts **не поддерживаются** (`NoLinkedYouTubeAccount`) — auth всегда per-human-channel.

1. Consent с `access_type=offline` + `prompt=consent` (форсит refresh token).
2. `code` на callback → обмен на `access_token` + **`refresh_token`**.
3. Refresh token хранить зашифрованным (это write-key канала).
4. Минтить короткоживущие access-токены на каждую загрузку.

> ⚠️ В статусе **«Testing» refresh-токены живут 7 дней.** Перевести OAuth consent screen в **«In production»** для бессрочных. Без `prompt=consent` повторная авторизация может не вернуть refresh token.

**Scopes:** `youtube.upload` (минимум для `videos.insert`); `youtube` (управление каналом, `thumbnails.set`); `youtube.force-ssl` (`captions.insert`); `youtubepartner` (только CMS-партнёрам). Все — sensitive/restricted → нужна **OAuth-верификация + brand review** (недели; до неё лимит 100 юзеров и страшный экран).

**`videos.insert`:** resumable upload (`MediaFileUpload(..., resumable=True)`, chunked `next_chunk()`). Эталон — официальный сэмпл `youtube/api-samples/python/upload_video.py` на `google-api-python-client` (8.8k★).
`part=snippet,status`: snippet (`title`, `description`, `tags[]`, `categoryId`), status (`privacyStatus`, `publishAt`, **`selfDeclaredMadeForKids`** — обязательно, иначе COPPA-reject, **`containsSyntheticMedia=true`** для AI-клипов).

> ⚠️ **Audit gate (главная причина reject):** все видео через `videos.insert` из непроверенных API-проектов (созданных после 2020-07-28) **заперты в private**, пока проект не пройдёт **API compliance audit** — это отдельно от OAuth-верификации. Запускать аудит заранее.

**Shorts:** спец-флага в API нет, YouTube классифицирует по файлу (правило 2025-12-08): **9:16 (1080×1920), ≤180 сек.** `#Shorts` в заголовке/описании опционально, но повышает надёжность классификации. Pipeline должен жёстко форсить 9:16 + ≤180с.

### 3.3 Квоты (модель с бакетами, после 2026-06)

| Бакет | Кап | Цена вызова |
|---|---|---|
| `videos.insert` | свой | ~100 units |
| `search.list` | свой | 100 units |
| Всё остальное (reads, thumbnails, captions) | 10 000 units/день | см. ниже |

Reads: `channels.list`=1, `playlistItems.list`=1, `videos.list`=1, `captions.insert`=400, `thumbnails.set`=50.

- **Публикация (теперь дёшево):** 1 Short ≈ 100 units → потолок ~**100 загрузок/день** на free-tier. Снижение Dec-2025 сделало upload-heavy продукты жизнеспособными без запроса квоты.
- **Ingest:** **никогда не делать `search.list` в цикле** (100/день стена). Обход через uploads-playlist (`playlistItems.list` = 1 unit) → ~10 000 страниц/день ≈ 500k видео. Дёшево.

### 3.4 Anti-rejection чеклист (YouTube)

1. **Пройти API compliance audit до публичного запуска** — иначе все загрузки молча private. №1 причина «видео исчезли».
2. **OAuth consent screen → «In production»** (иначе refresh-токены мрут за 7 дней); запрашивать только нужные scopes.
3. **Всегда явно `selfDeclaredMadeForKids`**; **`containsSyntheticMedia=true`** для AI-клипов.
4. **Resumable upload** chunked — иначе таймауты и сгорание квоты на ретраях.
5. **9:16 + ≤180с + `#Shorts`** на этапе энкода.
6. Различать `uploadLimitExceeded` (дневной кап канала) и `quotaExceeded`; backoff; квота сбрасывается в полночь Pacific.
7. **Ingest только авторизованных каналов** — не серверный yt-dlp чужого контента.
8. **Не `search.list` в цикле** — 100/день стена; обход uploads-playlist.

---

## 4. TikTok + Instagram: публикация

### 4.1 TikTok Content Posting API

**Потоки:** Direct Post (сразу в профиль; `POST /v2/post/publish/video/init/`) и Upload/Inbox (черновик в инбокс, юзер допостит в приложении — ниже compliance-нагрузка). **Source:** `FILE_UPLOAD` (chunked в `upload_url`, валиден 1ч) или `PULL_FROM_URL` (TikTok тянет с **верифицированного домена** — случай FlipHouse). Статус: `POST /v2/post/publish/status/fetch/`. **Обязательный pre-post вызов:** `POST /v2/post/publish/creator_info/query/` → nickname, `privacy_level_options`, `max_video_post_duration_sec`, доступность комментов/duet/stitch, лимиты.

**Аудит:** до аудита клиент — **5 юзеров/24ч, все посты `SELF_ONLY`, аккаунты private**. Полная публичность только после **TikTok audit** — gate, без которого публичная публикация невозможна.

**Rate limits:** **6 req/min на user access_token**; дневной кап → `403 spam_risk_too_many_posts`; client-wide кап активных юзеров → `403 reached_active_user_cap`. Точные числа не публикуются → backoff, не фикс-число.

**OAuth/токены:** Authorization Code + **PKCE**. Token endpoint `POST https://open.tiktokapis.com/v2/oauth/token/`. **access_token 24ч**, **refresh_token 365 дней**. При refresh **refresh_token может ротироваться — всегда сохранять новый**. Scope `video.publish` (+ `user.info.basic`).

> ⚠️ **Watermark/контент (hard reject):** запрещены бренд-нейм, логотип, водяной знак, промо-текст, ссылки, вжатые в контент → удаление контента / блок аккаунта. **№1 причина авто-флага.** FlipHouse обязан срезать чужой watermark (CapCut и т.п.) и **не вжигать собственный брендинг.** `is_aigc=true` обязателен для AI-контента.

**Обязательный UX (иначе провал аудита):** превью перед постом; явное одобрение создателя; **никаких preset/locked** заголовков/хэштегов (все поля редактируемы, тогглы interaction по умолчанию off); показ nickname получателя; читать `creator_info` первым и блокировать при достижении лимитов. Commercial disclosure по умолчанию OFF; branded content **не может быть `SELF_ONLY`**.

### 4.2 Instagram Graph API (Reels)

**Аккаунт:** только Instagram professional (Business/Creator). Логин: **Instagram Login** (рекомендуется; scopes `instagram_business_basic` + `instagram_business_content_publish`, host `graph.instagram.com`) или **Facebook Login** (IG привязан к Page; `instagram_basic` + `instagram_content_publish` + `pages_read_engagement`; может требовать PPA).

**Поток (3 шага):**
1. `POST /<IG_ID>/media` с `media_type=REELS`, `video_url` (публично хостится) или resumable upload; опц. `caption`, `cover_url`, `thumb_offset`, `share_to_feed`.
2. (resumable) загрузка байтов `POST https://rupload.facebook.com/ig-api-upload/<CONTAINER_ID>`.
3. Poll `GET /<CONTAINER_ID>?fields=status_code` до `FINISHED` → `POST /<IG_ID>/media_publish` с `creation_id`.

**Лимиты:** **100 публикаций/24ч** на аккаунт (`GET /<IG_ID>/content_publishing_limit`); контейнер **истекает за 24ч**; **макс 400 контейнеров/24ч**.

**Токены:** short-lived **1ч** → long-lived **60 дней** (`ig_exchange_token`); refresh `ig_refresh_token` (токен ≥24ч от роду, **истекает навсегда если не обновить за 60 дней**).

**Медиа:** длительность 3–90с (5–90с для вкладки Reels); MOV/MP4, **moov atom впереди**, H.264/HEVC, 23–60 FPS, AAC ≤48kHz; **9:16 1080×1920**; до 4GB (надёжнее <500MB). Медиа должно быть публично доступно на момент публикации.

### 4.3 ANTI-BLOCK / ANTI-SHADOWBAN чеклист (обе платформы)

Главные причины флага авто-постинга: **платформенные watermark, устаревшая/дублирующая метадата, бот-подобный ритм.**

**Fingerprint контента**
- [ ] **Срезать ВСЕ сторонние watermark** (CapCut, TikTok-export, IG-download). TikTok-watermark на Instagram (и наоборот) — главный кросс-пост суппрессор.
- [ ] **Не вжигать брендинг FlipHouse, логотипы, ссылки, промо-текст** (TikTok удаляет контент/блокирует, IG режет охват).
- [ ] **Транскодировать per-platform** (хэши файлов разные, спеки нативные: 9:16 1080×1920, moov-front для IG; MP4/H.264 для TikTok). Не постить байт-идентичный файл в обе.
- [ ] **Свежая метадата per-platform** — уникальная подпись, уникальные первые 3 слова, нативные хэштеги. Никогда не слать идентичные caption в обе API.
- [ ] `is_aigc=true` (TikTok) и AI-лейбл (IG) для AI-контента. Неверная маркировка AIGC — вектор флага.

**Human-in-the-loop (и требование аудита TikTok)**
- [ ] Обязательное **превью + явное одобрение** до любого post-вызова — никогда silent auto-post на TikTok.
- [ ] Все поля caption/хэштеги/privacy/interaction **редактируемы**, ничего preset/locked.
- [ ] Показ аккаунта-получателя (TikTok nickname / IG username).

**Ритм и лимиты**
- [ ] TikTok **6 req/min/user**; обрабатывать `403 spam_risk_*` / `reached_active_user_cap` с backoff.
- [ ] Pre-flight `creator_info` каждый пост; abort + retry-prompt при лимитах.
- [ ] IG **100 постов/24ч** и **400 контейнеров/24ч**; poll `content_publishing_limit` перед публикацией.
- [ ] **Jitter-планирование** (рандомные минутные оффсеты) вместо burst-постинга круглыми числами.
- [ ] Poll `status_code`/`status/fetch` до `FINISHED`/успеха перед объявлением «опубликовано»; ошибки показывать юзеру.

**Auth / гигиена аккаунта**
- [ ] TikTok: сохранять **ротированный refresh_token** при каждом refresh; PKCE.
- [ ] IG: авто-refresh long-lived (60д) до истечения; один IG-professional на коннект; PPA при Facebook Login.
- [ ] Верифицировать домен для TikTok `PULL_FROM_URL`; IG-медиа на стабильном публичном URL до завершения публикации.
- [ ] Никогда не встраивать `client_secret` на клиенте/в публичном репо (явное правило безопасности TikTok).

**Pre-launch gating**
- [ ] **TikTok audit** до прода — иначе 5 юзеров/24ч и `SELF_ONLY`.
- [ ] **Meta App Review** на `instagram_business_content_publish` до запуска.

> **Только официальные API.** Никаких неофициальных/реверс-инженеренных эндпоинтов: они нарушают ToS, ломаются и ведут к блокировке аккаунтов. Direct-API + аудит — единственный shippable путь.

---

## 5. Мультиплатформенная модель OAuth/токенов

### 5.1 Несовместимые модели refresh (драйвер всей архитектуры)

| Платформа | Publish-scope(s) | TTL access | Модель refresh |
|---|---|---|---|
| **YouTube** (Google OAuth2) | `youtube.upload` | ~1ч | Стандартный `refresh_token` (долгоживущий). Получить только при `access_type=offline` + `prompt=consent`. Потеря = полный re-consent. |
| **TikTok** | `video.publish` | **24ч** | `grant_type=refresh_token`; refresh **365 дней**. Ответ **может вернуть НОВЫЙ refresh_token — сохранять его.** |
| **Instagram** | `instagram_business_basic` + `..._content_publish` | short 1ч / **long 60 дней** | Не классический refresh. `GET /refresh_access_token?grant_type=ig_refresh_token`; токен ≥24ч; **истекает навсегда** если не обновить за 60 дней. |

> Три модели фундаментально несовместимы (OAuth2-grant vs sliding-window self-refresh vs approval-gated rotating). Наивная «одна refresh-функция» ломается на всех трёх — архитектура обязана это абсорбировать.

### 5.2 Решение 1: Login ≠ Connections

Не путать «вход в FlipHouse» и «подключить YouTube-канал» — разные lifecycle, scopes, отказы.

- **Login** → **Auth.js (NextAuth v5)** с минимальными scopes (Google login = только `openid email profile`, **не** `youtube.upload`). Использовать только для identity/session.
- **Social connections** → **отдельный hand-rolled OAuth-поток per-platform**, токены в **своей зашифрованной таблице**, НЕ в `accounts` Auth.js.

> Auth.js `accounts` моделирует «один провайдер = identity логина», не «3 TikTok + 2 YouTube», не шифрует токены по умолчанию, его refresh — ручной workaround, не подходящий под ротацию TikTok / sliding-window IG. Auth.js для сессий; токены коннектов — свои.

### 5.3 Решение 2: Direct vs Aggregator (Ayrshare)

**Рекомендация: старт на Ayrshare Business Plan; publish-слой за интерфейсом `PublishProvider` для последующего свопа на direct.**

- TikTok `video.publish` и IG content-publishing **требуют platform app review** (особенно TikTok — медленно, легко ошибиться). Ayrshare уже одобрен → недели ревью + ongoing token-refresh сжимаются в дни.
- Три несовместимые refresh-модели становятся проблемой **Ayrshare**: per-user Profiles + Profile Keys, JWT для линковки, токены и refresh держит Ayrshare; один `/post` с `platforms: ["youtube","tiktok","instagram"]`.
- Цена — per-profile SaaS-fee + вендор-зависимость. **Direct** включать при потолке цены/масштаба или нужде в фичах, недоступных через Ayrshare.

> Итог: **строить абстракцию сейчас, бэкать Ayrshare сегодня, держать direct-OAuth как вторую реализацию того же интерфейса.** Модель ниже поддерживает оба: `AGGREGATOR` хранит profile-ref, `DIRECT` хранит зашифрованные токены.

### 5.4 Архитектура

```text
Next.js (App Router)
 ┌───────────────┐      ┌──────────────────────────────┐
 │ Auth.js v5    │      │ Connection Flow (свои роуты)  │
 │ SESSION ONLY  │      │ /connect/[platform]/start     │
 │ Google/email  │      │ /connect/[platform]/callback  │
 └──────┬────────┘      └───────────────┬──────────────┘
        │ user.id (session)             │
        ▼                               ▼
 ┌────────────────────────────────────────────────────┐
 │  Connection Service                                 │
 │  createConnection / revoke / list                   │
 │  getValidAccessToken(connectionId)  ◄── core API    │
 └───────┬─────────────────────────────────┬───────────┘
         ▼                                  ▼
  ┌─────────────┐                  ┌──────────────────┐
  │ TokenVault  │                  │ PublishProvider  │ (интерфейс)
  │ AES-256-GCM │                  │  AyrshareProv ◄ сегодня
  │ KMS DEK     │                  │  YouTubeDirect ◄ позже
  └─────────────┘                  │  TikTokDirect / InstagramDir
                                   └──────────────────┘
   Postgres (зашифр. токены)        Refresh Worker (cron)
                                    per-platform стратегии
```

**Connect** (`/connect/[platform]/start`): сгенерить `state` (CSRF, подписан, короткий TTL, привязан к `user.id`) + PKCE `code_verifier` (сервер-сайд по `state`); редирект на authorize **только с publish-scopes этой платформы**; callback валидирует `state`, обменивает code, нормализует токен в модель, шифрует, пишет новую строку `social_connection`. Юзер держит N коннектов на платформу — единица учёта строка, не юзер.

**Publish** (`publishClip({ clipId, connectionIds })`): на каждый коннект → `PublishProvider` → `provider.publish(...)`; через `getValidAccessToken()` (ленивый refresh); результат per-target → частичный отказ first-class.

**`getValidAccessToken(connectionId)` — функция, через которую идёт всё:**
1. Дешифровать; если `expires_at` >5 мин → вернуть.
2. Иначе — диспатч в refresh-стратегию платформы (различаются).
3. Сохранить новый access, новый `expires_at`, **и возможно ротированный refresh** (критично для TikTok).
4. При отказе → `status = 'reauth_required'`, показать в UI. Никогда silent swallow.

### 5.5 Модель данных токенов (Prisma)

```prisma
// Auth.js владеет: User, Account, Session, VerificationToken (минимальные scopes)
// FlipHouse владеет публикацией:

enum Platform { YOUTUBE TIKTOK INSTAGRAM }
enum ConnectionStatus { ACTIVE REAUTH_REQUIRED REVOKED EXPIRED }
enum ProviderKind { DIRECT AGGREGATOR }   // DIRECT: токены у нас; AGGREGATOR: у Ayrshare

model SocialConnection {
  id            String   @id @default(cuid())
  userId        String                          // FK -> User.id
  platform      Platform
  providerKind  ProviderKind @default(AGGREGATOR)

  platformAccountId   String     // YouTube channelId / TikTok open_id / IG user id
  platformAccountName String?    // @handle / channel title (display)
  avatarUrl           String?
  grantedScopes       String[]   // аудит минимизации + capability-checks
  status        ConnectionStatus @default(ACTIVE)

  // DIRECT: зашифрованный токен-материал (null в AGGREGATOR)
  encAccessToken    Bytes?      // AES-256-GCM ciphertext
  encAccessIv       Bytes?
  encAccessTag      Bytes?
  encRefreshToken   Bytes?      // TikTok ротирует при каждом refresh
  encRefreshIv      Bytes?
  encRefreshTag     Bytes?
  encKeyVersion     Int?        // версия KMS master-key (ротация без re-encrypt)

  accessTokenExpiresAt   DateTime?   // драйвит ленивый refresh (5-мин skew)
  refreshTokenExpiresAt  DateTime?   // TikTok 365д; null где N/A
  // Instagram: refresh_token НЕТ. encAccessToken = long-lived токен,
  // accessTokenExpiresAt = issued+60д, refresh in-place через ig_refresh_token.
  lastRefreshedAt        DateTime?

  // AGGREGATOR: ссылка Ayrshare (null в DIRECT)
  aggregatorProfileKey   String?   // Ayrshare Profile Key (секрет -> шифровать)
  aggregatorRef          String?   // id связанного аккаунта в Ayrshare

  createdAt  DateTime @default(now())
  updatedAt  DateTime @updatedAt
  publishTargets PublishTarget[]

  @@unique([userId, platform, platformAccountId])  // нет дублей коннектов
  @@index([status, accessTokenExpiresAt])          // скан refresh-воркера
}

model PublishJob {
  id        String   @id @default(cuid())
  userId    String
  clipId    String
  caption   String?
  status    String   @default("pending")   // pending|running|partial|done|failed
  createdAt DateTime @default(now())
  targets   PublishTarget[]
}

model PublishTarget {
  id             String   @id @default(cuid())
  jobId          String
  connectionId   String
  platform       Platform
  status         String   @default("pending") // pending|uploading|published|failed
  platformPostId String?
  errorCode      String?
  errorMessage   String?
  attempts       Int      @default(0)
  job            PublishJob       @relation(fields: [jobId], references: [id])
  connection     SocialConnection @relation(fields: [connectionId], references: [id])
  @@index([jobId])
}
```

**Почему так:** коннект (не юзер) — единица → `@@unique([userId, platform, platformAccountId])` даёт несколько каналов/аккаунтов · `providerKind` — дискриминатор Ayrshare-сегодня / direct-позже · раздельные expiry-колонки абсорбируют три модели (IG кодируется конвенцией) · `encKeyVersion` — ротация master-key без bulk re-encrypt · `PublishTarget` per-platform → частичный успех по умолчанию с per-target retry.

### 5.6 Минимизация scopes (enforced)

- **Login scopes ≠ publish scopes.** Google login = `openid email profile`. YouTube-коннект отдельно просит `youtube.upload` — никогда широкий `youtube` и не на логине.
- **TikTok:** только `video.publish` (или `video.upload` для draft-only).
- **Instagram:** только `instagram_business_basic` + `instagram_business_content_publish`.
- Хранить `grantedScopes`, проверять capability перед публикацией → ясное «переподключитесь с правами публикации» вместо сырого 403.

### 5.7 Refresh-воркер (per-platform стратегии за одним интерфейсом)

Cron-воркер сканирует `@@index([status, accessTokenExpiresAt])`, диспатчит:
- **YouTube:** стандартный OAuth2 refresh-grant; нет captured `refresh_token` → `REAUTH_REQUIRED` сразу, не притворяться.
- **TikTok:** refresh против `open.tiktokapis.com/v2/oauth/token/`; **всегда сохранять ротированный refresh_token** + обновлять `refreshTokenExpiresAt` (365д → nudge на reconnect заранее).
- **Instagram:** нет refresh-grant; таймер-джоб вызывает `graph.instagram.com/refresh_access_token` на токенах >24ч задолго до 60-дневной стены (~день 30–50); пропуск окна → `EXPIRED`, полный reconnect.
- **Aggregator (Ayrshare):** ничего — refresh upstream, воркер пропускает AGGREGATOR-строки.

### 5.8 Рекомендации библиотек

| Задача | Выбор |
|---|---|
| Login / сессии | Auth.js (NextAuth v5) + Prisma adapter, минимальные scopes |
| Мульти-аккаунт коннекты | Свой OAuth-поток + `SocialConnection` (не перегружать `accounts` Auth.js) |
| Публикация (фаза 1) | Ayrshare Business Plan за `PublishProvider` |
| Публикация (фаза 2) | Direct YouTube / TikTok / Instagram — тот же интерфейс, своп per-platform |
| Шифрование токенов | AES-256-GCM envelope encryption + KMS master-key + `encKeyVersion` |

> **Сквозная линия:** разделить identity и публикацию; сделать коннект (не юзера) единицей; спрятать три несовместимые refresh-модели за `getValidAccessToken()` и `PublishProvider`; отдать lifecycle токенов Ayrshare до момента, когда масштаб/фичи оправдают direct.

---

## Источники (проверено, июнь 2026)

**PWA:** [Next.js PWA guide](https://nextjs.org/docs/app/guides/progressive-web-apps) · [Serwist](https://serwist.pages.dev/docs/next/getting-started) · [serwist/serwist](https://github.com/serwist/serwist) · [web-push](https://github.com/web-push-libs/web-push) · [MagicBell iOS limitations](https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide) · [Pushpad iOS](https://pushpad.xyz/blog/ios-special-requirements-for-web-push-notifications)
**OpenRouter:** [Quickstart](https://openrouter.ai/docs/quickstart) · [App Attribution](https://openrouter.ai/docs/app-attribution) · [Model Fallbacks](https://openrouter.ai/docs/guides/routing/model-fallbacks) · [Provider Routing](https://openrouter.ai/docs/guides/routing/provider-selection) · [Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs) · [Prompt Caching](https://openrouter.ai/docs/guides/best-practices/prompt-caching) · [Rate Limits](https://openrouter.ai/docs/api/reference/limits)
**YouTube:** [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert) · [quota costs](https://developers.google.com/youtube/v3/determine_quota_cost) · [revision history](https://developers.google.com/youtube/v3/revision_history) · [authentication](https://developers.google.com/youtube/v3/guides/authentication) · [Shorts 3-min](https://support.google.com/youtube/answer/15424877) · [upload_video.py](https://github.com/youtube/api-samples/blob/master/python/upload_video.py)
**TikTok/Instagram:** [TikTok Content Posting](https://developers.tiktok.com/doc/content-posting-api-get-started) · [TikTok sharing guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines) · [TikTok OAuth](https://developers.tiktok.com/doc/oauth-user-access-token-management) · [IG Content Publishing](https://developers.facebook.com/docs/instagram-platform/content-publishing) · [IG media ref](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/) · [IG refresh_access_token](https://developers.facebook.com/docs/instagram-platform/reference/refresh_access_token/)
**OAuth/Aggregator:** [Auth.js providers](https://authjs.dev/getting-started/providers) · [Ayrshare docs](https://www.ayrshare.com/docs/) · [Ayrshare Business Plan](https://www.ayrshare.com/docs/multiple-users/business-plan-overview)
