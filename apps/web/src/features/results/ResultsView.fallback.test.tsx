// @vitest-environment jsdom
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { UploadProgress } from './useUploadProgress';

// Mocks useUploadProgress to force the one branch the real hook can't reach: a
// failed phase with a null error (the real hook always attaches a label-error to
// a failure). This covers the defensive `?? fallback` copy in the error panel.
const progressState = vi.hoisted(() => ({
  current: null as unknown as UploadProgress,
}));

vi.mock('./useUploadProgress', () => ({
  useUploadProgress: () => progressState.current,
}));

const { ResultsView } = await import('./ResultsView');

afterEach(() => {
  vi.clearAllMocks();
});

describe('ResultsView error fallback copy', () => {
  it('shows the generic fallback message when a failed phase carries no error', () => {
    progressState.current = {
      phase: 'failed',
      percent: 100,
      phaseLabel: 'Ошибка обработки',
      error: null,
      clips: [],
    };

    render(<ResultsView contentHash={'a'.repeat(64)} />);

    expect(screen.getByText(/произошла ошибка во время обработки/i)).toBeInTheDocument();
  });
});
