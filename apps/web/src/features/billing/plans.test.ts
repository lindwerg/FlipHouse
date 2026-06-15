import { describe, expect, it } from 'vitest';
import { getPlan, getPlans, PAYG_PER_MINUTE_USDT, paygCostUsdt } from './plans';

// Plan grid is the monetization contract (docs/01 banner + roadmap §1.12). It is
// verified against Opus Clip (their Pro = 300 min / $29). Caps drive the GPU cost
// ceiling, so they are pinned by a test rather than living loose in a call-site.
describe('billing plans', () => {
  it('plan minute caps + prices match config (free 30 / start 9·150 / active 24·300 / studio 59·1000 / payg 0.25)', () => {
    expect(getPlan('free').minutesPerMonth).toBe(30);
    expect(getPlan('free').priceUsdt).toBe(0);

    expect(getPlan('start').priceUsdt).toBe(9);
    expect(getPlan('start').minutesPerMonth).toBe(150);

    expect(getPlan('active').priceUsdt).toBe(24);
    expect(getPlan('active').minutesPerMonth).toBe(300);

    expect(getPlan('studio').priceUsdt).toBe(59);
    expect(getPlan('studio').minutesPerMonth).toBe(1000);

    expect(PAYG_PER_MINUTE_USDT).toBe(0.25);
    expect(getPlan('payg').minutesPerMonth).toBeNull();
  });

  it('PAYG cost is $0.25 per source-minute', () => {
    expect(paygCostUsdt(4)).toBe(1);
    expect(paygCostUsdt(10)).toBe(2.5);
  });

  it('honors a BILLING_PLAN_ENV JSON override', () => {
    const override = JSON.stringify({ start: { priceUsdt: 12, minutesPerMonth: 200 } });
    const plans = getPlans(override);

    expect(plans.start.priceUsdt).toBe(12);
    expect(plans.start.minutesPerMonth).toBe(200);
    // Non-overridden plans keep their defaults.
    expect(plans.active.priceUsdt).toBe(24);
  });
});
