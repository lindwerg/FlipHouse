import { HeroDropzone } from '@/components/hero/HeroDropzone';
import { Eyebrow } from '@/components/layout/Eyebrow';
import { SiteHeader } from '@/components/layout/SiteHeader';

// Dev-only preview route for the Swiss shell + hero dropzone (P1.5–P1.7).
// NOT part of the production landing — that is assembled from real sections in
// P1.8. Kept as a living component sandbox for founder review during the build.
export default function DesignPreviewPage() {
  return (
    <div className="min-h-dvh bg-[var(--background)] text-[var(--foreground)]">
      <SiteHeader />
      <main className="mx-auto max-w-[1600px] px-[var(--space-margin)] py-16">
        <Eyebrow>Из нарезки · каркас P1.5</Eyebrow>
        <h1
          className="mt-4 max-w-[16ch] font-[family-name:var(--font-grotesk)] font-black uppercase leading-[0.9] tracking-tight"
          style={{ fontSize: 'var(--text-hero)' }}
        >
          Одно видео.
          {' '}
          <span className="text-[var(--pop)]">Пачка ранжированных</span>
          {' '}
          шортсов.
        </h1>
        <p className="mt-8 max-w-[46ch] text-[var(--ink-soft)]" style={{ fontSize: 'var(--text-base)' }}>
          Каркас P1.5: шрифты Archivo / Archivo Narrow / IBM Plex Mono, палитра paper + ink + vermillion,
          hairline-rules. Это превью компонентов — настоящий hero собираем в P1.6–P1.8.
        </p>

        <div className="mt-12 max-w-[760px]">
          <Eyebrow>P1.7 · hero-дропзона</Eyebrow>
          <div className="mt-4">
            <HeroDropzone />
          </div>
        </div>

        <div className="mt-12 flex flex-wrap gap-6 border-t border-[var(--rule)] pt-8">
          <Eyebrow>Archivo · гротеск</Eyebrow>
          <p className="font-[family-name:var(--font-narrow)] text-[var(--ink-soft)]">Archivo Narrow · меню</p>
          <p className="font-mono text-[var(--ink-faint)]">IBM Plex Mono · 00:41:12 — виральность 94</p>
        </div>
      </main>
    </div>
  );
}
