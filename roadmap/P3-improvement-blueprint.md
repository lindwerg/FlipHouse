# P3 — Captions + Reframe: Improvement Blueprint

> База: blueprint «quality-ceiling» (визуальный потолок Submagic/Opus июнь-2026 = заявленная founder'ом приоритетная ось №1).
> Графты: весь reliability+speed-субстрат из «reliability-speed» + YAGNI/упаковка из «mvp-fast».
> Две принудительные коррекции JUDGE: (1) CTC forced-alignment поднят из DEFER в первоклассный шаг; (2) реестр пресетов урезан с 5–8 до ОДНОГО флагманского RU-look + максимум 1–2 выразительных.
> **РЕВИЗИЯ после adversarial-прохода (4 линзы, 11 CRITICAL/HIGH-блокеров).** Несколько шагов были мис-специфицированы против РЕАЛЬНОЙ render-архитектуры (статичный per-segment crop, libass per-word events, двойной ASD-путь). Все блокеры применены — см. §0.

Все пути реальны: корень `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/`.

---

## 0. Поправки после adversarial-прохода

11 блокеров (4 CRITICAL/HIGH-линзы, file:line-цитаты сверены с живым кодом). Каждый применён в этом блюпринте:

1. **A7 punch-zoom (CRITICAL + HIGH) — переспецифицирован.** Render статичен per-segment: `segments.py::_box_for_run` коллапсит run в ОДИН `CropBox` (`median(centers)`+`_run_face`), `render.py::_build_crop_filtergraph` эмитит константный `crop=w:h:x:y` (docstring `segments.py`: «a single ffmpeg crop is geometrically constant while active»). Eased-зум «чисто в smoothing/segments» = NO-OP (усредняется в один уровень). **Фикс:** A7 ПЕРЕписан как НОВЫЙ time-varying crop-рендерер (`zoompan`/`sendcmd` с t-выражениями) — свой импурный ffmpeg-seam, easing проверяется LIVE-golden'ом (не unit-тестом), per-frame crop доказан внутри `compute_crop_box`-guard'ов для ВСЕХ t, по-прежнему ОДИН энкод (SPD-1 цел). Ложное «pure-модуляция» убрано. **A7 теперь founder-decision: вырезать ИЛИ строить новый рендерер** (§4.1).
2. **C2 hysteresis ASD (CRITICAL + 2×HIGH) — переспецифицирован.** (а) В пайплайне НЕТ per-face track id (`FaceBox` несёт только x/y/w/h/score/landmarks/speaking). (б) active-speaker решается в ДВУХ независимых путях, которые ОБЯЗАНЫ совпадать: `speaker_region.select_active_face` (центр, несёт `prev_center_x`+cooldown) и `smoothing._resolve_subject`→`_pick_dominant`/`pick_active_speaker` (subject-box, БЕЗ состояния). (в) crop УЖЕ задемпфен: `SWITCH_COOLDOWN_FRAMES=8` @ `SAMPLE_FPS=2.0` ≈ **4с cooldown** + `STICKINESS_BONUS=3.0` + `DEADBAND_FRAC=0.10` + One-Euro → реальный риск = ЛАГ, не мерцание. **Фикс:** C2 = ЕДИНАЯ shared-гистерезисная функция, потребляемая ОБОИМИ путями, с identity-ассоциацией по nearest-box; cross-path тест (center face id == subject box face id под cross-talk); сначала характеризуем существующее поведение; если шипим — СНИЖАЕМ cooldown в концерте и доказываем acquire-latency под бюджетом <1.0с.
3. **C1 word-hold cap (HIGH) — мисдиагноз исправлен.** ПОСЛЕДНЕЕ слово уже `seg_end=word.end` (`ass.py::_build_dialogues`) → не висит в трейлинг-тишине. Реальный phantom-linger = INTER-word gap ВНУТРИ строки (`group_caption_lines` без gap-разбиения; non-last слово держится `[start, next.start)`). **Фикс:** cap КАЖДУЮ row (`seg_end = min(seg_end, seg_start+MAX_WORD_HOLD_S)`) + разбиение строки в `group_caption_lines` при inter-word gap > порога. Тесты пере-выведены вокруг intra-line паузы.
4. **A4 keyword-emphasis (HIGH) — эвристика не дефолт.** `длина≥5` — плохой RU-прокси salience (ловит «предприниматель/соответственно», мимо «деньги/ноль/всё»). **Фикс:** эвристика НЕ боевой дефолт — gate за инжектируемый LLM-seam (founder-decision как A8) ИЛИ demote в dev/test-only; выбор emphasis перенесён ПОСЛЕ `group_caption_lines` (инвариант «≤1/строка» становится проверяемым).
5. **A5 fade-in `\fad` (HIGH) — архитектурно несовместим.** `_build_dialogues` эмитит ОДИН Dialogue PER WORD; `\fad` event-relative → каждое слово ре-фейдит ВСЮ строку из alpha 0 → строб. Литерал `\fad(in,0)` тоже малформед (правильно `\fad(<ms>,<ms>)`). **Фикс:** `\fad` только на ПЕРВОМ event'е строки (одноразовый вход строки) ЛИБО per-word `\alpha`+`\t` ключённый к первому появлению слова; golden утверждает что interior word-events НЕ несут `\fad`.
6. **A6 contrast-band (HIGH) — source-coords неверны.** Луму под band надо мерить на ВЫХОДНОМ 9:16-кадре, а это ДИНАМИЧЕСКИЙ per-segment crop (TRACK-колонка / CONTAIN-blurpad / GENERAL), переключается shot-to-shot; `caption_band_fn` сэмплит SOURCE-координаты. Один clip-wide BandStyle из source НЕВЕРЕН на multi-shot/CONTAIN. **Фикс:** считать band-луму ПЕР-СЕГМЕНТ из разрешённого crop-box (принять probe-цену в перф-бюджет) ЛИБО downgrade до СТАТИЧЕСКОГО усиленного band; «zero-pass» снято. **Founder-decision** (§4.2).
7. **Кинетика-vs-скорость (HIGH) — не «бесплатно».** A3 `\t`/A4 spans/A5 `\fad` бесплатны по ЧИСЛУ энкодов (SPD-1 цел), НЕ по WALL-TIME: libass растеризует активные events КАЖДЫЙ выходной кадр; NVENC оффлоадит только H.264-энтропию, а libass+scale+gblur(sigma=24) остаются на CPU. **Фикс:** добавлен wall-time budget assertion / live SSIM-и-длительность golden-gate; A3/A4/A5 за этим гейтом; impact B2 пере-ранжирован (НЕ «минуты vs 30 мин» для captioned single-window клипов).
8. **B2 hardware-encoder (HIGH) — инфра честно.** `render.py` крутится в КОНТЕЙНЕРЕ cpu-worker, НЕ в gpu-asd Modal-app; `h264_nvenc` требует GPU в RENDER-контейнере (реальная инфра/cost-перемена, не «Modal GPU»). Пиннинг golden'ов ТОЛЬКО на libopenh264 = production-FAST путь без visual-regression покрытия. **Фикс:** инфра заскоуплена честно; отдельный HW-path live SSIM/golden-gate; рычаг = ТОЛЬКО encode-стадия (decode+filter — доля 30-мин кейса); B2 founder-gated И test-gated.

> Остальные 35 находок (LOW/MEDIUM/информационные) не меняют скоуп шагов и учтены точечно в DoD ниже.

---

## 1. Что уже сделано в P2 (НЕ переделывать)

Бóльшая часть старого P3-роадмапа уже поставлена внутри P2 и часто в лучшей, более простой архитектуре. Честная сводка:

**Субтитры (`captioning/`)**
- Чистый ASS-билдер `ass.py` написан с нуля (captacity-lift из роадмапа УСТАРЕЛ — внешней зависимости нет).
- Пословный reveal: ОДИН `Dialogue` PER WORD (не статический `\k`-karaoke). Только произносимое слово — vermillion `&H00303BFF`, остальные — белые. Gap-free, вырожденные окна нудж-апаются на 0.01с. **Важно для A3/A5: каждое слово — ОТДЕЛЬНЫЙ event, показывающий ВСЮ строку → event-relative теги (`\fad`) ре-применяются на КАЖДОЕ слово.**
- Montserrat ExtraBold 140px @ 1080×1920, 4px outline + 2px shadow.
- Группировка 1–3 слова/строка, бюджет 11 символов (`segments.py::group_caption_lines`), lstrip ведущих пробелов. **Нет gap-разбиения** (релевантно C1).
- Safe-zone placement (MarginV 430) + авто-подъём над выжженными source-субтитрами (`caption_band.py` cv2-Sobel + temporal stability, сэмплит SOURCE-координаты — релевантно A6).
- Авто-scale длинных RU-слов (`\fscx/\fscy`, пол 50%), anti-injection escaping метасимволов ASS.
- 100% покрытие, golden-тесты пинят стиль и тело байт-в-байт.

**Reframe (`clipping/`)**
- Гибрид CPU/GPU active-speaker: YuNet (landmarks→frontality) primary, MediaPipe BlazeFace fallback, GPU LR-ASD-класс на Modal (sync `POST /score`, gated `GPU_ASD_MIN_FACES≥2`, wall-cap 45с, fail-open на CPU).
- Бонусы: speaking ×8, frontal ×4, stickiness ×3, switch-cooldown 8 кадров (= **4с @ 2 FPS**).
- One-Euro smoothing (min_cutoff 0.8, beta 0.15) + scene-cut reset + deadband 10% + асимметричный zoom-ease.
- **Render статичен per-segment:** `build_render_segments` коллапсит run в ОДИН `CropBox`; `_build_crop_filtergraph` эмитит константный `crop=w:h:x:y,scale=…`. Динамики кропа внутри сегмента НЕТ (load-bearing для A7).
- **Двойной ASD-путь:** центр — `select_active_face` (несёт `prev_center_x`+cooldown); subject-box — `_resolve_subject`/`pick_active_speaker` (без состояния). Совпадают по «кто говорит», но cooldown-стейт несёт ТОЛЬКО центровой путь (load-bearing для C2).
- Layout-логика: union / 2-way STACK (gated на 2 фронтальных) / CONTEXT_CONTAIN+BLURPAD / GENERAL. Non-causal debounce (kills start-of-clip «скачет»). Aspect-aware CONTAIN/FILL через cropdetect.

**Скорость/архитектура**
- SPD-1: субтитры выжигаются в ТОМ ЖЕ reframe-энкоде (один libopenh264-проход, `-filter_complex_script`/`subtitles=` anti-injection). Caption-стадия только ФОРВАРДИТ. **SPD-1 = один ЭНКОД, не один per-frame cost** (load-bearing для кинетика-tension).
- LGPL-чисто: libopenh264 + aac, без GPL. `render.py::_build_render_argv` хардкодит `-c:v libopenh264` (нет `_encoder_args`-экстракции — B2 это genuinely новая работа).

**ASR (`transcription/`)** — GigaAM-v3 primary (RU word-timestamps, ~8.4% WER), faster-whisper CPU fallback; два контракта `to_cascade_dict` + `to_word_segments`.

**Вывод:** ядро = «Opus-2023 clean reveal» + крепкий reframe. Не хватает кинетики 2024–2026 (pop/keyword/fade/emoji/контраст-band/punch-zoom), CTC-тайтнинга границ, и набора reliability/speed-усилений на реальной вариативности видео.

---

## 2. Genuine remaining gaps (сверено по 4 источникам + adversarial)

**Визуальные (ось «лучше всех»)**
- G1. Нет POP/scale активного слова (только смена цвета) — главная подпись Submagic/Opus. (A3 — архитектурно ОК через `\t` на active-слове.)
- G2. Нет read-ahead lead (~70 мс highlight ДО произнесения) — измеримый retention-рычаг.
- G3. Нет семантического keyword-emphasis (1–2 слова/фраза вторым акцентом). **Прокси salience требует LLM-seam, не длины** (A4).
- G4. Нет fade-in входа слова. **`\fad` нельзя в лоб на per-word events** (A5).
- G5. Нет emoji-инъекции (sparse, semantic).
- G6. Нет контраст-адаптивной подложки band над busy b-roll. **Луму надо мерить на ВЫХОДНОМ кропе, не source** (A6).
- G7. Нет punch-zoom на хук. **Требует НОВОГО time-varying crop-рендерера, не модуляции smoothing** (A7).
- G8. Один look — нет даже минимального выбора пресета.

**Тайминг/ASR (визуальный crispness + reliability)**
- G9. Декодерные word-timestamps дрейфуют; нет CTC forced-alignment (<100 мс). Это субстрат, без которого lead+pop выглядят «мыльно».

**Reliability reframe**
- G10. Бинарный гейт `SPEAKING_THRESHOLD=0.5` → пинг-понг кропа на near-threshold (cross-talk). **ПЕРЕОЦЕНЁН: crop УЖЕ задемпфен 4с-cooldown+stickiness+deadband+One-Euro → реальный риск = ЛАГ** (C2).
- G11. `scene_cut_times` без валидации (не отсортированы/вне границ) → snap-в-никуда/краш.
- G12. `frontality.py` хардкодит порядок 5 landmark'ов → скрэмбл-детектор молча даёт неверную frontality → неверный кроп.
- G13. ASD wall-cap не доказан тестом ≤ stage budget.
- G14. Нет stereo-audio L/R fallback при occlusion/no-face.

**Reliability captions**
- G15. Phantom-linger — **ПЕРЕДИАГНОСТИРОВАН: НЕ трейлинг-тишина (последнее слово уже `word.end`), а INTER-word gap ВНУТРИ строки** (`group_caption_lines` без gap-разбиения) (C1).
- G16. Тихий uncaptioned-dropout при off-by-one ASR-окне НЕ наблюдаем (нет телеметрии coverage).
- G17. Cross-talk даёт non-monotonic word starts → мерцание reveal.

**Скорость**
- G18. libopenh264-only — самоналоженный рычаг. NVENC/VideoToolbox LGPL-легальны → но `render.py` в cpu-worker-контейнере: NVENC требует GPU В RENDER-контейнере (инфра/cost), и оффлоадит ТОЛЬКО энтропию H.264 — libass+scale+gblur остаются на CPU (G18-impact пере-ранжирован) (B2).
- G19. CPU-путь libopenh264 не тюнингован (`-threads`/GOP/буферы).

---

## 3. Ordered TDD steps

Сортировка внутри осей — по impact-per-effort. Сквозные инварианты на КАЖДОМ шаге: pure-core тестируется 100% офлайн; импурные seam'ы (CTC-aligner, ffmpeg, stereo, frame-probe, time-varying crop) инжектируются и факаются; captions fail-open, geometry fail-closed; **SPD-1 (один ЭНКОД) не ломается**; libopenh264 остаётся default И гарантированным fallback'ом; RU UI, бренд FlipHouse — латиница.

**Архитектурный камень (должен лечь первым):** `CaptionPreset` со значением `DEFAULT_PRESET`, рендерящим БАЙТ-в-БАЙТ текущий golden. Это механизм добавить любой визуальный knob без churn'а пиннутого golden (каждый новый look — свой новый golden).

**Новый сквозной перф-инвариант (из adversarial #7):** caption-кинетика бесплатна по ЧИСЛУ энкодов, но НЕ по wall-time (libass растеризует активные events каждый выходной кадр). Любой шаг, добавляющий per-frame ASS-теги (A3/A4/A5), несёт **wall-time budget assertion + live SSIM-и-длительность golden-gate** на captioned-клипе — не только byte-diff `.ass`.

---

### ОСЬ A — ВИЗУАЛЬНО ЛУЧШЕ ВСЕХ (virality)

#### A0 — `CaptionPreset`-скаффолд (enabler, обязателен первым)
- **Goal/DoD:** frozen `CaptionPreset` со всеми knob'ами (font, base/active/keyword colour, outline/shadow, `lead_ms`, `pop`, `fade`, `emoji`, band-mode). `build_caption_ass`/`group_caption_lines`/`_build_style_line`/`_line_body` принимают `preset: CaptionPreset = DEFAULT_PRESET`. `DEFAULT_PRESET` = текущие константы → байт-идентичный вывод.
- **Files:** add `fliphouse_worker/captioning/preset.py`; modify `captioning/ass.py`, `stages/reframe.py::build_caption_ass_fn`.
- **Tests first:** `tests/captioning/test_preset.py` — `test_default_preset_reproduces_pinned_golden_bytes()`, `test_preset_is_frozen_and_fully_typed()`, round-trip каждого поля меняет ровно один ASS-токен.
- **Invariant:** `DEFAULT_PRESET` output == текущий golden (нулевая регрессия для боевых клипов). SPD-1/LGPL не затронуты (только структура билдера).
- **Effort:** M · **Impact:** virality (enabler всей оси).
- **Commit:** `refactor(captioning): thread CaptionPreset through pure ass builder, DEFAULT_PRESET byte-identical [P3-A0]`

#### A1 — CTC forced-alignment refine (поднят из DEFER — субстрат crispness)
- **Goal/DoD:** опциональный pass рефайнит ТОЛЬКО `start/end` слов GigaAM/Whisper до реальных аудиограниц (<100 мс) перед `to_word_segments`. Pure `merge_aligned_boundaries(transcript, aligned_words)`: текст/порядок/количество слов НЕ меняются, границы монотонны, клампятся к duration. Fail-OPEN: ошибка aligner'а / token-count mismatch → исходные тайминги дословно. Env-gated `ASR_FORCED_ALIGN_ENABLED`, off до live-валидации.
- **Files:** add `fliphouse_worker/transcription/align.py` (`Aligner` Protocol + pure `merge_aligned_boundaries` + token-match guard); modify transcription stage call-site (инжект aligner после `normalize_segments`). Контракты `to_word_segments`/`to_cascade_dict` неизменны.
- **Tests first:** `tests/transcription/test_align.py` — snap к CTC-границе; token mismatch → original; boundary > duration клампится; empty aligned → original; идентичность текста до/после; идемпотентность; disabled flag = identity.
- **Invariant:** двигаем ТОЛЬКО время, не текст; count/order сохранён; `end ≥ start`; не превышает `eff_duration`; fail-open на raw GigaAM. SPD-1/LGPL irrelevant (ASR-сторона).
- **Effort:** L · **Impact:** virality (crispness) + reliability (kills drift).
- **Commit:** `feat(transcription): CTC forced-alignment refine pass, time-only, fail-open [P3-A1]`

#### A2 — Read-ahead lead offset (~70 мс)
- **Goal/DoD:** старт окна активного слова сдвигается на `preset.lead_ms` раньше (default 0 в `DEFAULT_PRESET`, 70 в выразительных). Клампится к `≥0` и не пересекает старт предыдущего слова. `lead_ms=0` = no-op (golden-stable).
- **Files:** modify `captioning/ass.py::_build_dialogues`; `preset.py` (+`lead_ms`).
- **Tests first:** `tests/captioning/test_ass.py::test_lead_offset_advances_without_overlap_or_negative_time()` — первое слово ≥0; слово i не раньше i-1; `lead_ms=0` воспроизводит текущие окна.
- **Invariant:** монотонные неперекрывающиеся окна; t≥0; SPD-1 (тот же burn).
- **Effort:** XS · **Impact:** virality (retention).
- **Commit:** `feat(captioning): read-ahead caption lead offset (preset.lead_ms) [P3-A2]`

#### A3 — POP/scale активного слова через libass `\t` ✅ СДЕЛАНО
- **Goal/DoD:** при `preset.pop` активное слово анимирует scale base→~115%·base→base двумя `\t(...)` за ~160 мс. КОМПОЗИРУЕТСЯ с авто-scale длинных слов (мультипликативно на base). Только активное слово; остальные сброшены на базу `\fscx{base}\fscy{base}` (иначе inline-scale «течёт» вперёд). Off в default.
- **Архитектурная заметка (adversarial #7):** A3 совместим с per-word-event моделью — `\t` анимирует ТОЛЬКО scale активного слова ВНУТРИ его event-окна и возвращает к базе; non-active слова статичны между events, строба нет (в отличие от `\fad`/A5). Но `\t` повышает per-frame libass-стоимость → A3 ЗА wall-time gate'ом.
- **⚠️ КОРРЕКЦИЯ ИНВАРИАНТА (ultracode adversarial, реализация):** clamp пика НЕ может опираться на `estimate_line_width_px` (это Latin `len·0.62`, занижает кириллицу на 14–56% → RU-строки вылезали бы за кадр). Операт. инвариант = **истинная popped-ширина по реальным hmtx-метрикам шрифта (`captioning/metrics.py`) ≤ `POP_FRAME_BUDGET_PX` (1080 − 2·16)**, по-словно (растёт только активное слово). Нет запаса до кадра → peak=base, `\t` не эмитится (graceful no-pop). Пред-существующий резерв `_line_scale_pct` (тоже Latin) НЕ трогаем (churn golden) — A3 лишь не добавляет клиппинга.
- **Files:** NEW `captioning/metrics.py` (hmtx-таблица, fail-soft); modify `captioning/ass.py` (`_line_body`+`_pop_peak_pct`, `POP_*` константы); `preset.py` (+`pop`); `pyproject.toml` (+`fonttools`).
- **Tests:** `tests/captioning/test_pop.py` + `test_metrics.py` — два `\t` обратно к базе; popped ≤ max(resting, budget) на RU-кейсах; non-active стартуют `\fscx{base}\fscy{base}`; widе-RU подавляет pop; `pop=False` байт-идентичен; пустое слово=no-pop; fail-soft без шрифта. **+ wall-time/SSIM live-golden** `test_pop_live_golden.py` (env-gated `FLIPHOUSE_LIVE_CAPTIONS=1`).
- **Invariant:** истинная popped-ширина ≤ frame budget; ровно одно активное слово; вся анимация в `.ass` (SPD-1 один ПРОХОД); per-frame libass-cost в wall-time-бюджете. Гейты: 1161 passed, 100% cov, ruff/black 0.
- **Effort:** S · **Impact:** virality (high — signature).
- **Commit:** `feat(captioning): active-word pop via libass \t, composes with autoscale [P3-A3]`

#### A4 — Семантический keyword-emphasis (второй акцент) — heuristic НЕ дефолт
- **Goal/DoD:** ≤1 значимое слово/строка во втором цвете (`preset.keyword_colour`), отдельно от karaoke-активного. **Selector — инжектируемый LLM (Gemini-seam) как РЕАЛЬНЫЙ боевой look (founder-gated, как A8); pure-эвристика (`KeywordSelector` Protocol: RU/EN-stopwords) — ТОЛЬКО dev/test default, НЕ боевой.** Причина (adversarial #4): `длина≥5` — плохой RU-прокси salience (ловит «предприниматель/соответственно», мимо хуковых «деньги/ноль/всё»), боевой второй акцент выглядел бы случайным.
- **Архитектурный фикс порядка:** выбор emphasis ПОСЛЕ `group_caption_lines` (на сгруппированной строке), а НЕ внутри `slice_and_offset_words` (плоский pre-grouping список) — иначе инвариант «≤1/строка» непроверяем. `CaptionWord.emphasis` остаётся additive, но присваивается per-grouped-line.
- **Files:** add `captioning/keywords.py` (`KeywordSelector` Protocol + pure dev-эвристика + место под Gemini-seam); modify `captioning/segments.py::CaptionWord` (+`emphasis`), `captioning/ass.py::group_caption_lines`-callsite (selector ПОСЛЕ группировки), `captioning/ass.py::_line_body`, `stages/reframe.py` (инжект; боевой default = no-keyword, пока LLM-seam не включён founder'ом).
- **Tests first:** `tests/captioning/test_keywords.py` — ≤1/СТРОКА (после группировки); stopwords не выбираются; детерминизм; empty-safe; `tests/captioning/test_ass.py::test_active_hue_wins_over_keyword()` (precedence active>keyword>base); пустой/выключенный selector = байт-идентичен A3-golden; **+ wall-time gate** (доп. colour-spans).
- **Invariant:** боевой default БЕЗ keyword-слоя (пока LLM-seam off); эвристика — dev/test; precedence active>keyword>base; additive; ≤1/строка enforceable после группировки. SPD-1.
- **Effort:** M · **Impact:** virality (signature «easier to follow»), НО только с LLM-seam'ом — иначе риск вкуса.
- **Commit:** `feat(captioning): semantic keyword-emphasis, LLM-seam live look + dev-only heuristic, post-grouping [P3-A4]`

#### A5 — Fade-in входа слова (одноразовый, НЕ per-word `\fad`)
- **Goal/DoD:** при `preset.fade` слово входит плавно ОДИН раз. **`\fad` НЕЛЬЗЯ в лоб (adversarial #5):** `_build_dialogues` эмитит ОДИН Dialogue PER WORD, каждый показывает ВСЮ строку; `\fad` event-relative → каждое слово ре-фейдит всю строку из alpha 0 каждые ~200–400 мс → СТРОБ. Реализация — одна из:
  - **(a) line-entrance:** `\fad(<ms>,0)` ТОЛЬКО на ПЕРВОМ event'е каждой строки (одноразовый вход строки); interior word-events НЕ несут `\fad`.
  - **(b) per-word alpha:** управлять alpha слова через `\alpha`+`\t`, ключённый к ПЕРВОМУ появлению слова, чтобы слово фейдилось один раз и оставалось непрозрачным на последующих events.
- Литерал — `\fad(<fadein_ms>,<fadeout_ms>)` (не малформед `\fad(in,0)`). fade < длины окна. Off в default.
- **Files:** modify `captioning/ass.py::_build_dialogues`/`_line_body`; `preset.py` (+`fade_in_ms`).
- **Tests first:** `tests/captioning/test_ass.py::test_fade_only_on_first_line_event_interior_events_carry_no_fad()` (golden утверждает отсутствие `\fad` на interior word-events); fade не переживает окно; default off (байт-стабилен); **+ wall-time gate**.
- **Invariant:** НЕТ строба (interior events без `\fad`/повторного fade); fade < event-window; default off; SPD-1.
- **Effort:** S · **Impact:** virality (polish).
- **Commit:** `feat(captioning): one-shot per-word/line fade-in, no per-event strobe (preset.fade) [P3-A5]`

#### A6 — Контраст-адаптивная подложка band (per-segment ИЛИ статическая — founder-decision)
- **Goal/DoD:** над низко-контрастным фоном усилить подложку (толще outline/shadow ЛИБО semi-opaque box `BorderStyle=3`+`BackColour`-alpha). **Pure core** `band_style(luma, variance, preset)→BandStyle` остаётся. **Импурный probe пере-специфицирован (adversarial #6):** луму надо мерить на ВЫХОДНОМ 9:16-кадре, а он — ДИНАМИЧЕСКИЙ per-segment crop (TRACK-колонка/CONTAIN-blurpad/GENERAL), переключается shot-to-shot; `caption_band_fn` сэмплит SOURCE-координаты. Один clip-wide BandStyle из source НЕВЕРЕН на multi-shot/CONTAIN (именно тот busy-b-roll кейс, что G6 таргетит). Два пути:
  - **(a) per-segment probe:** считать band-луму ПЕР-СЕГМЕНТ из РАЗРЕШЁННОГО crop-box (переиспользуя cropdetect/render-time окно, НЕ source-band coords), принять доп. probe-цену ЯВНО в перф-бюджет (НЕ «zero-pass»). BandStyle — per-segment.
  - **(b) static:** downgrade до СТАТИЧЕСКОГО усиленного band (всегда `BorderStyle=3` semi-opaque box на выразительных пресетах), без adaptive-probe — дёшево, но не контент-адаптивно.
- **Files:** add `captioning/band_contrast.py`; modify `captioning/ass.py`; путь (a) → `clipping/render.py` (probe над РАЗРЕШЁННЫМ per-segment crop-box, после `_resolve_contain_segments`) + расширить `caption_ass_fn`-контракт под per-segment band; путь (b) → только `preset.py`+`ass.py`.
- **Tests first:** `tests/captioning/test_band_contrast.py` (dark/bright/noisy→BandStyle, pure); путь (a): `tests/clipping/test_render.py` (инъекция per-segment probe в argv, multi-shot → разные BandStyle); default → no box.
- **Invariant:** probe-fail → fail-open к default outline (не блокирует рендер); default preset не затронут; SPD-1 = один ЭНКОД (probe = read, но его wall-cost учтён в бюджете на пути (a)).
- **Effort:** M (a) / S (b) · **Impact:** reliability + virality.
- **Commit:** `feat(captioning): contrast-adaptive caption band, per-segment crop-box luma probe (or static) [P3-A6]`

#### A7 — Punch-zoom на хук — НОВЫЙ time-varying crop-рендерер (founder-decision: cut vs build)
- **Статус:** **переспецифицирован после CRITICAL-блокера.** Старая формулировка («pure модуляция в smoothing/segment-слое») — NO-OP: `segments.py::_box_for_run` коллапсит run в ОДИН `CropBox` (`median(centers)`+`_run_face`→`compute_crop_box`), `render.py::_build_crop_filtergraph` эмитит КОНСТАНТНЫЙ `crop=w:h:x:y,scale=…` (docstring: «a single ffmpeg crop is geometrically constant while active»). Eased-зум в smoothing усредняется в один zoom-level. Единственное, что даёт статичный box — более тесный ОТКРЫВАЮЩИЙ сегмент = мгновенный step-cut (= тот самый «скачок», который A7 обещал избегать). Микро-сегментация головы клипа = N отдельных video-only энкодов (множит энкоды + видимый степпинг). **Поэтому A7 в старом виде невозможен.**
- **Re-scope (если founder выбирает строить):** A7 = НОВЫЙ time-varying crop-рендерер в `render.py` — `crop=w='…':h='…':x='…':y='…'` с t-выражениями (LGPL) ЛИБО `zoompan`, по-прежнему ОДИН энкод (SPD-1 цел). Свой импурный ffmpeg-seam. Easing проверяется LIVE-golden'ом (не unit-тестом — кривая манифестируется только в пикселях). Pure-часть = построитель t-выражения огибающей; она доказывает, что per-frame crop остаётся 9:16 И ВНУТРИ source-кадра для ВСЕХ t огибающей (не только на концах) внутри `compute_crop_box`-guard'ов.
- **Files:** modify `clipping/render.py` (+`_build_punch_crop_filtergraph` / t-expression builder + новый seam), `clipping/segments.py`/`smoothing.py` (только если огибающая параметризуется от трактории); const `HOOK_PUNCH_FRAC`, `HOOK_PUNCH_S`.
- **Tests first:** pure `tests/clipping/test_render.py::test_punch_envelope_stays_9x16_and_in_frame_for_all_t()` (выборка t по огибающей, не endpoints); монотонный спад; **live-golden** на реальном клипе (визуальная проверка easing, нет «скачка», SSIM-стабильность soft-settle).
- **Invariant:** per-frame crop 9:16 и в source-bounds для ВСЕХ t; ОДИН энкод (SPD-1); fail-closed geometry; libopenh264 (или B2-кодек) без второго энкода.
- **Effort:** M–L · **Impact:** virality (hook retention) — НО только при выборе «строить». **Founder-decision (§4.1): вырезать A7 из волны ИЛИ строить новый time-varying рендерер.**
- **Commit:** `feat(reframe): hook punch-zoom via time-varying crop renderer, single-encode, live-golden [P3-A7]`

#### A8 — Emoji-инъекция (sparse, semantic, fail-open) — gated решением founder'а
- **Goal/DoD:** при `preset.emoji` редкий семантический emoji к keyword-строке через pure keyword→emoji map (`EmojiSelector`-seam, детерм. default). Density-cap ≤1 на N строк. **Capability-gated:** colour-emoji требует вендоренного Noto Color Emoji (COLR/CBDT) в delivery-ffmpeg/freetype.
- **Files:** add `captioning/emoji.py`; modify `captioning/ass.py` (font-fallback chain + append glyph), вендорить шрифт; `preset.py` (+`emoji`).
- **Tests first:** `tests/captioning/test_emoji.py` (детерм. map, density-cap, no-match→no emoji); `test_ass.py::test_emoji_off_default_byte_identical()`; `@pytest.mark.live` golden — non-grey пиксели (colour-emoji реально растеризован), gated на capable-build.
- **Invariant:** **fail-open** — если build не растеризует colour-emoji, строка рендерит текст (не tofu, не блок платного клипа); pure core без cv2/сети. SPD-1.
- **Effort:** M · **Impact:** virality (high — Submagic headline). **Live-риск:** зависит от libass/freetype-build (НЕ GPL) — подтвердить на Modal/delivery-образе до флипа `emoji=True`.
- **Commit:** `feat(captioning): sparse semantic emoji injection, capability-gated fail-open [P3-A8]`

#### A9 — Один флагманский RU-look + ≤1–2 выразительных (НЕ реестр 5–8)
- **Goal/DoD:** собрать knob'ы A2–A8 в `DEFAULT_PRESET` (= текущий look, байт-идентичен) + 1–2 выразительных RU-пресета (напр. «Поп», «Караоke»). НЕ 5–8 (YAGNI: founder хочет «один лучший look»). Каждый — значение `CaptionPreset`, выбор per-job. Бренд FlipHouse — латиница, labels RU.
- **Files:** add `captioning/presets_catalog.py` (мини-реестр 2–3 ключа); wire в `stages/reframe.py`; RU-labels в web-UI контракт.
- **Tests first:** `tests/captioning/test_presets_catalog.py` — каждый пресет строит валидный ASS на empty/1-word/overlong-word; labels RU; по golden на пресет.
- **Invariant:** ни один пресет не крашит рендер на крайних входах; 100% branch-coverage каталога; default байт-идентичен.
- **Effort:** S–M · **Impact:** virality + product.
- **Commit:** `feat(captioning): flagship RU caption preset + 1-2 expressive looks (no broad registry) [P3-A9]`

---

### ОСЬ B — БЫСТРО (speed)

#### B1 — libopenh264 encode-arg/threading тюн (бесплатно, каждый клип)
- **Goal/DoD:** в LGPL-пути тюн `-threads`/GOP/rate-буферов для 1080×1920 → CPU-энкод (~120с/клип) падает без потери качества. Pure argv, golden-diffed, SSIM-gated.
- **Files:** modify `clipping/render.py` (`_build_render_argv` / новый `_encoder_args`); `tests/clipping/test_render.py`.
- **Tests first:** argv содержит тюненые `-threads`/`-g`; bitrate-ceiling неизменен; live-gated SSIM — нет регрессии vs прошлый golden-кадр.
- **Invariant:** envelope качества/битрейта неизменен; только параллелизм/буферизация. LGPL/SPD-1 целы.
- **Effort:** S · **Impact:** speed (бесплатно).
- **Commit:** `perf(render): tune libopenh264 threads/GOP/rate-buffers, SSIM-gated [P3-B1]`

#### B2 — Hardware-encoder SEAM (NVENC/VideoToolbox) — gated решением founder'а + ТЕСТ-gated
- **Goal/DoD:** Pure `select_encoder(env, probe_fn)` + pure `_encoder_args(codec)` (экстракция из `_build_render_argv`, сегодня хардкодит `-c:v libopenh264`). `h264_nvenc` / `h264_videotoolbox` при `FH_HW_ENCODER` + успешном probe; **default И fallback = libopenh264**. libass-burn (CPU) неизменен, single-pass (кадры round-trip'ят энкодер, но энкод один — SPD-1 цел). Выход 1080×1920 H.264/AAC `+faststart`.
- **Инфра-честность (adversarial #8):** `render.py` крутится в КОНТЕЙНЕРЕ cpu-worker, НЕ в gpu-asd Modal-app. `h264_nvenc` требует NVIDIA-устройство В RENDER-контейнере → перенос рендера на GPU-контейнер = реальная cost/инфра-перемена (НЕ «Modal GPU» хэндвейв). Заскоупить: где render-контейнер берёт GPU и по какой цене.
- **Тест-честность (adversarial #8):** пиннинг golden'ов ТОЛЬКО на libopenh264 значит production-FAST путь (NVENC/VideoToolbox) — единственный БЕЗ visual-regression покрытия (NVENC при заданном битрейте даёт иное качество/keyframe-поведение). → отдельный **HW-path live SSIM/golden-gate** (live-tier) ДО любого founder-флипа.
- **Impact-честность (adversarial #7,#8):** NVENC оффлоадит ТОЛЬКО H.264-энтропию; per-frame доминанта captioned talking-head клипа (libass-rasterize + scale + gblur sigma=24) остаётся на CPU. 30-мин worst-case = long/4K DECODE+filter, который NVENC НЕ адресует. → рычаг = «encode-стадия ONLY», НЕ «минуты vs 30 мин» для captioned single-window клипов. Квантифицировать долю decode+filter в 30-мин кейсе.
- **Files:** modify `clipping/render.py` (extract `_encoder_args(codec)`, add `select_encoder`); `tests/clipping/test_render.py`; CI HW не включается.
- **Tests first:** no-env→`libopenh264`; env+probe-true→`h264_nvenc`; env+probe-false→`libopenh264` (fallback); `_encoder_args("h264_nvenc")` даёт `-rc vbr -b:v -maxrate`; `_encoder_args("libopenh264")` байт-идентичен текущему golden-argv. **+ HW-path live SSIM/golden** на NVENC-выводе.
- **Invariant:** НИКОГДА не выбирается `--enable-gpl`-кодек (только NVENC/VAAPI/VideoToolbox, LGPL-легально); libopenh264 — гарантированный default+fallback; SPD-1 single-encode; libopenh264-goldens пиннуты + ОТДЕЛЬНЫЙ HW-golden.
- **Effort:** M (код) + инфра (GPU render-контейнер) · **Impact:** speed (encode-стадия ONLY, high на encode-bound клипах), reliability (меньше timeout-краёв на encode).
- **Tension (founder-gated):** ослабляет САМОНАЛОЖЕННОЕ «libopenh264-only» (НЕ GPL-инвариант) + требует GPU render-контейнер (cost). Founder-gated И test-gated.
- **Commit:** `feat(render): hardware-encoder seam (nvenc/videotoolbox), libopenh264 default+fallback, HW-golden-gated [P3-B2]`

---

### ОСЬ C — НАДЁЖНО (reliability)

#### C1 — `MAX_WORD_HOLD_S` cap на КАЖДОЙ row + gap-разбиение строки (kills phantom-linger)
- **Goal/DoD:** ни одна caption-row не показывается дольше `MAX_WORD_HOLD_S` (~1.2с); истинный gap рендерит пусто. **Мисдиагноз исправлен (adversarial #3):** ПОСЛЕДНЕЕ слово уже `seg_end=word.end` (`_build_dialogues`) → НЕ висит в трейлинг-тишине. Реальный phantom-linger = INTER-word gap ВНУТРИ строки (`group_caption_lines` пакует до 3 слов БЕЗ gap-break; non-last слово держит highlight `[start, next.start)` сквозь mid-line паузу). Фикс — оба:
  - cap КАЖДУЮ row в per-word цикле: `seg_end = min(seg_end, seg_start + MAX_WORD_HOLD_S)` (НЕ только последнюю);
  - разбивать строку в `group_caption_lines` при inter-word gap > порога (то самое «BP1-subsumption», что старый блюпринт упоминал, но не реализовывал).
- **Files:** modify `captioning/ass.py::_build_dialogues` (cap каждой row); `captioning/ass.py::group_caption_lines` (gap-break); `tests/captioning/test_ass.py`, `tests/captioning/test_segments.py` (или где живёт grouping).
- **Tests first:** intra-line пауза 3с между словом i и i+1 → row слова i ≤ cap (НЕ next.start); строка разбита по gap; 5с-trailing-silence (уже OK сегодня) остаётся пусто; пустой список → headers-only ASS.
- **Invariant:** НИ ОДНА row > `MAX_WORD_HOLD_S` (включая non-last); intra-line gap → пусто/разбито, не stale. SPD-1.
- **Effort:** S · **Impact:** reliability (podcast intros, mid-line паузы).
- **Commit:** `fix(captioning): cap every word-row hold + gap-based line split (kills intra-line linger) [P3-C1]`

#### C2 — ЕДИНАЯ shared-гистерезисная active-speaker selection для ОБОИХ путей (kills 0.5-flip, без divergence)
- **Goal/DoD:** **переспецифицирован после CRITICAL+2×HIGH.** Три факта из кода:
  1. **НЕТ per-face track id** — `FaceBox` несёт x/y/w/h/score/landmarks/speaking; гистерезис «несёт prev-speaker id» не имеет id → нужна identity-ассоциация по nearest-box (IoU/ближайший центр).
  2. **ДВА независимых пути** должны совпасть: `speaker_region.select_active_face` (ЦЕНТР, несёт `prev_center_x`+cooldown) и `smoothing._resolve_subject`→`_pick_dominant`/`_all_profile`→`pick_active_speaker` (SUBJECT-BOX, БЕЗ состояния). Гистерезис в одном пути без другого → центр-трекинг следует за спикером A, а smoother кадрирует/сайзит спикера B = ХУЖЕ и труднее дебажить, чем 0.5-flip.
  3. **crop УЖЕ задемпфен** — `SWITCH_COOLDOWN_FRAMES=8`@`SAMPLE_FPS=2.0` ≈ **4с cooldown** + `STICKINESS_BONUS=3.0` + `STICKY_RADIUS_FRAC=0.12` + `DEADBAND_FRAC=0.10` + One-Euro. 0.5-flip редко двигает реальный crop → доминирующий риск = **ЛАГ, не мерцание**.
- **Скоуп:** (1) сначала ХАРАКТЕРИЗОВАТЬ существующее cooldown/stickiness-поведение на реальном cross-talk (док-тест/фикстура) — возможно 0.5-flip уже задемпфен. (2) Если шипим C2: сделать speaking-candidate selection ЕДИНОЙ shared-гистерезисной функцией, потребляемой ОБОИМИ `speaker_region._candidate_pool` И `smoothing._pick_dominant`/`_all_profile`; протянуть prev-speaker identity (nearest-box) через `_trajectory_from_frames` И `build_trajectory`/`_resolve_subject` (рядом с существующим `prev_cx`/cooldown). (3) СНИЗИТЬ `SWITCH_COOLDOWN_FRAMES` в концерте (два механизма избыточны) и ДОКАЗАТЬ полную acquire-latency на fast-switch фикстуре под бюджетом (<1.0с). dual-threshold (`SPEAKING_ENTER≈0.55`/`SPEAKING_EXIT≈0.40`); при `ENTER==EXIT` сводится к текущему (backward-compat).
- **Files:** add `clipping/active_speaker.py::pick_active_speaker_hysteretic` (shared, identity-aware); modify `speaker_region.py::select_active_face`/`_candidate_pool` И `smoothing.py::_resolve_subject`/`_pick_dominant`/`_all_profile`/`build_trajectory` (протянуть prev-selection state); `asd_config.py` (cooldown-знаб). `tests/clipping/test_active_speaker.py`, `test_smoothing.py`, `test_speaker_region.py`.
- **Tests first:** **cross-path тест: center face id == subject box face id на КАЖДОМ сэмпле под cross-talk** (без unifying — НЕ шипить); 0.52→0.48→0.52 с prev=A держит A; чёткий 0.9-challenger забирает; mis-association тест (identity nearest-box); acquire-latency < бюджета на fast-switch; single-face не затронут.
- **Invariant:** ОБА пути потребляют ОДНУ shared-функцию (нет divergence); переключение только через band; identity по nearest-box; fail-open к CPU-эвристике неизменен; lag ≤ заявленного бюджета.
- **Effort:** L (был M — identity-ассоциация + unifying двух путей это load-bearing) · **Impact:** reliability (multi-speaker cross-talk) — НО только при unifying.
- **Commit:** `fix(reframe): single shared hysteretic active-speaker for both center+subject paths, reduced cooldown [P3-C2]`

#### C3 — Монотонный clamp word-start (kills reveal-мерцание на cross-talk)
- **Goal/DoD:** pure `_enforce_monotonic(words)` после slicing: каждый `start ≥ max` предыдущих. Текст/порядок/`end` НЕ меняются — только `start` клампится вверх.
- **Files:** modify `captioning/segments.py`; `tests/captioning/test_segments.py`.
- **Tests first:** убывающие starts → неубывающие, текст цел; равные starts → degenerate-nudge downstream; уже-монотонный вход неизменен.
- **Invariant:** порядок текста никогда не меняется; `end ≥ start`. SPD-1.
- **Effort:** S · **Impact:** reliability.
- **Commit:** `fix(captioning): monotonic word-start clamp for cross-talk reveal [P3-C3]`

#### C4 — Caption-coverage телеметрия (тихий dropout → наблюдаемый)
- **Goal/DoD:** pure `caption_coverage(word_segments, clip_window)→[0,1]`. Reframe-стадия пишет `caption_coverage` per-clip в `metrics`; клип с речевым скорингом но ~0 coverage флагается в metrics (НЕ блокируется). Решает off-by-one absolute-vs-relative ASR-окно.
- **Files:** add `captioning/coverage.py`; modify `stages/reframe.py` (fold в `metrics` из того же `slice_and_offset_words`); `tests/captioning/test_coverage.py`.
- **Tests first:** full→~1.0; zero in-window→0.0; partial→ratio; off-by-one воспроизведён как 0.0 + флаг.
- **Invariant:** телеметрия read-only; платный путь байт-идентичен; coverage∈[0,1]; render fail-open.
- **Effort:** S · **Impact:** reliability (observability).
- **Commit:** `feat(captioning): caption-coverage telemetry in reframe metrics, read-only [P3-C4]`

#### C5 — Sanitize scene-cuts (trust-boundary)
- **Goal/DoD:** pure `sanitize_scene_cuts(times, clip_start, clip_end)`: sort + dedup + drop out-of-range; единственная точка входа для smoothing/segments. Garbage → `()` (no-snap, no-crash).
- **Files:** modify `clipping/smoothing.py` (или `stages/clips_io.py` где `load_scene_cut_times`); соответствующий тест.
- **Tests first:** unsorted→sorted; out-of-clip→drop; dup→collapse; garbage→`()`; clean неизменен.
- **Invariant:** sanitized = sorted/unique/в `[start,end]`; никогда не raise.
- **Effort:** S · **Impact:** reliability (anti-crash).
- **Commit:** `fix(reframe): sanitize scene-cut times at trust boundary [P3-C5]`

#### C6 — Frontality landmark-order guard (fail-closed против скрэмбла)
- **Goal/DoD:** sanity-guard в `frontality.py`: implausible-геометрия (глаза ниже рта, NaN, вырожденный spread) → `None` (unknown pose → legacy largest-face fallback), а не уверенно-неверный score.
- **Files:** modify `clipping/frontality.py`; `tests/clipping/test_frontality.py`.
- **Tests first:** скрэмбл (глаза/рот swap)→`None`; NaN→`None`; вырожденный (равные точки)→`None`; валидный фронтал → неизменный score.
- **Invariant:** implausible landmarks → `None` (safe fallback), не confident-wrong.
- **Effort:** S · **Impact:** reliability (silent wrong-speaker prevention).
- **Commit:** `fix(reframe): frontality landmark-order sanity guard, fail-safe to None [P3-C6]`

#### C7 — ASD wall-clock budget assertion как unit-инвариант
- **Goal/DoD:** доказать тестом, что per-clip GPU wall-cap не конфигурируется выше stage budget — guard при config-load.
- **Files:** modify `clipping/asd_config.py`; extend `tests/clipping/test_asd_config.py`.
- **Tests first:** cap > budget → raise при load; cap в budget → pass; timeout fail-open к CPU (пин).
- **Invariant:** GPU-ASD cap ≤ stage budget, enforced at load; render не блокирует past cap.
- **Effort:** S · **Impact:** reliability (bounded latency).
- **Commit:** `test(reframe): enforce ASD wall-clock cap <= stage budget at config load [P3-C7]`

#### C8 — Stereo-audio L/R pan-bias fallback (occlusion/no-face) — Tier 3
- **Goal/DoD:** при промахе face-detection, если аудио stereo — coarse L/R bias из inter-channel energy рулит кропом горизонтально вместо drop в центрированный GENERAL. Pure `stereo_pan_bias(left_rms, right_rms)→[-1,1]`; импурный stereo-decode за seam'ом. Консультируется ТОЛЬКО при отсутствии лица.
- **Files:** add `clipping/stereo_localize.py`; modify `speaker_region.py` (gated, fail-open к GENERAL); `tests/clipping/test_stereo_localize.py`.
- **Tests first:** louder-left→negative; balanced→~0 (GENERAL); mono/NaN→0 (no steer); seam факнут, без аудио-I/O в unit.
- **Invariant:** консультируется только при no-face; balanced/mono → no change; никогда не raise.
- **Effort:** L · **Impact:** reliability (occlusion), но низкая частота на talking-head → Tier 3.
- **Commit:** `feat(reframe): stereo-audio pan-bias fallback for occluded shots [P3-C8]`

---

## 4. Risks & open questions for founder

### 4.1 НОВОЕ (из adversarial): A7 — вырезать ИЛИ строить time-varying рендерер
A7 в старой формулировке («pure модуляция в smoothing/segments») — **NO-OP** против статичного per-segment crop (`_box_for_run` коллапсит run в один box; `_build_crop_filtergraph` константен). Реальный eased punch-zoom требует **НОВОГО time-varying crop-рендерера** (`zoompan`/`sendcmd` с t-выражениями) — свой импурный ffmpeg-seam, easing проверяется live-golden'ом (не unit-тестом), всё ещё ОДИН энкод. **Вопрос: вырезать A7 из этой волны (deferred), ИЛИ инвестировать M–L в новый рендерер?** (Static-box альтернатива = мгновенный step-cut = тот «скачок», что A7 обещал избегать → не делать.)

### 4.2 НОВОЕ (из adversarial): A6 — per-segment probe-cost ИЛИ статический band
Контраст-band'у нужна лума на ВЫХОДНОМ 9:16-кадре, а он — динамический per-segment crop. **(a) per-segment probe** из разрешённого crop-box (контент-адаптивно, корректно на multi-shot/CONTAIN, +probe wall-cost) ИЛИ **(b) статический усиленный band** (`BorderStyle=3` на выразительных пресетах, дёшево, не адаптивно). **Вопрос: платим per-segment probe-цену за корректность на busy b-roll, или статический band достаточен?**

### 4.3 НОВОЕ (из adversarial): A4 — keyword-эвристика НЕ боевой дефолт
`длина≥5` — плохой RU-прокси (ловит «предприниматель», мимо «деньги/ноль/всё»). **Боевой второй-акцент = инжектируемый LLM-seam (Gemini, стоимость/латентность), эвристика — dev/test-only.** **Вопрос: включаем A4 в первой волне ТОЛЬКО с LLM-seam'ом (founder-decision как A8), или откладываем keyword-emphasis до отдельного LLM-тикета?**

### 4.4 НОВОЕ (из adversarial): кинетика стоит wall-time, не только byte-diff
A3 `\t`/A4 spans/A5 fade повышают per-frame libass-стоимость в ТОМ ЖЕ проходе, что B1/B2 ускоряют. **Вопрос: подтверждаем wall-time budget + live SSIM-и-длительность golden-gate как обязательный гейт для A3/A4/A5 (предлагается — да)?**

### 4.5 НОВОЕ (из adversarial): B2 — GPU render-контейнер = реальная инфра/cost
NVENC требует GPU В render-контейнере (cpu-worker сегодня), не в gpu-asd Modal-app. Рычаг = encode-стадия ONLY (NVENC не трогает decode+filter/libass — доминанту captioned-клипа). **Вопрос: готовы ли на cost GPU render-контейнера + отдельный HW-path live-golden-gate ради encode-bound ускорения (не «минуты vs 30 мин» для captioned single-window)?**

### 4.6 Перенесённые из первой версии
1. **NVENC/VideoToolbox (B2) — ослабление named-инварианта.** LGPL-легально. Ослабляет САМОНАЛОЖЕННОЕ «libopenh264-only». **Нужно: явное «да» + правка invariant-doc.** Реализуется за seam'ом, off по умолчанию, libopenh264-goldens + HW-golden — риск изолирован ТОЛЬКО при наличии HW-golden-gate (см. 4.5).
2. **Emoji (A8) — build-зависимость.** Colour-emoji требует вендоренного Noto Color Emoji в delivery-ffmpeg/freetype. Fail-open (нет colour → текст), но флипать `emoji=True` только после live-валидации на Modal/delivery-образе. **Вопрос: emoji в первой волне или Tier 2?**
3. **Сколько пресетов (A9).** JUDGE урезал 5–8 → ОДИН флагман + 1–2 выразительных. **Подтвердить:** default + «Поп» + «Караоke», или только default + 1?
4. **CTC-aligner (A1) — выбор реализации + ASR-время.** GigaAM-CTC logits + n-gram ИЛИ `ctc-forced-aligner`/RU wav2vec2 CTC. +10–20% ASR-времени. Off до live. **Вопрос:** какой aligner и приемлем ли +10–20%.
5. **GPU-ASD lead-time.** C2-unifying + СНИЖЕННЫЙ cooldown должны держать acquire-latency <1.0с (старый «accept 500ms» был неверен — 500мс стэкались поверх 4с cooldown). **Вопрос: бюджет acquire-latency <1.0с — приемлем?**
6. **Read-ahead lead default.** В выразительных пресетах 70 мс; в DEFAULT_PRESET — 0 (golden-stable). **Вопрос:** 70 мс дефолтом для боевых клипов (меняет пиннутый golden) или только в «Поп»?

---

## 5. Out of scope / deferred

- **3-way / 2×2 grid split-screen** — текущий 2-way STACK покрывает доминантный interview-кейс; grid = L-эффорт, резкое падение отдачи, деградация на rapid switches.
- **Predictive/anticipatory pan** (audio-prosody lookahead) — большой; реактивный One-Euro уже матчит 2026-jitter-рецепт.
- **Per-speaker caption colour** — нужен diarization/speaker-label в `word_segments` (ASR-контракт не эмитит). Заблокировано upstream.
- **Замена базового ASR на Parakeet/Canary** — хуже RU, segment-level timestamps. НЕ адоптировать (A1 forced-alignment — правильный RU-фикс тайминга).
- **Background pills (rounded-rect)** — A6 contrast-band покрывает readability дешевле.
- **Hand/pose tracking, mouth-aware vertical anchor, rule-of-thirds vision-guide, adaptive face-sizing, video-rate ASD** — каждый = новый subsystem/сигнал; YAGNI на talking-head RU-контенте.
- **Interactive timing-nudge UI** — product/editor-surface, не render-core.
- **Safe-zones JSON Schema export / standalone `check_safezones.py`** — инвариант уже в `test_safe_zones.py`; schema нужна только для P4 ad-insertion. Отложить до P4.
- **LR-ASD замена текущего GPU-ASD движка** — seam уже fail-open к CPU; смена модели = engine-quality задача, не reliability-gap.
- **A7 как модуляция smoothing/segments** — архитектурно невозможно (статичный per-segment crop); если A7 живёт, то ТОЛЬКО как новый time-varying рендерер (§4.1).

---

## Упаковка PR (rollout — graft из mvp-fast)

- **PR-0 (A0):** CaptionPreset-скаффолд, golden байт-идентичен. Ложится первым.
- **PR-1 «caption flourish» (A2,A3,A5):** всё в `captioning/`, один re-пиннутый golden + **wall-time/SSIM live-gate** (кинетика не бесплатна по wall-time), нулевой риск encode-пути, максимальный видимый virality-скачок. Ship первым после A0. (A5 — одноразовый fade, НЕ per-word `\fad`.)
- **PR-2 «ASD/reframe stability» (C2,C5,C6,C7):** изолировано в `clipping/`. **C2 = unifying двух путей + identity-ассоциация + снижение cooldown** (L, не M) — сначала характеризация существующего демпфирования.
- **PR-3 «caption reliability» (C1,C3,C4):** `captioning/` + reframe-metrics. (C1 = cap КАЖДОЙ row + gap-разбиение строки.)
- **PR-4 «tight karaoke» (A1):** `transcription/align.py`, env-gated, live-валидация до флипа.
- **PR-5 «speed CPU» (B1):** свободный тюн.
- **PR-6 «contrast band» (A6):** per-segment probe ИЛИ статический band (§4.2). **A7 — ТОЛЬКО если founder выбрал «строить» (§4.1)**, отдельным под-PR с новым time-varying рендерером + live-golden.
- **PR-7 «keyword + emoji + presets» (A4,A8,A9):** A4 ТОЛЬКО с LLM-seam'ом (§4.3); capability-gated emoji; founder-решения.
- **PR-8 «stereo fallback» (C8):** Tier 3.
- **Отдельный founder-decision тикет:** B2 NVENC encoder-relaxation (ослабляет named-инвариант + GPU render-контейнер + HW-golden-gate, §4.5).

**Единый самый сильный visual-win за наименьший риск:** A3 (pop, архитектурно совместим) + A9 (флагман-пресет) на субстрате A1 (CTC), за wall-time gate'ом — переводят FlipHouse из «Opus-2023 clean reveal» в «Submagic-2026 kinetic» в чистом single-pass ASS, без цены по SPD-1/LGPL. **A4/A5/A6/A7/B2 требуют founder-решений (§4) — они либо переспецифицированы, либо ослабляют инвариант, либо платят реальную цену.**
