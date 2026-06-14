# FlipHouse — ROADMAP (мастер-индекс сборки)

> Это **корневой индекс** всего строительства FlipHouse. Он не содержит шагов реализации — только карту фаз, граф зависимостей и глобальные правила. Каждая фаза живёт отдельным файлом в [`roadmap/`](./roadmap/) и исполняется атомарно.

---

## 1. Видение продукта

FlipHouse — это AI-конвейер, который превращает одно длинное видео (загруженное drag&drop или вставкой ссылки) в набор готовых к публикации вертикальных вирусных клипов 9:16 (1080×1920) с karaoke-субтитрами, speaker-tracking reframe и **детерминированно вставленным рекламным баннером** из оффера рекламодателя, после чего автоматически публикует их в YouTube/TikTok/Instagram и учитывает показы для двусторонних выплат creator↔advertiser. По сути это self-serve двусторонний маркетплейс поверх медиа-рендер-движка: креаторы монетизируют контент, рекламодатели покупают нативные интеграции, а платформа гарантирует geometry-safe вставку, anti-block публикацию и честную атрибуцию просмотров.

---

## 2. Как пользоваться этим роудмапом через ultracode

Этот роудмап спроектирован под **автономного исполнителя (ultracode)**, который ведёт сборку фаза-за-фазой:

1. **Фазы идут строго по порядку зависимостей.** Открой эту таблицу (§3) и граф (§4), выбери первую незакрытую фазу, у которой все `depends_on` уже зелёные.
2. **Каждая фаза — отдельный файл** в [`roadmap/`](./roadmap/). Внутри файла фаза разбита на **атомарные шаги**. Один шаг = один логический инкремент = один коммит.
3. **Каждый шаг исполняется через строгий TDD:** `RED` (пишем падающий тест) → `GREEN` (минимальная реализация, тест зелёный) → `refactor` → `commit`. Не переходи к следующему шагу, пока текущий не зелёный.
4. **После каждого шага обновляй [`STATE.md`](./STATE.md):** какая фаза, какой шаг, статус тестов, покрытие, что осталось. STATE.md — единственный источник истины о прогрессе; именно его читает следующая сессия, чтобы продолжить «на холодную».
5. **Останавливайся на 🛑 ЧЕКПОИНТАХ.** Чекпоинты (колонка в §3 и метки внутри файлов фаз) — это точки обязательного ревью основателя. На чекпоинте исполнитель **не продолжает сам** — он фиксирует состояние, отчитывается и ждёт «go».
6. **Полный операционный протокол** (формат коммитов, формат STATE-записей, правила остановки, что делать при красном CI) — в [`EXECUTION-PROTOCOL.md`](./EXECUTION-PROTOCOL.md). Читай его перед началом любой фазы.

---

## 3. Таблица фаз

