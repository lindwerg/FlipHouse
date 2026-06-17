# FlipHouse P2 — Финальный blueprint: динамический реврейм, надёжный recall, баннеры субтитров, boundary-snapping

Готовый к реализации план. Все CRITICAL/HIGH блокеры из adversarial-проверки вшиты, judge-графты слиты. Все пути/сигнатуры/факты сверены с реальным кодом (`render.py`, `smoothing.py`, `crop_geometry.py`, `speaker_region.py`, `highlights.py`, `recall.py`, `openrouter_adapter.py`, `routes.py`, `schemas.py`, `engine_backend.py`, `manifest.py`, `cascade.py`, `provider.py`, `dsp/audio_energy.py`, `cli/_dispatch.py`, `clipping/__init__.py`, `tests/clipping/test_packaging.py`).

Роль: архитектор клиппинг-движка. Реализация под строгим TDD, `pytest --cov-fail-under=100` на весь `fliphouse_worker`, ruff+black (line-length 100, E501 ignored).

---

## 0. Опорные факты (что в коде ЕСТЬ СЕЙЧАС — проверено)

- **`render.py:229-235`** коллапсит траекторию в ОДНУ `CropBox` на клип: `traj.is_general()` (булево на весь клип) + `traj.dominant_center()` (медиана по всему клипу) → `_resolve_box` → один `_render_fn`. Время-вариативности нет.
- **`smoothing.py:71-73`** глобальный форс: `avg_faces == 0.0 or avg_faces > general_face_max` → ВСЕ кейфреймы переписываются в `GENERAL`. `CropKeyframe` хранит только `(t, center_x, mode)` — `face_count` живёт лишь в `RawSample` ВНУТРИ `build_trajectory` и до downstream НЕ доходит.
- **`speaker_region.py:160-166`** строит `RawSample(t, center_x, face_count)` на `SAMPLE_FPS=2.0`; `center_x=None` когда лица нет.
- **`crop_geometry.py:103-141`** `compute_crop_box` всегда полная высота (`crop_h=src_h, y=0`), сужает только X; при узком источнике сам возвращает `BLURPAD_MODE`. **Субтитры-нижняя-треть вертикально не режутся никогда.**
- **`render.py:78-90`** `_build_blurpad_filtergraph` = `split=2` + `force_original_aspect_ratio=decrease` (fit, не crop) = founder-«вмести всё».
- **`render.py:93-156`** `_build_render_argv`: `-ss start` ДО `-i`, `-t end-start`, libopenh264 ABR, `-pix_fmt yuv420p`, `-g 60`, AAC 48k stereo.
- **`render.py:52-55`** инжектируемые сеамы `_render_fn`/`_probe_fn`/`_write_fn`/`_clock`; `selector` тоже инжектится.
- **ffmpeg `crop` x/y/w/h КОНСТАНТНЫ пока фильтр активен** (`enable=between` лишь toggle). Один dynamic-crop не может одновременно трекать спикера И переключаться в fit без `sendcmd`/`zmq` (репо их отверг).
- **`engine_backend.py:26-31`** recall идёт через `adapter.complete` (response_format=None) → `_parse_json_loose`.
- **`openrouter_adapter.py:102-135`** `complete_json` шлёт strict json_schema, **бросает `ValueError`** на content=None и на не-JSON. **`_call_with_retry` (162-178) ретраит ТОЛЬКО transport (429/5xx/conn)** — `finish_reason=length` (HTTP-200, обрезанный JSON) НЕ ретраится.
- **`routes.py:24-27`** `RouteConfig(models, provider)` — поля `max_tokens` НЕТ. `_request` (83-91) строит body БЕЗ `max_tokens`.
- **`highlights.py:62`** `CHUNK_SIZE_SECONDS=1200`. **`highlights.py:276`** chunk-loop ловит ТОЛЬКО `RuntimeError`. **`highlights.py:194`** LLM-вызов СНАРУЖИ inner-try (195) — значит `ValueError` из `complete_json` ускользнёт из `call_highlight_api` И из chunk-loop И убьёт всё видео.
- **`cli/_dispatch.py:39`** `isinstance(exc, ValueError) → fatal` — Node/BullMQ не ретраит.
- **`recall.py:48-53`** `snap_to_pause(t, pauses, tol=1.5)` → `pause.mid`. **`recall.py:143-148`** зовётся на start и end с fallback к LLM-границам при коллапсе.
- **`recall.py:129-131`** `recall_candidates(transcript: dict, signals, *, llm_fn, k)` — принимает cascade-dict БЕЗ `word_segments` (`to_cascade_dict` их не кладёт).
- **`provider.py:74-83`** `to_word_segments()` уже умеет проецировать `word_segments` плоским списком — но в cascade-dict они НЕ попадают.
- **`cascade.py:28`** `RecallFn = Callable[[dict, LocalSignals], tuple[CandidateClip, ...]]`. **`cascade.py:95`** `candidates = recall_fn(transcript, signals)`. **НЕТ runtime-сборки `recall_fn`/`render_vertical_clips` нигде в пакете** — связываются только в тестах. «Wiring-точки» в проде не существует (живой entrypoint не построен).
- **`manifest.py:15`** `MANIFEST_SCHEMA_VERSION=1`; `to_dict` обоих dataclass'ов — фиксированный порядок ключей, под byte-shape golden.
- **`__init__.py:22-40`** `__all__` экспортирует публичный API; `test_packaging.py:45-52` проверяет импорт `render_vertical_clips` и др.

---

## 1. ЦЕНТР: динамический реврейм внутри клипа (segment-render + single-clip audio)

