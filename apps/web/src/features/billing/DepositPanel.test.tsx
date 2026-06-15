// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DepositPanel } from './DepositPanel';

describe('DepositPanel', () => {
  it('shows the TRC-20 deposit address', () => {
    render(<DepositPanel address="TXyz123" />);

    expect(screen.getByText('Пополнить')).toBeDefined();
    expect(
      screen.getByText('TXyz123', { selector: '[data-slot="deposit-address"]' }),
    ).toBeDefined();
  });

  it('copies the address to the clipboard on click', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<DepositPanel address="TXyz123" />);
    fireEvent.click(screen.getByRole('button', { name: 'Скопировать' }));

    expect(writeText).toHaveBeenCalledWith('TXyz123');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Скопировано' })).toBeDefined(),
    );
  });
});