| ID | Название | Цель (кратко) | Зависит от | Шагов | Файл | Чекпоинты |
|----|----------|---------------|------------|:-----:|------|-----------|
| **P0** | Bootstrap: монорепо, CI, тест-харнесс, vendor | pnpm-монорепо + строгий тулинг + полный тест-харнесс (Vitest/Playwright/pytest, coverage ≥80% роняет билд) + CI fail-fast + завендорить 11 upstream-репо по SHA. Только леса, бизнес-кода нет. | — | 13 | [P0-bootstrap-test-harness.md](./roadmap/P0-bootstrap-test-harness.md) | A: структура+TS-тулинг · B: shared зелёный + coverage-гейт роняет билд · C: golden-video assertion-контракт · D: web Playwright smoke + worker Vitest · E: /vendor 11 репо + PINS.lock · F: CI блокирует красный PR + branch protection |
| **P1** | Веб-каркас: auth, биллинг, лендинг с hero-дропзоной | Форк SaaS-Boilerplate (Next.js + Clerk + Stripe + Drizzle) на Railway, creator/advertiser RBAC, dark AI-tech лендинг с hero-дропзоной (Kibo + AI Elements над shadergradient), scroll-сторителлинг. | P0 | 17 | [P1-web-auth-billing-landing.md](./roadmap/P1-web-auth-billing-landing.md) | A: форк поднят, тесты зелёные · B: oklch-токены + dark-тема · C: hero-дропзона все состояния · D: лендинг целиком · E: 2 типа аккаунта + онбординг · F: Stripe checkout + webhook · G: staging deploy, e2e зелёные |
| **P2** | Загрузка + AI-нарезка MVP (openshorts + OpenRouter) | CPU-путь: tusd→R2→hook→BullMQ Flow-DAG (validate→transcode→asr→score→clip→store)→ранжированные клипы 9:16. Gemini-выбор свопнут на OpenRouter (json_schema strict). GPU-стадии под PHASE3-флагом с CPU-fallback. | P0 | 14 | [P2-upload-clipping-mvp.md](./roadmap/P2-upload-clipping-mvp.md) | A: OpenRouter-адаптер · B: Python-движок на golden-фикстуре · C: Flow-DAG (порядок/идемпотентность) · D: tusd→R2→hook · E: E2E дашборд (видео→ранжированные клипы) |
| **P3** | Субтитры + speaker-tracking reframe (captacity + LR-ASD) | reframe (LR-ASD на Modal-GPU → planner EMA+min-hold → FFmpeg-crop 1080×1920) + caption (karaoke строго в caption_band) + safe_zones.json CI-инвариант (caption_band ⊂ content_safe ∧ ∩ banner = ∅). | P0, P1, P2 | 15 | [P3-captions-reframe.md](./roadmap/P3-captions-reframe.md) | A: safe_zones.json + CI-инвариант · B: golden-frame ноль пикселей в баннере · C: ASD→crop→video · D: Modal submit-and-park + HMAC · E: e2e финальный клип + субтитры + crop из ASD |
| **P4** | Движок офферов + вставка баннера | JSON Schema 2020-12 оффера + Ajv, 5-шаговый advertiser intake, fail-closed brand-safety гейт, rules-engine plan()→PlacementPlan с AABB collision avoidance, injection-hardened FFmpeg overlay-кодоген + MoviePy fallback, попиксельный render-assertion. Heaviest-TDD; ядро ≥95%. | P0, P1, P2 | 17 | [P4-offer-engine-banner.md](./roadmap/P4-offer-engine-banner.md) | A: схема + валидатор · B: intake form · C: brand-safety fail-closed · D: rules-engine golden · E: FFmpeg-вставка end-to-end |
| **P5** | Маркетплейс креатор↔реклама + учёт показов/выплаты | Self-serve двусторонний маркетплейс: оффер→apply→match→impression_unit→рендер с баннером→конверсия→cliq Commission→Stripe Connect payout. Идемпотентный usage/metered billing. Attribution v1 по дельтам просмотров. | P0, P1, P2, P4 | 26 | [P5-marketplace-attribution.md](./roadmap/P5-marketplace-attribution.md) | ЧП-1: схема БД + валидатор · ЧП-2: каталог + brand-safety · ЧП-3: browse/apply/match · ЧП-4: acceptance + input_hash · ЧП-5: рендер с оффером · ЧП-6: cliq Commission (4 модели) · ЧП-7: Stripe usage идемпотентность · ЧП-8: attribution v1 · ЧП-9: Stripe Connect payout · ЧП-10: e2e + ≥80% |
| **P6** | Публикация (YT/TikTok/IG анти-блок) + OAuth + PWA + push | Identity (Auth.js v5) отдельно от публикационных коннектов (AES-256-GCM SocialConnection), getValidAccessToken прячет 3 refresh-модели, PublishProvider (Ayrshare + direct), enforced анти-блок чеклист, PWA на Serwist + web-push «нарезки готовы». | P0, P1, P2 | 24 | [P6-publishing-pwa.md](./roadmap/P6-publishing-pwa.md) | A: Token Vault + getValidAccessToken · B: Connect-флоу YT/TikTok/IG (PKCE/CSRF) · C: анти-блок transform-слой · D: PublishProvider+Ayrshare e2e · E: PWA + web-push на staging · F: Direct-провайдеры + аудит-гейтинг |
| **P7** | Trust-слой (verified views), масштаб, харднинг, релиз-гейты | Trust verified-views (Δviews × visibility → billable → charge + anomaly-detection + cross-source аудит), масштаб/харднинг (GPU-quota guard, BullMQ backpressure, R2 lifecycle, observability, rate-limit, nonce-CSP), релиз-гейт как CI-блокер + go-live чеклист. | P0, P1, P2, P4, P5, P6 | 16 | [P7-trust-scale-hardening.md](./roadmap/P7-trust-scale-hardening.md) | A: метеринг-математика · B: anomaly-detection пороги · C: cross-source аудит · D: GPU-quota guard под нагрузкой · E: security surface · F: релиз-гейт CI-блокер · G: go-live чеклист + OAuth-аудиты |

