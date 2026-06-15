import { ImageResponse } from 'next/og';

// Social card for the FlipHouse marketing homepage. Swiss-Pop direction
// (docs/design-reference/swiss-pop.html): flush-left grid, paper/ink base with
// vermillion + cobalt accents. Copy is RUSSIAN and mirrors the hero — the
// Cyrillic glyphs are loaded as an Archivo subset at request time (Satori has no
// Cyrillic by default), so the share preview matches the localized page.
export const runtime = 'nodejs';
export const alt
  = 'FlipHouse — одно видео превращается в пачку вертикальных шортсов, ранжированных по виральности';
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = 'image/png';

const PAPER = '#f4f1ea';
const INK = '#16140f';
const VERMILLION = '#e8431f';
const COBALT = '#1f4fe8';

// Every glyph the card renders (incl. the uppercased "FLIPHOUSE" form) — passed
// to Google Fonts so it returns one TTF subset (truetype, which Satori can
// parse) covering exactly these characters.
const GLYPHS
  = 'FlipHouse FLIPHOUSE Видео на входе. Деньги на выходе. Автонарезка 9:16 Субтитры Ранжирование + Маркетплейс';

async function loadArchivo(weight: number): Promise<ArrayBuffer> {
  const url = `https://fonts.googleapis.com/css2?family=Archivo:wght@${weight}&text=${encodeURIComponent(GLYPHS)}`;
  // An old User-Agent forces Google to serve TTF instead of WOFF2 (Satori needs
  // ttf/otf/woff, not woff2).
  const css = await (
    await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1)' },
    })
  ).text();
  const fontUrl = css.match(/src: url\((.+?)\) format\('(?:opentype|truetype)'\)/)?.[1];
  if (!fontUrl) {
    throw new Error('Failed to resolve Archivo font URL');
  }
  return (await fetch(fontUrl)).arrayBuffer();
}

const chip = (label: string) => (
  <div
    key={label}
    style={{
      display: 'flex',
      fontSize: 26,
      fontWeight: 600,
      padding: '10px 18px',
      border: `2px solid ${INK}`,
      color: INK,
    }}
  >
    {label}
  </div>
);

export default async function OpengraphImage() {
  let fonts;
  try {
    const [bold, semi] = await Promise.all([loadArchivo(800), loadArchivo(600)]);
    fonts = [
      { name: 'Archivo', data: bold, style: 'normal' as const, weight: 800 as const },
      { name: 'Archivo', data: semi, style: 'normal' as const, weight: 600 as const },
    ];
  } catch {
    // If the font fetch fails (e.g. no network at build), fall back to the
    // Satori default so the route still returns an image instead of erroring.
    fonts = undefined;
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          backgroundColor: PAPER,
          color: INK,
          padding: '72px 80px',
          fontFamily: 'Archivo',
        }}
      >
        {/* Top rule + brand kicker */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ width: 64, height: 14, backgroundColor: VERMILLION }} />
          <div
            style={{
              fontSize: 26,
              letterSpacing: 6,
              textTransform: 'uppercase',
              fontWeight: 600,
              color: INK,
            }}
          >
            FlipHouse
          </div>
        </div>

        {/* Headline — mirrors the hero */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 92, fontWeight: 800, lineHeight: 1.02, letterSpacing: -3 }}>
            Видео на входе.
          </div>
          <div style={{ display: 'flex', fontSize: 92, fontWeight: 800, lineHeight: 1.02, letterSpacing: -3 }}>
            <span style={{ color: VERMILLION }}>Деньги</span>
            <span>{' '}на выходе.</span>
          </div>
        </div>

        {/* Bottom row: feature chips */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          {['Автонарезка', '9:16', 'Субтитры', 'Ранжирование'].map(chip)}
          <div
            style={{
              display: 'flex',
              fontSize: 26,
              fontWeight: 600,
              padding: '10px 18px',
              backgroundColor: COBALT,
              color: PAPER,
            }}
          >
            + Маркетплейс
          </div>
        </div>
      </div>
    ),
    {
      ...size,
      ...(fonts ? { fonts } : {}),
    },
  );
}
