'use client';

// HeroAnimation — FlipHouse hero motion (ported from the dc-runtime export).
// Self-contained 12s loop: 01 one long video → 02 scissors cut it into 5 vertical
// clips → 03 subtitles snap on → 04 ranked views spin up + coins/income rain.
// Decorative (aria-hidden): the <h1> carries the meaning. Honors reduced-motion
// by holding a single payoff frame. Background is the site OLED black so it sits
// seamlessly in the hero with no visible panel edge.
//
// Self-contained illustrative canvas: raw px/hex by design (its own coordinate
// space + palette mirroring the design tokens --pop / --background).

import { createContext, useContext, useEffect, useRef, useState } from 'react';

// ── tiny engine ──────────────────────────────────────────────────────────────
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const E = {
  linear: (t: number) => t,
  inQuad: (t: number) => t * t,
  outQuad: (t: number) => t * (2 - t),
  inOutCubic: (t: number) => (t < 0.5 ? 4 * t * t * t : (t - 1) * (2 * t - 2) * (2 * t - 2) + 1),
  outCubic: (t: number) => (--t) * t * t + 1,
  inCubic: (t: number) => t * t * t,
  outExpo: (t: number) => (t >= 1 ? 1 : 1 - 2 ** (-10 * t)),
  outBack: (t: number) => { const c1 = 1.70158; const c3 = c1 + 1; return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2; },
};
type Ease = (t: number) => number;
// eased window: maps t in [s,e] -> 0..1 with easing, clamped
const win = (t: number, s: number, e: number, ease: Ease = E.inOutCubic) => ease(clamp((t - s) / (e - s || 1e-6), 0, 1));

const TL = createContext<{ time: number }>({ time: 0 });
const useTime = () => useContext(TL).time;

// ── palette / type ────────────────────────────────────────────────────────────
const BG = '#000000'; // site OLED black (--background: oklch(0% 0 0))
const INK = '#F2F0EC';
const MUTED = 'rgba(242,240,236,0.42)';
const FAINT = 'rgba(242,240,236,0.14)';
const RED = '#FF2A2A';
const GOLD = '#F3C24B';
const GOLD_DK = '#C68A28';
const PANEL = '#151517';
const DISP = "var(--font-grotesk, 'Archivo'), 'Inter', system-ui, sans-serif";
const MONO = "var(--font-mono, 'JetBrains Mono'), ui-monospace, monospace";

const W = 1600;
const H = 900;
const CX = W / 2;
const DUR = 12;
const REDUCED_FRAME = 9.6; // ranked clips + views + income — the payoff still

// ── number formatting ──────────────────────────────────────────────────────────
const fmtViews = (n: number) => {
  if (n >= 1e6) {
    return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace('.', ',') + 'M';
  }
  if (n >= 1e3) {
    return Math.round(n / 1e3) + 'K';
  }
  return String(Math.round(n));
};
const fmtMoney = (n: number) => Math.round(n).toLocaleString('ru-RU').replace(/,/g, ' ');

// ── clip data ───────────────────────────────────────────────────────────────────
type Clip = { hue: string; dur: string; subs: readonly string[]; views: number; rank: number };
const CLIPS: readonly Clip[] = [
  { hue: '#2E6BFF', dur: '0:21', subs: ['смотри', 'сюда'], views: 847000, rank: 3 },
  { hue: '#FF2A2A', dur: '0:14', subs: ['вот', 'почему'], views: 1240000, rank: 2 },
  { hue: '#19C37D', dur: '0:33', subs: ['это', 'работает'], views: 318000, rank: 5 },
  { hue: '#F3C24B', dur: '0:09', subs: ['не', 'пропусти'], views: 2410000, rank: 1 },
  { hue: '#A855F7', dur: '0:27', subs: ['жми', 'лайк'], views: 612000, rank: 4 },
];
const NC = CLIPS.length;