**Итого: 8 фаз, 142 атомарных шага, 6+ founder-чекпоинтов на критических фазах.**

---

## 4. Граф зависимостей

```text
                                  ┌──────────────────────────────┐
                                  │  P0  Bootstrap / Test-Harness │  (фундамент, нет зависимостей)
                                  │  монорепо · CI · vendor · TDD │
                                  └───────────────┬──────────────┘
                                                  │
                 ┌────────────────────────────────┼────────────────────────────────┐
                 │                                 │                                 │
                 ▼                                 ▼                                 │
        ┌─────────────────┐               ┌─────────────────┐                       │
        │  P1  Веб-каркас │               │  P2  Загрузка + │                       │
        │  auth·billing·  │               │  AI-нарезка MVP │                       │
        │  landing        │               │  (CPU-путь)     │                       │
        └────────┬────────┘               └───┬─────────┬───┘                       │
                 │                            │         │                           │
                 │   ┌────────────────────────┘         │                           │
                 │   │                                  │                           │
                 ▼   ▼                                  ▼                           ▼
        ┌─────────────────┐                   ┌──────────────────┐        (P6 зависит только
        │ P3 Субтитры +   │                   │ P4 Движок офферов │         от P0·P1·P2 —
        │ reframe         │                   │ + вставка баннера │         публикация не ждёт
        │ (P0·P1·P2)      │                   │ (P0·P1·P2)        │         баннер/маркетплейс)
        └─────────────────┘                   └─────────┬────────┘                  │
            (тупиковая ветка:                           │                           │
             не блокирует P5/P6/P7,                      ▼                           │
             но нужна для качества клипа)      ┌──────────────────┐                  │
                                              │ P5 Маркетплейс +  │                  │
                                              │ attribution       │◄─────────────────┤
                                              │ (P0·P1·P2·P4)     │                  │
                                              └─────────┬────────┘                   │
                                                        │            ┌───────────────┘
                                                        ▼            ▼
                                              ┌──────────────────────────────┐
                                              │ P6 Публикация + OAuth + PWA   │
                                              │ (P0·P1·P2)                    │
                                              └──────────────┬───────────────┘
                                                             │
                                                             ▼
                                              ┌──────────────────────────────┐
                                              │ P7 Trust · Scale · Hardening  │
                                              │ Release-Gate                  │
                                              │ (P0·P1·P2·P4·P5·P6)           │
                                              └──────────────────────────────┘
```

**Что можно параллелить:**
- После **P0** ветки **P1** и **P2** независимы — их можно вести параллельно двумя потоками.
- **P3** (субтитры/reframe) и **P4** (офферы/баннер) оба зависят от `P0·P1·P2`, но **друг от друга не зависят** → параллельны. P3 — тупиковая ветка качества клипа, она не блокирует P5/P6/P7 на уровне зависимостей.
- **P6** (публикация) зависит только от `P0·P1·P2`, поэтому может идти **параллельно с P4 и P5** — публикация готового клипа не ждёт движок баннера.

**Критический путь к go-live:** `P0 → P2 → P4 → P5 → P7` (P7 дополнительно ждёт P6). Это самая длинная цепочка; на ней нет распараллеливания, и именно она определяет дату релиза.

---

## 5. Глобальные правила (founder-rule: ZERO bugs)

Эти правила действуют на **каждом шаге каждой фазы** и имеют приоритет над удобством.

