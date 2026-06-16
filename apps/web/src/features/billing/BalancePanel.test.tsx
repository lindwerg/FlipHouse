// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BalancePanel } from './BalancePanel';

describe('BalancePanel', () => {
  it('shows the formatted balance and the plan label', () => {
    render(
      <BalancePanel balanceUsdt={50} plan="active" subscriptionStatus={null} />,
    );

    expect(
      screen.getByText('50.00', { selector: '[data-slot="balance"]', exact: false }),
    ).toBeDefined();
    expect(
      screen.getByText('Актив', { selector: '[data-slot="plan"]' }),
    ).toBeDefined();
  });

  it('renders the subscription status when present', () => {
    render(
      <BalancePanel
        balanceUsdt={6}
        plan="active"
        subscriptionStatus="active"
      />,
    );

    expect(screen.getByText(/подписка активна/)).toBeDefined();
  });

  it('omits the status line for a free user with no subscription', () => {
    render(
      <BalancePanel balanceUsdt={0} plan="free" subscriptionStatus={null} />,
    );

    expect(screen.getByText('Бесплатно', { selector: '[data-slot="plan"]' })).toBeDefined();
    expect(screen.queryByText(/подписка/)).toBeNull();
  });
});