// wide-video geometry (phase 1)
const WV = { w: 760, h: 428, x: CX - 380, y: 232 };
const SLW = WV.w / NC; // slice width = 152
// clip-row geometry (phase 4)
const CLW = 196;
const CLH = 348;
const GAP = 40;
const ROWW = NC * CLW + (NC - 1) * GAP;
const ROWX = CX - ROWW / 2;
const ROWY = 318;

// phase timing (seconds)
const T = {
  vIn: [0.0, 0.7], cap1Out: [2.2, 2.55],
  lines: [2.25, 2.65], scissor: [2.85, 4.35],
  sliceIn: [3.15, 3.45], wideOut: [2.95, 3.5],
  sep: [3.45, 4.35], morph: [4.4, 5.45],
  subIn: 5.65, viewIn: 7.95, coins: 8.05, money: [8.7, 10.9],
  brandPulse: 10.2, fadeOut: 11.55,
};

// ─────────────────────────────────────────────────────────────────────────────
function StepCaption({ t }: { t: number }) {
  const steps = [
    { n: '01', s: 0.7, e: 2.55, label: 'Одно длинное видео' },
    { n: '02', s: 2.7, e: 5.45, label: 'Режем на клипы' },
    { n: '03', s: 5.5, e: 7.7, label: 'Накладываем субтитры' },
    { n: '04', s: 7.8, e: 11.6, label: 'Ранжируем — просмотры и доход' },
  ];
  return (
    <div style={{ position: 'absolute', top: 58, left: 0, right: 0, display: 'flex', justifyContent: 'center' }}>
      <div style={{ position: 'relative', height: 26 }}>
        {steps.map((st, i) => {
          const o = clamp(win(t, st.s, st.s + 0.35, E.outCubic) - win(t, st.e, st.e + 0.35, E.inCubic), 0, 1);
          return (
            <div key={i} style={{ position: 'absolute', left: '50%', top: 0, transform: `translate(-50%, ${(1 - o) * 6}px)`, opacity: o, whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 12, fontFamily: MONO, fontSize: 14, letterSpacing: '0.18em', textTransform: 'uppercase' }}>
              <span style={{ color: RED, fontWeight: 700 }}>{st.n}</span>
              <span style={{ color: FAINT }}>/</span>
              <span style={{ color: MUTED, fontWeight: 500 }}>{st.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const thumbBg = () => 'linear-gradient(135deg, #243a57 0%, #1a2233 48%, #120f18 100%)';

// the source long video — fades out as cutting begins
function WideVideo({ t }: { t: number }) {
  const inP = win(t, T.vIn[0]!, T.vIn[1]!, E.outBack);
  const out = win(t, T.wideOut[0]!, T.wideOut[1]!, E.inCubic);
  const op = clamp(inP - out, 0, 1);
  if (op <= 0) {
    return null;
  }
  const zoom = 1 + 0.03 * win(t, 0.7, 2.6, E.linear);
  const scrub = 0.12 + 0.5 * win(t, 0.7, 2.8, E.linear);
  return (
    <div style={{ position: 'absolute', left: WV.x, top: WV.y, width: WV.w, height: WV.h, opacity: op, transform: `scale(${lerp(0.94, 1, inP) * zoom})`, transformOrigin: 'center', borderRadius: 16, overflow: 'hidden', background: thumbBg(), boxShadow: '0 30px 80px rgba(0,0,0,0.55), inset 0 0 0 1px rgba(255,255,255,0.06)' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(120% 90% at 50% 38%, transparent 35%, rgba(0,0,0,0.55) 100%)' }} />
      <div style={{ position: 'absolute', top: 16, right: 16, fontFamily: MONO, fontSize: 13, fontWeight: 600, color: INK, background: 'rgba(0,0,0,0.5)', padding: '5px 9px', borderRadius: 7, letterSpacing: '0.04em' }}>47:32</div>
      <div style={{ position: 'absolute', left: '50%', top: '46%', transform: 'translate(-50%,-50%)', width: 72, height: 72, borderRadius: 999, background: 'rgba(255,255,255,0.14)', backdropFilter: 'blur(2px)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.25)' }}>
        <div style={{ width: 0, height: 0, marginLeft: 6, borderLeft: '20px solid #fff', borderTop: '13px solid transparent', borderBottom: '13px solid transparent' }} />
      </div>
      <div style={{ position: 'absolute', left: 22, right: 22, bottom: 22, height: 4, background: 'rgba(255,255,255,0.2)', borderRadius: 2 }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${scrub * 100}%`, background: RED, borderRadius: 2 }} />
        <div style={{ position: 'absolute', left: `${scrub * 100}%`, top: '50%', width: 11, height: 11, marginLeft: -5, marginTop: -5, borderRadius: 999, background: '#fff' }} />
      </div>
    </div>
  );
}

// vertical cut lines that flash as the scissors crosses
function CutLines({ t }: { t: number }) {
  const appear = win(t, T.lines[0]!, T.lines[1]!, E.outCubic);
  const out = win(t, 4.5, 5.0, E.inCubic);
  const op = clamp(appear - out, 0, 1);
  if (op <= 0) {
    return null;
  }
  const sx = scissorX(t);
  return (
    <div style={{ position: 'absolute', left: 0, top: 0, width: W, height: H, pointerEvents: 'none' }}>
      {Array.from({ length: NC - 1 }).map((_, i) => {
        const lx = WV.x + (i + 1) * SLW;
        const passed = sx >= lx;
        const flash = clamp(1 - Math.abs(sx - lx) / 26, 0, 1);
        return (
          <div key={i} style={{ position: 'absolute', left: lx - 1, top: WV.y - 14, width: 2, height: WV.h + 28, opacity: op, background: passed ? `linear-gradient(${INK} 0 6px, transparent 6px 12px)` : 'transparent', backgroundSize: '2px 12px', borderLeft: `2px dashed ${flash > 0.05 ? RED : 'rgba(242,240,236,0.5)'}`, boxShadow: flash > 0.05 ? `0 0 ${12 * flash}px ${RED}` : 'none' }} />
        );
      })}
    </div>
  );
}

const scissorX = (t: number) => lerp(WV.x - 26, WV.x + WV.w + 26, win(t, T.scissor[0]!, T.scissor[1]!, E.inOutCubic));

function Scissors({ t }: { t: number }) {
  if (t < T.scissor[0]! - 0.15 || t > T.scissor[1]! + 0.35) {
    return null;
  }
  const inO = win(t, T.scissor[0]! - 0.15, T.scissor[0]! + 0.15, E.outCubic);
  const outO = win(t, T.scissor[1]! + 0.05, T.scissor[1]! + 0.35, E.inCubic);
  const op = clamp(inO - outO, 0, 1);
  const x = scissorX(t);
  const chew = Math.sin(t * 34) * 7;
  return (
    <div style={{ position: 'absolute', left: x, top: WV.y - 52, transform: 'translateX(-50%)', opacity: op }}>
      <svg width="46" height="58" viewBox="0 0 46 58" style={{ filter: 'drop-shadow(0 4px 10px rgba(0,0,0,0.6))' }}>
        <g transform="translate(23 14)">
          <g transform={`rotate(${chew})`}>
            <circle cx="-9" cy="-9" r="6.5" fill="none" stroke={INK} strokeWidth="3" />
            <path d="M-6 -4 L7 30" stroke={INK} strokeWidth="3.4" strokeLinecap="round" />
          </g>
          <g transform={`rotate(${-chew})`}>
            <circle cx="9" cy="-9" r="6.5" fill="none" stroke={INK} strokeWidth="3" />
            <path d="M6 -4 L-7 30" stroke={INK} strokeWidth="3.4" strokeLinecap="round" />
          </g>
          <circle cx="0" cy="2" r="2.4" fill={RED} />
        </g>
      </svg>
    </div>
  );
}

// one slice: lives whole time. Continuous from wide-slice → vertical ranked clip.
function ClipSlice({ t, i }: { t: number; i: number }) {
  const c = CLIPS[i]!;
  const appear = win(t, T.sliceIn[0]!, T.sliceIn[1]!, E.outCubic);
  const fadeEnd = win(t, T.fadeOut, T.fadeOut + 0.45, E.linear);
  const op = clamp(appear - fadeEnd, 0, 1);
  if (op <= 0) {
    return null;
  }

  const sep = win(t, T.sep[0]!, T.sep[1]!, E.outCubic);
  const morph = win(t, T.morph[0]!, T.morph[1]!, E.inOutCubic);

  const gap = 16 * sep;
  const sX = WV.x + i * SLW + (i - (NC - 1) / 2) * gap;
  const sR = { x: sX, y: WV.y, w: SLW, h: WV.h, r: lerp(2, 6, sep) };
  const cR = { x: ROWX + i * (CLW + GAP), y: ROWY, w: CLW, h: CLH, r: 18 };

  const x = lerp(sR.x, cR.x, morph);
  const y = lerp(sR.y, cR.y, morph);
  const w = lerp(sR.w, cR.w, morph);
  const h = lerp(sR.h, cR.h, morph);
  const r = lerp(sR.r, cR.r, morph);

  const settled = win(t, T.morph[1]!, T.morph[1]! + 0.4, E.outCubic);
  const isTop = c.rank === 1;
  const topPop = isTop ? win(t, T.viewIn + 0.2, T.viewIn + 0.9, E.outBack) : 0;
  const floatY = settled * Math.sin(t * 1.3 + i * 1.1) * 5;
  const lift = topPop * -12;
  const sc = 1 + topPop * 0.05;

  const subStart = T.subIn + i * 0.14;
  const rankStart = T.viewIn + 0.5 + i * 0.08;

  const glow = isTop ? topPop : 0;

  return (
    <div style={{ position: 'absolute', left: x, top: y + floatY + lift, width: w, height: h, opacity: op, transform: `scale(${sc})`, transformOrigin: 'center bottom', borderRadius: r, overflow: 'hidden', boxShadow: `0 24px 60px rgba(0,0,0,0.5)${glow > 0 ? `, 0 0 0 2px ${RED}, 0 0 ${40 * glow}px rgba(255,42,42,${0.5 * glow})` : ', inset 0 0 0 1px rgba(255,255,255,0.06)'}` }}>
      <div style={{ position: 'absolute', inset: 0, backgroundImage: thumbBg(), backgroundSize: `${WV.w}px ${WV.h}px`, backgroundPosition: `-${i * SLW}px 0px` }} />
      <div style={{ position: 'absolute', inset: 0, background: `radial-gradient(130% 80% at 50% 8%, ${c.hue}38, transparent 58%)` }} />
      <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg, transparent 45%, rgba(0,0,0,0.72) 100%)' }} />
      <div style={{ position: 'absolute', top: 12, right: 12, opacity: morph, fontFamily: MONO, fontSize: 12, fontWeight: 600, color: INK, background: 'rgba(0,0,0,0.5)', padding: '3px 7px', borderRadius: 6 }}>{c.dur}</div>
      <RankBadge t={t} start={rankStart} rank={c.rank} top={isTop} />
      <Subtitles t={t} start={subStart} words={c.subs} w={w} />
    </div>
  );
}

function RankBadge({ t, start, rank, top }: { t: number; start: number; rank: number; top: boolean }) {
  const o = win(t, start, start + 0.4, E.outBack);
  if (o <= 0) {
    return null;
  }
  return (
    <div style={{ position: 'absolute', top: 12, left: 12, opacity: clamp(o, 0, 1), transform: `translateY(${(1 - o) * -6}px)`, display: 'flex', alignItems: 'center', gap: 5, background: top ? RED : 'rgba(0,0,0,0.55)', color: top ? '#0B0B0B' : INK, padding: '4px 8px', borderRadius: 7, fontFamily: MONO, fontSize: 12, fontWeight: 700, boxShadow: top ? '0 4px 14px rgba(255,42,42,0.45)' : 'inset 0 0 0 1px rgba(255,255,255,0.12)' }}>
      <span style={{ opacity: 0.7 }}>#</span>
      {rank}
    </div>
  );
}

function Subtitles({ t, start, words, w }: { t: number; start: number; words: readonly string[]; w: number }) {
  const o = win(t, start, start + 0.3, E.outCubic);
  if (o <= 0) {
    return null;
  }
  const lt = t - start;
  const w1 = clamp((lt - 0.05) / 0.18, 0, 1);
  const w2 = clamp((lt - 0.34) / 0.18, 0, 1);
  const active = lt > 0.34;
  const fs = Math.max(15, w * 0.105);
  const box = (txt: string, show: number, hot: boolean) => (
    <span style={{ display: 'inline-block', opacity: show, transform: `translateY(${(1 - show) * 6}px) scale(${0.85 + 0.15 * show})`, background: hot ? RED : 'transparent', color: hot ? '#0B0B0B' : INK, padding: hot ? '1px 6px' : '1px 2px', borderRadius: 5, fontWeight: 800, fontFamily: DISP, fontSize: fs, lineHeight: 1.15, letterSpacing: '-0.01em', textShadow: hot ? 'none' : '0 1px 4px rgba(0,0,0,0.7)' }}>{txt}</span>
  );
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, bottom: 18, opacity: clamp(o, 0, 1), display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: 5, padding: '0 8px', textAlign: 'center' }}>
      {box(words[0]!, w1, false)}
      {box(words[1]!, w2, active)}
    </div>
  );
}

// view counter pill floating above each clip
function ViewPills({ t }: { t: number }) {
  return (
    <div style={{ position: 'absolute', left: 0, top: 0, width: W, height: H, pointerEvents: 'none' }}>
      {CLIPS.map((c, i) => {
        const start = T.viewIn + i * 0.1;
        const o = win(t, start, start + 0.4, E.outBack);
        const fadeEnd = win(t, T.fadeOut, T.fadeOut + 0.45, E.linear);
        const op = clamp(o - fadeEnd, 0, 1);
        if (op <= 0) {
          return null;
        }
        const count = c.views * win(t, start + 0.1, start + 1.3, E.outExpo);
        const cx = ROWX + i * (CLW + GAP) + CLW / 2;
        return (
          <div key={i} style={{ position: 'absolute', left: cx, top: ROWY - 42, transform: `translate(-50%, ${(1 - o) * 8}px)`, opacity: op, display: 'flex', alignItems: 'center', gap: 6, background: PANEL, padding: '5px 11px', borderRadius: 999, boxShadow: '0 6px 18px rgba(0,0,0,0.5), inset 0 0 0 1px rgba(255,255,255,0.08)' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" stroke={INK} strokeWidth="2" />
              <circle cx="12" cy="12" r="3" stroke={INK} strokeWidth="2" />
            </svg>
            <span style={{ fontFamily: MONO, fontSize: 14, fontWeight: 700, color: INK, fontVariantNumeric: 'tabular-nums' }}>{fmtViews(count)}</span>
          </div>
        );
      })}
    </div>
  );
}

// coins / bills rain
type CoinSpec = { x: number; start: number; life: number; drift: number; sway: number; rot: number; size: number; bill: boolean };
const COINS: readonly CoinSpec[] = [
  { x: 180, start: 8.05, life: 2.6, drift: 30, sway: 1.2, rot: 1.4, size: 40, bill: false },
  { x: 360, start: 8.45, life: 2.5, drift: -26, sway: 1.0, rot: -1.1, size: 32, bill: false },
  { x: 520, start: 8.2, life: 2.7, drift: 22, sway: 1.4, rot: 0.9, size: 0, bill: true },
  { x: 700, start: 8.9, life: 2.4, drift: -30, sway: 1.1, rot: 1.2, size: 36, bill: false },
  { x: 860, start: 8.3, life: 2.6, drift: 26, sway: 1.3, rot: -1.3, size: 44, bill: false },
  { x: 1020, start: 8.7, life: 2.5, drift: -22, sway: 0.9, rot: 1.0, size: 30, bill: false },
  { x: 1180, start: 8.15, life: 2.7, drift: 28, sway: 1.2, rot: -0.9, size: 0, bill: true },
  { x: 1340, start: 8.6, life: 2.5, drift: -26, sway: 1.5, rot: 1.3, size: 38, bill: false },
  { x: 1460, start: 8.95, life: 2.4, drift: 20, sway: 1.0, rot: -1.1, size: 34, bill: false },
  { x: 90, start: 8.8, life: 2.5, drift: 24, sway: 1.3, rot: 1.1, size: 28, bill: false },
  { x: 620, start: 9.2, life: 2.3, drift: -28, sway: 1.1, rot: -1.2, size: 42, bill: false },
  { x: 940, start: 9.35, life: 2.2, drift: 22, sway: 1.4, rot: 0.8, size: 0, bill: true },
  { x: 1260, start: 9.5, life: 2.0, drift: -20, sway: 1.0, rot: 1.0, size: 36, bill: false },
];

function CoinRain({ t }: { t: number }) {
  return (
    <div style={{ position: 'absolute', left: 0, top: 0, width: W, height: H, pointerEvents: 'none' }}>
      {COINS.map((p, i) => {
        const lt = t - p.start;
        if (lt < 0 || lt > p.life) {
          return null;
        }
        const prog = lt / p.life;
        const y = lerp(-60, H + 70, E.inQuad(prog));
        const x = p.x + Math.sin(prog * p.sway * Math.PI * 2) * p.drift;
        const rot = p.rot * prog * 360;
        let op = clamp(lt / 0.2, 0, 1);
        if (prog > 0.82) {
          op *= clamp(1 - (prog - 0.82) / 0.18, 0, 1);
        }
        return p.bill
          ? <Bill key={i} x={x} y={y} rot={rot} op={op} />
          : <Coin key={i} x={x} y={y} rot={rot} op={op} size={p.size} />;
      })}
    </div>
  );
}

function Coin({ x, y, rot, op, size }: { x: number; y: number; rot: number; op: number; size: number }) {
  const flip = Math.abs(Math.cos(rot * Math.PI / 180));
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: size, height: size, opacity: op, transform: `translate(-50%,-50%) scaleX(${0.25 + 0.75 * flip})`, borderRadius: '50%', background: `radial-gradient(circle at 34% 30%, #FFE9A8, ${GOLD} 52%, ${GOLD_DK} 100%)`, boxShadow: `inset 0 0 0 ${Math.max(1.5, size * 0.06)}px rgba(255,255,255,0.4), 0 4px 12px rgba(0,0,0,0.45)`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: GOLD_DK, fontFamily: DISP, fontWeight: 800, fontSize: size * 0.5 }}>₽</div>
  );
}

function Bill({ x, y, rot, op }: { x: number; y: number; rot: number; op: number }) {
  return (
    <div style={{ position: 'absolute', left: x, top: y, width: 58, height: 34, opacity: op, transform: `translate(-50%,-50%) rotate(${rot * 0.25}deg)`, borderRadius: 5, background: 'linear-gradient(135deg, #3aa776, #1f6f4d)', boxShadow: '0 5px 14px rgba(0,0,0,0.45), inset 0 0 0 1px rgba(255,255,255,0.25)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#eafff4', fontFamily: DISP, fontWeight: 800, fontSize: 17 }}>₽</div>
  );
}

// income payoff readout (bottom center)
function MoneyReadout({ t }: { t: number }) {
  const o = win(t, T.money[0]! - 0.15, T.money[0]! + 0.35, E.outBack);
  const fadeEnd = win(t, T.fadeOut, T.fadeOut + 0.45, E.linear);
  const op = clamp(o - fadeEnd, 0, 1);
  if (op <= 0) {
    return null;
  }
  const val = 248400 * win(t, T.money[0]!, T.money[1]!, E.outExpo);
  return (
    <div style={{ position: 'absolute', left: 0, right: 0, top: 720, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8, opacity: op, transform: `translateY(${(1 - o) * 10}px)` }}>
      <div style={{ fontFamily: MONO, fontSize: 14, letterSpacing: '0.2em', textTransform: 'uppercase', color: MUTED }}>Доход за неделю</div>
      <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 76, color: INK, letterSpacing: '-0.02em', lineHeight: 1, fontVariantNumeric: 'tabular-nums', display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span style={{ color: RED, fontSize: 52 }}>₽</span>
        {fmtMoney(val)}
      </div>
    </div>
  );
}

function BackdropGlow({ t }: { t: number }) {
  const o = win(t, T.viewIn, T.viewIn + 1.2, E.outCubic);
  const fadeEnd = win(t, T.fadeOut, T.fadeOut + 0.45, E.linear);
  const op = clamp(o - fadeEnd, 0, 1) * (0.55 + 0.45 * Math.sin(t * 1.6));
  if (op <= 0) {
    return null;
  }
  return <div style={{ position: 'absolute', inset: 0, opacity: op, background: 'radial-gradient(60% 55% at 50% 52%, rgba(255,42,42,0.16), transparent 70%)', pointerEvents: 'none' }} />;
}

function LoopFade({ t }: { t: number }) {
  const inB = clamp(1 - t / 0.45, 0, 1);
  const outB = win(t, T.fadeOut, DUR, E.linear);
  const op = Math.max(inB, outB);
  if (op <= 0) {
    return null;
  }
  return <div style={{ position: 'absolute', inset: 0, background: BG, opacity: op, pointerEvents: 'none' }} />;
}

// ── root scene ─────────────────────────────────────────────────────────────────
function Scene() {
  const t = useTime();
  const zoom = 1 + 0.018 * win(t, 0, DUR, E.linear);
  return (
    <div style={{ position: 'absolute', inset: 0, background: BG, overflow: 'hidden', fontFamily: DISP }}>
      <div style={{ position: 'absolute', inset: 0, transform: `scale(${zoom})`, transformOrigin: '50% 48%' }}>
        <BackdropGlow t={t} />
        <StepCaption t={t} />
        <WideVideo t={t} />
        {CLIPS.map((_, i) => <ClipSlice key={i} t={t} i={i} />)}
        <CutLines t={t} />
        <Scissors t={t} />
        <ViewPills t={t} />
        <CoinRain t={t} />
        <MoneyReadout t={t} />
      </div>
      <LoopFade t={t} />
    </div>
  );
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const apply = () => setReduced(mq.matches);
    apply();
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, []);
  return reduced;
}

// ── stage: scale the fixed 1600×900 canvas to fill the parent, drive the loop ────
export function HeroAnimation() {
  const reduced = usePrefersReducedMotion();
  const [time, setTime] = useState(0);
  const [scale, setScale] = useState(1);
  const wrapRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const lastRef = useRef<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) {
      return;
    }
    const measure = () => setScale(Math.max(0.05, Math.min(el.clientWidth / W, el.clientHeight / H)));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (reduced) {
      setTime(REDUCED_FRAME);
      return;
    }
    const step = (ts: number) => {
      if (lastRef.current == null) {
        lastRef.current = ts;
      }
      const dt = (ts - lastRef.current) / 1000;
      lastRef.current = ts;
      setTime((t) => {
        let n = t + dt;
        if (n >= DUR) {
          n %= DUR;
        }
        return n;
      });
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
      lastRef.current = null;
    };
  }, [reduced]);

  return (
    <div
      ref={wrapRef}
      aria-hidden
      style={{ position: 'absolute', inset: 0, overflow: 'hidden', background: BG, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      <div style={{ width: W, height: H, position: 'relative', transform: `scale(${scale})`, transformOrigin: 'center', flexShrink: 0, overflow: 'hidden' }}>
        <TL.Provider value={{ time }}>
          <Scene />
        </TL.Provider>
      </div>
    </div>
  );
}