1. **ZERO bugs через строгий TDD.** Любой шаг начинается с падающего теста (`RED`), затем минимальная реализация (`GREEN`), затем рефактор. Тест пишется *до* кода, а не после. Нет теста — нет кода.
2. **Ничего не «готово» без зелёных тестов.** Шаг считается завершённым только когда: все unit/integration/e2e тесты зелёные **и** покрытие проходит гейт. «Работает локально руками» ≠ готово.
3. **Coverage-гейты роняют билд.** Глобальный порог **≥80%**; на детерминированных доменных ядрах (rules-engine P4, attribution/commission P5, доменные модули P6) — **≥95%**. Гейт настраивается *up front* в P0 и реально проваливает CI, а не просто печатает число.
4. **CI fail-fast блокирует merge.** Красный тест или просадка покрытия = красный PR = merge запрещён branch-protection'ом. Нельзя «домержить и починить потом».
5. **Детерминизм критических ядер.** Геометрия (safe-zones, AABB collision), биллинг (impression_unit, commission, usage-metering) и атрибуция должны быть детерминированными и покрыты golden-тестами; одинаковый вход → одинаковый `input_hash` → одинаковый выход.
6. **Идемпотентность по content-hash везде.** Загрузка, стадии DAG, рендер, метеринг и payout не должны задваивать эффекты на ретрае. Это инвариант, а не оптимизация.
7. **Fail-closed на security-гейтах.** Brand-safety и injection-hardening: при исключении/неоднозначности система **запрещает**, а не пропускает. Никаких `'unsafe-inline'`, FFmpeg только через argv/`-filter_complex_script`, никогда через строковую интерполяцию.
8. **Лицензии не блокируют.** Все 11 upstream-репозиториев вендорятся в `/vendor` с пинами по SHA и правовой разметкой (`PINS.lock` + лицензии) ещё в P0. Используются совместимые лицензии; ни одна зависимость не должна юридически блокировать коммерческий запуск. Если репо несовместим — он портируется/заменяется, а не тащится как есть.
9. **Останов на 🛑 чекпоинтах обязателен.** Исполнитель не проскакивает founder-ревью ради скорости. На чекпоинте — стоп, отчёт, ожидание «go».
10. **STATE.md обновляется после каждого шага.** Прогресс без записи в STATE = потерянный прогресс.

---

## 6. Ссылки

**Управляющие документы сборки:**
- [ROADMAP.md](./ROADMAP.md) — этот мастер-индекс фаз (вы здесь).
- [STATE.md](./STATE.md) — живой статус прогресса: текущая фаза/шаг, тесты, покрытие, что дальше. Обновляется после каждого шага.
- [EXECUTION-PROTOCOL.md](./EXECUTION-PROTOCOL.md) — операционный протокол исполнителя: формат коммитов, формат STATE-записей, правила остановки на чекпоинтах, поведение при красном CI.

**Файлы фаз:**
- [roadmap/P0-bootstrap-test-harness.md](./roadmap/P0-bootstrap-test-harness.md)
- [roadmap/P1-web-auth-billing-landing.md](./roadmap/P1-web-auth-billing-landing.md)
- [roadmap/P2-upload-clipping-mvp.md](./roadmap/P2-upload-clipping-mvp.md)
- [roadmap/P3-captions-reframe.md](./roadmap/P3-captions-reframe.md)
- [roadmap/P4-offer-engine-banner.md](./roadmap/P4-offer-engine-banner.md)
- [roadmap/P5-marketplace-attribution.md](./roadmap/P5-marketplace-attribution.md)
- [roadmap/P6-publishing-pwa.md](./roadmap/P6-publishing-pwa.md)
- [roadmap/P7-trust-scale-hardening.md](./roadmap/P7-trust-scale-hardening.md)

**Проектные документы (контракты и спецификации):**
- [docs/00-MASTER-FlipHouse.md](./docs/00-MASTER-FlipHouse.md) — мастер-обзор продукта.
- [docs/01-АРХИТЕКТУРА-И-RAILWAY.md](./docs/01-АРХИТЕКТУРА-И-RAILWAY.md) — архитектура, сервисы, деплой на Railway.
- [docs/02-ДИЗАЙН-И-МОУШЕН.md](./docs/02-ДИЗАЙН-И-МОУШЕН.md) — дизайн-система, токены, моушен, лендинг.
- [docs/03-ОФФЕРЫ-И-ВСТАВКА-РЕКЛАМЫ.md](./docs/03-ОФФЕРЫ-И-ВСТАВКА-РЕКЛАМЫ.md) — схема оффера, rules-engine, маркетплейс, attribution.
- [docs/04-ИНТЕГРАЦИИ-PWA-AI-ПУБЛИКАЦИЯ.md](./docs/04-ИНТЕГРАЦИИ-PWA-AI-ПУБЛИКАЦИЯ.md) — OpenRouter-роутинг, публикация, PWA, push.