### 1.1 Механизм (с учётом CRITICAL про A/V-дрейф)

**CRITICAL-факт (adversarial reframe-correctness):** наивная схема «каждый сегмент = независимый `-ss start -i src -t span` re-encode → concat-демуксер `-c copy`» ломает A/V-синхронизацию. `-ss` до `-i` делает input-seek, видео сбрасывает PTS к ~0, но аудио-стрим сикается независимо и первый AAC-пакет редко попадает в точку реза; плюс libopenh264 даёт свежий GOP+priming, а AAC добавляет ~1024-2048 семплов priming на КАЖДЫЙ голову-сегмента. concat-демуксер `-c copy` НЕ ребейзит PTS и НЕ дропает AAC priming — он только аппендит пакеты. Дрейф НАКАПЛИВАЕТСЯ по N сегментам → губы расходятся к хвосту. Это ровно тот founder-видимый дефект, ради устранения которого фича и делается.

**Решение (вшито):** аудио кодируется/режется РОВНО ОДИН РАЗ на клип, никогда не на сегмент. Видео нарезается по сегментам (разные filtergraph'ы CROP↔BLURPAD), затем VIDEO-сегменты конкатятся, и к конкату подмешивается единожды-нарезанная аудиодорожка клипа.

Поток рендера на клип:

```
keyframes (per-sample TRACK/GENERAL, center_x)              [build_trajectory — изменим §1.3]
   │
   ├─► resolve_mode_timeline (FSM + гистерезис, seed от kf[0])   [НОВОЕ, segments.py]
   ├─► build_render_segments (run-length + merge + snap-to-cut)   [НОВОЕ, segments.py]
   │       TRACK→compute_crop_box(центр интервала); GENERAL→BLURPAD-бокс
   │
   ├─► ОДИН СЕГМЕНТ → fast path: прямой _render_fn(full span) — как сегодня, без concat/mux
   │
   └─► НЕСКОЛЬКО → для каждого сегмента _render_video_fn (VIDEO-ONLY, no audio)
           проба каждого part на (1080,1920) ПЕРЕД склейкой [CRITICAL fail-closed]
           _concat_mux_fn(video_parts, src, clip_start, clip_end, out):
              concat video parts (copy) + единый аудио-рез клипа (-ss clip_start -t span, -c:a aac)
              → mux -shortest → один 1080x1920 mp4
           финальный re-probe (1080,1920) + duration ≈ sum(spans) ±tol [fail-closed]
```

### 1.2 Render-сеамы (с учётом testability-100 HIGH)

`_run_concat_ffmpeg` нельзя оставлять как многострочный temp-file lifecycle под `# pragma: no cover` (testability-100 HIGH: precedent `_run_render_ffmpeg` — буквальный one-liner). Разделяем на чистое ядро + тонкие one-line-boundary.

Новые/изменённые сеамы в `render.py`:

```python
# Video-only рендер одного сегмента (новый seam; mirrors RenderFn но без аудио).
VideoRenderFn = Callable[[str, float, float, CropBox, Path, int, int, str], None]

# Concat видео-частей + единый аудио-рез клипа → один mp4 (новый seam).
ConcatMuxFn = Callable[[Sequence[Path], str, float, float, Path], None]
```

Чистые билдеры (юнит-тестируемы, без ffmpeg):

```python
def _build_video_render_argv(src, start, end, box, out, w, h, bitrate) -> list[str]:
    """libopenh264 ABR + (crop|blurpad) filtergraph, -an (VIDEO ONLY). -ss до -i."""

def _build_concat_list(parts: Sequence[Path]) -> str:
    """concat-demuxer list: одна строка `file '<abs>'` на part; ' → '\\'' экранирование."""

def _build_concat_mux_argv(list_path: Path, src: str, start: float, end: float, out: Path) -> list[str]:
    """Вход 0 = concat-демуксер видео-частей (-c:v copy); вход 1 = src с -ss start -t (end-start);
    -map 0:v:0 -map 1:a:0 -c:a aac -ar 48000 -ac 2 -shortest -movflags +faststart."""
```

Тонкие boundary (one-liner логики, `# pragma: no cover`):

```python
def _run_video_render_ffmpeg(...) -> None:  # pragma: no cover
    subprocess.run(_build_video_render_argv(...), check=True)

def _run_concat_mux_ffmpeg(parts, src, start, end, out):  # pragma: no cover
    list_path = _write_concat_list(_build_concat_list(parts))   # _write_concat_list — covered helper
    try:
        subprocess.run(_build_concat_mux_argv(list_path, src, start, end, out), check=True)
    finally:
        list_path.unlink(missing_ok=True)
```

`_write_concat_list(text: str) -> Path` — отдельный covered хелпер (tmp write), либо инжектируемый `_write_list_fn` (фейк в тестах в `tmp_path`). Net: под pragma остаётся только `subprocess.run`.

Единичный сегмент по-прежнему рендерится полным `_render_fn` (с аудио) — fast path сохраняет обратную совместимость со всеми существующими `test_render.py` фейками (`_ok_render`, `_FakeSelector`).

### 1.3 FSM режимов + интервал-билдер — НОВЫЙ модуль `clipping/segments.py`

Judge-графт (cohesion): `RenderSegment` живёт РЯДОМ со своим билдером — в `segments.py`, НЕ в `crop_geometry.py`.

```python
@dataclass(frozen=True)
class RenderSegment:
    start_s: float       # клип-относительные секунды (0 = старт клипа)
    end_s: float
    box: CropBox
    @property
    def span(self) -> float: return self.end_s - self.start_s
```

Именованные константы (не magic numbers):

```python
N_DROP_SAMPLES: int = 3       # 1.5s @2Hz: подряд "лицо отсутствует" для входа в BLURPAD
N_ACQUIRE_SAMPLES: int = 2    # 1.0s @2Hz: подряд "лицо есть" для возврата в CROP
MIN_SEGMENT_DURATION_S: float = 0.75
EDGE_MARGIN_FRAC: float = 0.10   # лицо ближе этого к краю кадра → b-roll/уходит (reframe HIGH)
```

FSM с гистерезисом, **seed от первого кейфрейма** (reframe-correctness HIGH: безусловный старт в BLURPAD даёт спурьёзный 1s-blurpad-интро на каждом talking-head клипе — частый случай):

```python
def resolve_mode_timeline(
    keyframes: Sequence[CropKeyframe], *,
    n_drop: int = N_DROP_SAMPLES, n_acquire: int = N_ACQUIRE_SAMPLES,
) -> tuple[str, ...]:
    """Per-keyframe TRACK/GENERAL → стабилизированный per-keyframe CROP_MODE/BLURPAD_MODE.

    Состояние СИДИТСЯ от kf[0].mode (TRACK→CROP, GENERAL→BLURPAD): нет ложного blurpad-
    интро на чисто-лицевом клипе. Асимметричный дебаунс применяется только к ПЕРЕХОДАМ:
    CROP→BLURPAD после n_drop подряд GENERAL; BLURPAD→CROP после n_acquire подряд TRACK.
    Пустой вход → пустой кортеж. PURE.
    """
```

Run-length + merge + snap-to-cut + маппинг в боксы:

```python
def build_render_segments(
    traj: CropTrajectory, *,
    sample_fps: float, clip_duration: float,
    scene_cut_times: Sequence[float] = (),          # клип-относительные (reframe MEDIUM)
    min_segment_s: float = MIN_SEGMENT_DURATION_S,
) -> tuple[RenderSegment, ...]:
    """CropTrajectory → упорядоченные RenderSegment, покрывающие [0, clip_duration]. PURE.

      1. resolve_mode_timeline(keyframes) → per-keyframe режим.
      2. run-length-collapse подряд одинаковых режимов → интервалы.
      3. границы = середины между соседними сэмплами; первый=0.0, последний=clip_duration.
         Если scene_cut_time попадает В transition-интервал — снап границы к РЕЗУ,
         не к midpoint (убирает wrong-mode кадры на самом видимом моменте).
      4. merge интервалов < min_segment_s в соседа (предпочесть предыдущего; первый—в след.).
      5. TRACK-интервал → compute_crop_box(src_w, src_h, медиана center_x кейфреймов интервала).
         GENERAL-интервал → CropBox(0,0,src_w,src_h, BLURPAD_MODE).
      6. Пусто (нет кейфреймов) → ОДИН BLURPAD-сегмент [0, clip_duration] (fail-safe).
      Гарантия: ≥1 сегмент; одно-режимная траектория → ровно ОДИН сегмент (fast path).
    """
```

**Источник истины GENERAL не дублируется** (pitfall): `is_general()`/`dominant_center()` НЕ переопределяем, render их просто перестаёт звать. TRACK-интервал может вернуть BLURPAD-бокс (узкий источник) — downstream смотрит на `box.mode`.

### 1.4 `smoothing.py` — per-sample GENERAL вместо глобального форса (CRITICAL regression-fix)

**CRITICAL (integration-regression + reframe HIGH):** просто удалить форс `71-73` нельзя — это (а) ломает `test_marks_general_on_group_shot` и `test_speaker_region.py:96` (оба ждут `is_general()==True`), и (б) даёт regression: интервью-2-shot, который 40s показывает одну говорящую голову, имеет `avg_faces>1.2` → СЕЙЧАС весь клип форсится GENERAL; при наивном удалении FSM получит all-GENERAL и весь клип станет BLURPAD, никогда не трекая. А `face_count` в `CropKeyframe` не доходит.

**Фикс (графт Design 3: «group/faceless сэмпл = raw-GENERAL ВХОД в FSM, per-sample»):** перенести решение TRACK-vs-GENERAL с clip-global на per-sample ВНУТРИ `build_trajectory`, по `face_count` ЭТОГО сэмпла:

```python
for s in samples:
    ... (snap-reset как сейчас) ...
    if s.center_x is None or s.face_count > round(general_face_max):
        keyframes.append(CropKeyframe(s.t, None, GENERAL_MARK))   # per-sample GENERAL вход
        continue
    ... (deadband + One-Euro, center_x сохраняется) ...
    keyframes.append(CropKeyframe(s.t, cx, TRACK_MARK))
# УДАЛИТЬ глобальный пост-цикл-форс (строки 71-73) целиком.
```

Так per-keyframe режим становится истинно время-вариативным, и FSM-вход совпадает со спецификацией. `center_x` сохраняется для TRACK-сэмплов даже в смешанном клипе.

**Сопутствующие правки тестов (в ТОМ ЖЕ PR):**
- `test_marks_general_on_group_shot` переписать: ассертить per-sample GENERAL-марки (или что `build_render_segments` даёт один BLURPAD-сегмент), а не `is_general()==True`.
- `test_speaker_region.py:96` аналогично.

**Опционально (reframe HIGH, face-area/edge guard):** при желании добавить в `build_trajectory` промоушн в GENERAL когда активное лицо в пределах `EDGE_MARGIN_FRAC` от края источника (лицо уходит/съёживается в b-roll) — тогда уходящее/краевое лицо триггерит BLURPAD-fit вместо head-crop. Если включаем — покрыть тестом; иначе отложить (см. открытые решения).

### 1.5 `render.py` — перепись цикла (с fail-closed на каждый part)

Новая сигнатура (все новые параметры keyword-only с дефолтами — 3 существующих call-site целы; testability LOW подтвердил отсутствие позиционных вызовов в проде):

```python
def render_vertical_clips(
    clips, src_path, out_dir, scene_cut_times=(), *,
    target_w=TARGET_W, target_h=TARGET_H, engine=ENGINE_NAME, bitrate=TARGET_BITRATE,
    selector=None,
    sample_fps: float = SAMPLE_FPS,                       # НОВОЕ
    _render_fn: RenderFn = _run_render_ffmpeg,            # full-span (видео+аудио) — fast path
    _video_render_fn: VideoRenderFn = _run_video_render_ffmpeg,   # НОВОЕ: video-only сегмент
    _concat_mux_fn: ConcatMuxFn = _run_concat_mux_ffmpeg,         # НОВОЕ
    _probe_fn=probe_dimensions,
    _write_fn=_write_manifest_json,
    _clock=_utc_now_iso,
) -> RenderManifest:
```

Тело на клип (заменяет 229-240):

```python
traj = selector.select_speaker_region(src_path, start, end, scene_cut_times)
cuts_rel = [c - start for c in scene_cut_times if start <= c < end]
segments = build_render_segments(traj, sample_fps=sample_fps, clip_duration=span,
                                 scene_cut_times=cuts_rel)
out_path = out_dir / clip_filename(i)

if len(segments) == 1:                                   # fast path = текущее поведение
    _render_fn(src_path, start, end, segments[0].box, out_path, target_w, target_h, bitrate)
else:
    seg_dir = Path(tempfile.mkdtemp(prefix=f"fh_seg_{i:02d}_"))   # tmp ВНЕ out_dir (LOW: leak)
    try:
        parts = []
        for j, seg in enumerate(segments):
            part = seg_dir / f"part_{j:02d}.mp4"
            _video_render_fn(src_path, start + seg.start_s, start + seg.end_s,
                             seg.box, part, target_w, target_h, bitrate)
            if not part.exists() or part.stat().st_size == 0:
                raise RenderOutputError(f"clip {i} segment {j} produced no output")
            pw, ph = _probe_fn(part)                      # CRITICAL/MEDIUM: проба КАЖДОГО part
            if (pw, ph) != (target_w, target_h):
                raise DimensionMismatchError(f"clip {i} seg {j} is {pw}x{ph}, expected ...")
            parts.append(part)
        _concat_mux_fn(parts, src_path, start, end, out_path)
    finally:
        shutil.rmtree(seg_dir, ignore_errors=True)

if not out_path.exists() or out_path.stat().st_size == 0:
    raise RenderOutputError(f"ffmpeg produced no output at {out_path}")
rw, rh = _probe_fn(out_path)
if (rw, rh) != (target_w, target_h):
    raise DimensionMismatchError(f"clip {i} is {rw}x{rh}, expected {target_w}x{target_h}")
```

`segment_count = len(segments)` пишется в `ClipEntry` (§3.4 manifest, наблюдаемость).

### 1.6 Что НЕ делаем (guardrails — графт Design 1, дословно)

- НЕ анимируем геометрию crop через стык (ffmpeg не умеет; вернёт per-frame-crop проблему). Стык = жёсткое переключение режима.
- НЕ переопределяем `is_general()`/`dominant_center()` второй эвристикой (один источник истины). Render просто перестаёт их звать.
- НЕ делаем `xfade`-дизолв CROP↔BLURPAD в MVP (ре-энкод на стыке, дороже; nice-to-have за отдельным сеамом — открытое решение).
- НЕ режем аудио по сегментам (A/V-дрейф). Аудио = единый рез клипа.
- НЕ плодим микро-сегменты: FSM-гистерезис + `MIN_SEGMENT_DURATION_S` merge ограничивают число.

---

## 2. Надёжность recall (strict JSON + лимит вывода + меньший чанк + per-chunk resilience)

### 2.1 Корень (CRITICAL recall-reliability)

Strict json_schema сам по себе **НЕ чинит** корень: 4/7 падений были `finish_reason=length` (HTTP-200, обрезанный массив на 20-мин чанке), а `_call_with_retry` length НЕ ретраит и `complete_json` бросает `ValueError`. Поэтому обязательны ТРИ рычага вместе, не «рекомендуется»:

1. **strict json_schema** (грамматика валидна).
2. **`max_tokens >= 4096`** для recall-вызова (массив ~12 хайлайтов закрывается).
3. **`CHUNK_SIZE_SECONDS 1200 → 720`** (короче вход → короче выход → меньше шанс length).

### 2.2 Per-chunk resilience не сломать (CRITICAL recall-reliability)

`complete_json` бросает `ValueError`; chunk-loop ловит только `RuntimeError`; LLM-вызов в `call_highlight_api` СНАРУЖИ inner-try. Значит strict-путь как есть = один сбойный чанк убивает всё видео, и `classify_exception` метит `ValueError` как fatal (Node не ретраит). **Фикс:** в `call_highlight_api` обернуть вызов `highlight_fn`/`llm_fn` ВНУТРИ try, ловить `(RuntimeError, ValueError)`, после `MAX_HIGHLIGHT_API_ATTEMPTS` ре-райзить как `RuntimeError` — контракт, на который опирается chunk-loop.

### 2.3 Файл-за-файлом

**`llm/schemas.py`** — `HIGHLIGHTS_SCHEMA` (top-level object, плоско, без enum/minItems — Gemini-safe; ложится на `_sanitize_highlights(parsed.get("highlights"))`):

```python
HIGHLIGHTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"highlights": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "title": {"type": "string"}, "start_time": {"type": "number"},
            "end_time": {"type": "number"}, "score": {"type": "integer"},
            "hook_sentence": {"type": "string"}, "virality_reason": {"type": "string"},
        },
        "required": ["title","start_time","end_time","score","hook_sentence","virality_reason"],
        "additionalProperties": False,
    }}},
    "required": ["highlights"], "additionalProperties": False,
}
```

**`llm/engine_backend.py`** — `EngineHighlightBackend` (НЕ ломая `LLMFn = Callable[[str],str]`, который нужен `detect_content_type`):

```python
HighlightFn = Callable[[str], dict]

class EngineHighlightBackend:
    _USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")
    def __init__(self, adapter, *, profile=Profile.SCORING) -> None:
        self._adapter = adapter; self._profile = profile
        self.last_model_used = ""; self.raw_usage = {}
    def __call__(self, prompt: str) -> dict:
        result = self._adapter.complete_json(
            profile=self._profile, system="", user=prompt,
            schema_name="highlights", schema=HIGHLIGHTS_SCHEMA, temperature=0.3,
        )
        self.last_model_used = result.model_used
        for k in self._USAGE_KEYS:
            self.raw_usage[k] = self.raw_usage.get(k, 0) + result.raw_usage.get(k, 0)
        return result.data
```

**`engine/highlights.py`:**
- `CHUNK_SIZE_SECONDS = 720`.
- `call_highlight_api(..., *, llm_fn=None, highlight_fn: HighlightFn | None = None)`: вызов ВНУТРИ try, `except (RuntimeError, ValueError)`; если `highlight_fn` задан — `parsed = highlight_fn(prompt)` (strict, уже dict), иначе legacy `_parse_json_loose(llm_fn(prompt))`. `_sanitize_highlights` остаётся. `_parse_json_loose` → salvage-fallback (legacy путь).
- chunk-loop (276) расширить до `except (RuntimeError, ValueError)` (двойная страховка).
- `get_highlights(..., *, llm_fn, highlight_fn=None, dedupe=True)` пробрасывает `highlight_fn`.

**`llm/routes.py`** — добавить `max_tokens: int | None = None` в `RouteConfig`; `SCORING.max_tokens = 4096`. `require_parameters: True` ОСТАЁТСЯ (без него strict молча деградирует).

**`llm/openrouter_adapter.py`** — в `_request` добавить `if route.max_tokens is not None: body["max_tokens"] = route.max_tokens`.

**`engine/recall.py`** — `recall_candidates(..., *, llm_fn, highlight_fn=None, k=3)` пробрасывает `highlight_fn` в `get_highlights` (integration-regression HIGH: нет wiring-точки — тащим через explicit keyword-arg, `llm_fn` остаётся required для `detect_content_type`).

**`cascade.py` / wiring** — `RecallFn` остаётся `Callable[[dict, LocalSignals], ...]`; strict-путь выбирается будущим runner'ом через partial с `highlight_fn=EngineHighlightBackend(adapter)`. НЕ заявлять несуществующий cascade-edit; задокументировать, что entrypoint ещё не построен.

### 2.4 Эскалация сбойного чанка (HIGH recall-reliability) — bounded

Если на проде остаются пропуски: per-chunk эскалация на `gemini-3.5-flash` ПЕРЕД скипом, но с жёстким cap (≤1 эскалация/чанк, только после дешёвого ретрая). Стоимость складывать в существующий `JobCostRecord`/`summarize_job_cost`. По умолчанию — выкл (см. открытые решения).

---

## 3. Вшитые субтитры источника (cheapest, fail-OPEN, geometry НЕ трогаем)

### 3.1 Постура (графт Design 3 — главный графт)

MVP = **detect-and-record + fail-open + feature-flag default None**. `compute_crop_box` геометрия остаётся НЕТРОНУТОЙ (НЕ берём центр-байас Design 2 — он рисковал бы fail-closed примитивом и 100%-гейтом). CROP = полная высота ⇒ нижняя треть субтитров вертикально не теряется; проблема только горизонтальная — её решаем записью band в манифест (свои субтитры FlipHouse ставятся выше `y_top`).

### 3.2 Новый `clipping/caption_band.py`

Чёткий seam (testability-100 MEDIUM): PURE-ядро ест УЖЕ-готовый numpy-стек row-energy `(n_frames, n_rows)` и делает ТОЛЬКО temporal mean/variance + группировку + guards — на чистом numpy (core-dep, без cv2). cv2-декод+Sobel+row-sum живёт целиком в `# pragma: no cover` boundary, который ПРОИЗВОДИТ этот стек.

```python
@dataclass(frozen=True)
class CaptionBand:
    y_top: int
    y_bottom: int
    confidence: float

DetectCaptionBandFn = Callable[[Sequence["NDArrayLike"]], "CaptionBand | None"]

CAPTION_SEARCH_BOTTOM_FRAC = 0.30
CAPTION_K_STD = 2.0
CAPTION_MAX_BAND_FRAC = 0.40     # > 40% высоты → не субтитр → None
CAPTION_MIN_FRAMES = 4           # меньше кадров → None (fail-open)

def detect_caption_band(row_energy_stack) -> CaptionBand | None:
    """PURE. Caption-строка = высокий temporal-mean И НИЗКАЯ temporal-variance
    (стабильность — главный дискриминатор против busy-фона). Группировка смежных
    строк в нижней трети → CaptionBand|None. Любая неопределённость → None."""
```

Реальный producer (`# pragma: no cover`): grayscale → Sobel dx=1 → row-sum по кадру → стек. Fail-OPEN: cv2-ошибка, < CAPTION_MIN_FRAMES, band > 40% → None → рендер как сегодня. Детектор НИКОГДА не блокирует клип.

### 3.3 manifest — `caption_band: dict | None` (см. §3.4 версионирование).

### 3.4 Manifest как версионированный контракт (CRITICAL integration-regression)

Любой новый ключ ломает byte-shape golden `test_manifest_to_dict_byte_shape`. Поэтому:
- `MANIFEST_SCHEMA_VERSION 1 → 2`.
- `ClipEntry.to_dict` += `segment_count: int` (default 1) и `caption_band: dict | None` (default None) в ФИКСИРОВАННОЙ позиции.
- Обновить golden-dict в `test_manifest.py` в ТОМ ЖЕ коммите. Single-segment fast-path → `segment_count=1`, стабильная форма.

---

## 4. Boundary-snapping (полная мысль) — `refine_boundaries` over word_segments + pauses

### 4.1 Что меняем + согласование констант (CRITICAL/HIGH integration-regression + judge-графт)

`snap_to_pause` → `pause.mid` неверно для границ клипа (полпаузы мёртвого эфира). Нужен асимметричный снап к РЕЧЕВОМУ краю + ASR-кандидаты по пунктуации, с даун-вейтом середин-предложения.

**Конфликт констант (judge-графт, обязательно согласовать ДО шипа):** `HIGHLIGHT_SYSTEM_PROMPT` (highlights.py:50) говорит «sweet spot 45-90s, 91-180s для арки», `render.py` `MAX_CLIP_DURATION_S=180`. MIN/MAX 15/40 РЕЖЕТ намеренные 45-90s клипы → recall и snapping дерутся. **Фикс:** `MIN_CLIP_S=20.0` (нижний пол промпта «20-44 короче»), `MAX_CLIP_S=180.0` (= render cap).

`snap_to_pause` и его тесты ОСТАВИТЬ (integration-regression: `test_recall_candidates_snaps_boundary_to_pause` сломается если просто заменить). `refine_boundaries` — ОТДЕЛЬНАЯ функция; заменяем только call-site в `recall_candidates`, обновляем ТОЛЬКО recall-снап-ассерты на новое speech-edge-ожидание.

### 4.2 `transcription/provider.py`

Протащить `word_segments` в recall — отдельным аргументом (не загрязнять hard-subscript cascade-dict). `to_word_segments()` уже есть.

### 4.3 `engine/recall.py` — `refine_boundaries`

```python
GAP_MIN_S = 0.6
MAX_SHIFT_START_S = 1.0     # хук важнее — старт двигаем меньше
MAX_SHIFT_END_S = 2.0
MIN_CLIP_S = 20.0; MAX_CLIP_S = 180.0     # согласовано с промптом + render cap
LEAD_PAD_S = 0.08; TRAIL_PAD_S = 0.20
SENTENCE_END_CHARS = (".", "!", "?", "…")

def refine_boundaries(start, end, word_segments, pauses, duration) -> tuple[float, float]:
    """Снап (start,end) к естественным границам речи. PURE, fail-open к LLM-границам.
      1. Унифицированные кандидаты: word-gaps ≥ GAP_MIN_S (speech_resume/stop,
         tag sentence_end = prev.word.rstrip(quotes/brackets).endswith(SENTENCE_END_CHARS))
         ∪ pauses (resume=p.end, stop=p.start).
      2. START: лучший кандидат в ±MAX_SHIFT_START_S (sentence_end жёстко > gap-only —
         даун-вейт середин-предложения), снап → speech_resume - LEAD_PAD_S.
      3. END: в ±MAX_SHIFT_END_S, снап → speech_stop + TRAIL_PAD_S.
      4. Кламп [0, duration]; end>start.
      5. |сдвиг| > cap ИЛИ длительность вне [MIN_CLIP_S, MAX_CLIP_S] → откат стороны
         (предпочесть откат END) к LLM-границе.
      6. Пустые word_segments И pauses → (start, end) как есть.
    """
```

Заменить в `recall_candidates` (143-148) блок `snap_to_pause` на `refine_boundaries`, прокинув `word_segments` + `duration`. **Порядок (integration-regression):** snapping на CandidateClip ДО реврейма; селектор в render зовётся заново на снапнутом span → face-окна не десинхронятся (подтверждено: `select_speaker_region(src, start, end, ...)`).

---

## 5. #5 широкие/мульти-персон кадры

Решается тем же FSM: group/faceless = per-sample GENERAL вход (§1.4), гистерезис, fail-safe «вмести всё». Глобального whole-clip GENERAL-форса больше нет. Отдельного кода не требует.

---

## 6. Per-file plan (новое/изменённое)

| Файл | Действие | Ключевое |
|---|---|---|
| `clipping/segments.py` | **НОВЫЙ** | `RenderSegment`, `resolve_mode_timeline`, `build_render_segments`, FSM-константы |
| `clipping/smoothing.py` | изменить | per-sample GENERAL по `face_count`; УДАЛИТЬ глобальный форс 71-73; (опц.) edge-guard |
| `clipping/render.py` | изменить | `VideoRenderFn`/`ConcatMuxFn` сеамы, `_build_video_render_argv`/`_build_concat_list`/`_build_concat_mux_argv`, `_write_concat_list`, перепись цикла, per-part probe, tmp вне out_dir, `sample_fps` |
| `clipping/caption_band.py` | **НОВЫЙ** | `CaptionBand`, `DetectCaptionBandFn`, PURE `detect_caption_band`, cv2-producer (pragma) |
| `clipping/manifest.py` | изменить | `SCHEMA_VERSION=2`; `ClipEntry` += `segment_count`, `caption_band` |
| `clipping/__init__.py` | изменить | экспорт `RenderSegment`, `CaptionBand`, `build_render_segments` в `__all__` |
| `llm/schemas.py` | изменить | `HIGHLIGHTS_SCHEMA` |
| `llm/engine_backend.py` | изменить | `EngineHighlightBackend`, `HighlightFn` |
| `llm/routes.py` | изменить | `RouteConfig.max_tokens`; `SCORING.max_tokens=4096` |
| `llm/openrouter_adapter.py` | изменить | `max_tokens` в body `_request` |
| `engine/highlights.py` | изменить | `CHUNK_SIZE_SECONDS=720`; `highlight_fn` seam; вызов внутри try `(RuntimeError,ValueError)`; chunk-loop except расширить |
| `engine/recall.py` | изменить | `refine_boundaries` + константы; проброс `highlight_fn`, `word_segments` |
| `transcription/provider.py` | изменить | проброс `word_segments` в recall |
| `cascade.py` | изменить | проброс `sample_fps`/`word_segments`/`highlight_fn` (БЕЗ фиктивного wiring-claim) |
| `tests/clipping/test_packaging.py` | изменить | добавить `RenderSegment`/`CaptionBand` в импорт-ассерт |

Все инжекшн-сеамы сохранены: `_render_fn`, `_video_render_fn`, `_concat_mux_fn`, `_probe_fn`, `_write_fn`, `_clock`, `selector`, `_sample_faces`, `_probe_dims_fn`, `llm_fn`, `highlight_fn`, `DetectCaptionBandFn`. Real-model ветки `# pragma: no cover`.

---

## 7. TDD-план (100% на фейках) + порядок сборки

### 7.1 Тесты

**`tests/clipping/test_segments.py` (новый):**
- `resolve_mode_timeline`: seed CROP при kf[0]=TRACK (нет ложного blurpad-интро); seed BLURPAD при kf[0]=GENERAL; одиночный GENERAL внутри CROP-серии (< n_drop) НЕ переключает; n_drop подряд переключает; n_acquire подряд возвращает; пустой → пустой.
- `build_render_segments`: чистый TRACK → один CROP [0,dur]; чистый GENERAL → один BLURPAD; TRACK→GENERAL→TRACK → три, непрерывное покрытие; микро-сегмент < min мерджится; центр = медиана; узкий источник TRACK → box.mode==BLURPAD; нет кейфреймов → один BLURPAD [0,dur]; scene_cut в transition → граница == cut, не midpoint; all-broll с одним транзиентным лицом → один BLURPAD после merge.

**`tests/clipping/test_smoothing.py` (расширить):** per-sample GENERAL при face_count > general_face_max ТОЛЬКО для того окна (2-shot внутри single-face серии → GENERAL интервал только для окна, не весь клип); center_x сохраняется для TRACK; обновить `test_marks_general_on_group_shot`.

**`tests/clipping/test_render.py` (расширить):**
- `_build_video_render_argv`: содержит `-an`, нет аудио-флагов; (crop|blurpad) graph.
- `_build_concat_list`: экранирование апострофа; одна строка/part. `_build_concat_mux_argv`: `-f concat -safe 0`, `-map 0:v:0 -map 1:a:0 -c:a aac -shortest`, `-ss start -t span` на аудио-входе.
- fast path (1 сегмент): `_concat_mux_fn`/`_video_render_fn` НЕ вызваны; `_render_fn` один раз с full span; существующие `_FakeSelector` тесты целы.
- multi: `_video_render_fn` N раз с `start+seg.start_s`/`start+seg.end_s`; per-part probe; `_concat_mux_fn` один раз с N parts + (src,start,end); фейк `_concat_mux_fn` пишет out → post-checks проходят; финальный re-probe.
- fail-closed: part пустой → `RenderOutputError` ДО concat; part probe != 1080x1920 → `DimensionMismatchError` ДО concat; финал != 1080x1920 → `DimensionMismatchError`; пустая траектория → 1 BLURPAD сегмент → fast path валиден.

**`tests/clipping/test_caption_band.py` (новый):** стабильная (low-variance) → band; busy (high-variance) → None; > 40% → None; < MIN_FRAMES → None; producer бросает → None (fail-open).

**`tests/clipping/test_manifest.py` (расширить):** обновить byte-shape golden на v2 + `segment_count`/`caption_band`; single-segment → `segment_count=1`, `caption_band=None`.

**`tests/llm/test_schemas.py` (новый):** контракт HIGHLIGHTS_SCHEMA — top-level object, `additionalProperties:False`, nested item тоже `additionalProperties:False` + 6 required, нет enum/minItems/maxItems/oneOf/anyOf/allOf/$ref/format/minimum/maximum.

**`tests/llm/test_engine_backend.py` (расширить):** фейк-adapter `complete_json` → `EngineHighlightBackend` отдаёт dict, копит usage, пишет model_used.

**`tests/llm/test_routes.py` / test_openrouter_adapter.py:** `SCORING.max_tokens==4096`; `max_tokens` попадает в body когда задан, отсутствует когда None.

**`tests/engine/test_highlights.py` (расширить):** `highlight_fn=fake_dict` → strict путь без `_parse_json_loose`; `highlight_fn` бросает `ValueError` на чанке 2/3 → чанки 1,3 дают хайлайты, job НЕ падает (per-chunk resilience под strict); salvage-fallback на обрезанном тексте (legacy); `CHUNK_SIZE_SECONDS==720`.

**`tests/engine/test_recall.py` (расширить):** start → speech-after-pause минус lead; end → speech-stop плюс trail; sentence_end бьёт длинный gap-only mid-sentence; cap превышен → откат стороны; длительность вне [20,180] → откат END; пустые word_segments+pauses → no-op; кламп к duration; RU `?»`/`!"` (rstrip quotes); сохранить старые `snap_to_pause` тесты, обновить только recall-снап-ассерт.

### 7.2 Порядок сборки (каждый шаг 100% + push)

**ВАЖНО (integration-regression CRITICAL):** шаги 3 и 4 (FSM + render-перепись) — в ОДНОМ PR/пуше, чтобы render перестал звать `is_general()` в том же коммите, где меняется семантика `build_trajectory`; иначе промежуточный стейт шипит wrong-crop на group-shot.

1. **Recall strict-JSON + надёжность** (изолировано, наибольший impact): `HIGHLIGHTS_SCHEMA` + контракт-тест → `RouteConfig.max_tokens`+body → `EngineHighlightBackend` → `call_highlight_api(highlight_fn=)` внутри try `(RuntimeError,ValueError)` → `CHUNK_SIZE_SECONDS=720` → проброс. Live: 7/7 чанков. → push.
2. **Boundary-snapping** (чистая, без рендера): `refine_boundaries` (MIN=20/MAX=180) + проброс `word_segments` → замена call-site. → push.
3. **+4 (один PR): FSM/интервалы + segment-render** — `segments.py` (`RenderSegment`/`resolve_mode_timeline`/`build_render_segments` seed+snap-to-cut), per-sample GENERAL в `smoothing.py` (удалить форс, обновить тесты), `render.py` перепись (video-only сегменты + single-audio concat-mux + per-part probe + tmp вне out_dir), `manifest.py` v2 + `segment_count`, `__init__`/`test_packaging`. → push.
5. **Caption-band** (fail-open, за сеамом): `caption_band.py` + `caption_band` в манифест. → push.
6. **Live golden re-run** на `tinkov-plata.mp4`: динамический реврейм; A/V-синк ассерт (start_time delta < 1 кадр, audio dur == video dur ±40ms); полнота recall 7/7; чистые границы; band в манифесте; число сегментов в норме.

Шаги 1, 2 независимы (параллельно); 3+4 строго вместе; 5 независим.

---

## 8. Открытые решения для founder'а (с дефолтом)

1. **Recall лимит/чанк** — дефолт: ОБА (`max_tokens=4096` + `CHUNK_SIZE_SECONDS=720`). Влияет на стоимость/латентность.
2. **Эскалация сбойного чанка** на `gemini-3.5-flash` перед скипом — дефолт: ВЫКЛ (skip+fail-if-all), включать bounded (≤1/чанк) если live покажет пропуски. Стоимость в JobCostRecord.
3. **Пороги FSM** `N_DROP=3 (1.5s)`/`N_ACQUIRE=2 (1.0s)`/`MIN_SEGMENT=0.75s` @2Hz — дефолт принять, потюнить после golden.
4. **Face-area/edge guard** (§1.4 опц.) — дефолт: ВКЛ (уходящее/краевое лицо → BLURPAD, прямо бьёт в «съёживается в b-roll»); если хотим минимальный MVP — отложить.
5. **Кросс-фейд CROP↔BLURPAD (`xfade`)** — дефолт: НЕТ в MVP (жёсткое переключение; дизолв = ре-энкод стыка).
6. **Caption-band действие** — дефолт: только запись в манифест (свои субтитры выше source-полосы); центр-байас геометрии отложен (защита fail-closed примитива + 100% гейта).
7. **A/V-механизм** — дефолт: video-segment-concat + единый аудио-рез клипа + `-shortest` (устраняет per-segment AAC priming). Fallback (если на golden слышен клик на стыке видео): concat-FILTER с ре-энкодом за вторым сеамом.

---

Ключевые абсолютные пути:
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/clipping/segments.py` (новый)
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/clipping/caption_band.py` (новый)
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/clipping/smoothing.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/clipping/render.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/clipping/manifest.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/clipping/__init__.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/llm/schemas.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/llm/engine_backend.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/llm/routes.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/llm/openrouter_adapter.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/engine/highlights.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/engine/recall.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/transcription/provider.py`
- `/Users/mishanikhinkirtill/Desktop/FlipHouse/services/ai-worker-python/fliphouse_worker/engine/cascade.py`

Load-bearing якоря (нельзя обойти): (1) ffmpeg `crop` x/y/w/h константны пока активен → segment-split единственный портируемый механизм; (2) аудио режется/кодируется РОВНО ОДИН РАЗ на клип (единый рез + `-shortest`), НИКОГДА не на сегмент — иначе AAC-priming-дрейф пере-вводит founder-дефект как рассинхрон; (3) `complete_json` бросает `ValueError` → strict-recall вызов ОБЯЗАН быть внутри try в `call_highlight_api`, иначе один чанк убивает видео и `classify_exception` метит fatal; (4) strict-JSON без `max_tokens`+меньшего чанка НЕ чинит корень (length-truncation) — все три рычага обязательны; (5) удаление whole-clip GENERAL-форса требует per-sample GENERAL по face_count в `build_trajectory` И обновления двух тестов И одного PR с render-переписью, иначе regression + красный гейт.