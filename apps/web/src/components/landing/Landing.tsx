import { HeroSection } from '@/components/hero/HeroSection';
import { SiteFooter } from '@/components/layout/SiteFooter';
import { SiteHeader } from '@/components/layout/SiteHeader';
import { Closer } from '@/components/sections/Closer';
import { Marketplace } from '@/components/sections/Marketplace';
import { Metrics } from '@/components/sections/Metrics';
import { ProcessSteps } from '@/components/sections/ProcessSteps';
import { RankedBatch } from '@/components/sections/RankedBatch';

// The FlipHouse Swiss-Pop landing (docs/design-reference/swiss-pop.html): masthead,
// hero with the .dropbar, the ranked batch, the four passes, the marketplace,
// the receipts, the closer and the colophon — assembled around the P1.7 hero.

export function Landing() {
  return (
    <div className="min-h-dvh bg-[var(--background)] text-[var(--foreground)]">
      <SiteHeader />
      <main id="top">
        <HeroSection />
        <RankedBatch />
        <ProcessSteps />
        <Marketplace />
        <Metrics />
        <Closer />
      </main>
      <SiteFooter />
    </div>
  );
}
