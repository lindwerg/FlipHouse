// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ProgressTracker } from './ProgressTracker';

describe('ProgressTracker', () => {
  it('renders a polite live region announcing the phase label', () => {
    render(
      <ProgressTracker phase="processing" percent={40} phaseLabel="Оцениваем виральность" error={null} />,
    );

    const live = screen.getByText('Оцениваем виральность');
    expect(live).toHaveAttribute('aria-live', 'polite');
  });

  it('exposes the percent on the progressbar and clamps out-of-range values', () => {
    const { rerender } = render(
      <ProgressTracker phase="processing" percent={40} phaseLabel="x" error={null} />,
    );
    expect(screen.getByRole('progressbar', { name: /прогресс обработки/i })).toHaveAttribute(
      'aria-valuenow',
      '40',
    );

    rerender(<ProgressTracker phase="processing" percent={140} phaseLabel="x" error={null} />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
  });

  it('shows an alert only when the phase has failed', () => {
    const { rerender } = render(
      <ProgressTracker phase="processing" percent={40} phaseLabel="x" error="Ошибка обработки" />,
    );
    // A non-failed phase does not surface the error as an alert.
    expect(screen.queryByRole('alert')).toBeNull();

    rerender(
      <ProgressTracker phase="failed" percent={100} phaseLabel="Ошибка обработки" error="Ошибка обработки" />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Ошибка обработки');
  });
});
