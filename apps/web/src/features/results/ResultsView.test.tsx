// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ResultsView } from './ResultsView';

const HASH = 'a'.repeat(64);

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: () => Promise.resolve(body) } as unknown as Response;
}

// Flush the in-flight poll promise chain under fake timers (no waitFor, which
// schedules its own real timers and would deadlock against the fake clock).
async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

const CLIP = {
  rank: 0,
  score: 87.5,
  startTime: 12,
  endTime: 41.5,
  durationS: 29.5,
  width: 1080,
  height: 1920,
  clipUrl: 'https://clips.example.com/clips/a/clip_00.mp4',
  title: 'Лучший момент',
};

function renderView(status: string, clips: unknown[] = []) {
  const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({ status, clips }));
  render(<ResultsView contentHash={HASH} deps={{ fetch: fetchSpy as unknown as typeof fetch }} />);
  return fetchSpy;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('ResultsView', () => {
  it('shows the progress tracker while the upload is still processing', async () => {
    renderView('scoring');
    await flush();

    expect(screen.getByRole('progressbar', { name: /прогресс обработки/i })).toBeInTheDocument();
  });

  it('renders the ranked clips when processing is done', async () => {
    renderView('done', [CLIP]);
    await flush();

    expect(screen.getByText('Готовые клипы')).toBeInTheDocument();
    expect(screen.getByText('Лучший момент')).toBeInTheDocument();
    expect(screen.getByRole('listitem')).toBeInTheDocument();
  });

  it('shows a Russian error panel with retry copy on failure', async () => {
    renderView('failed');
    await flush();

    expect(screen.getByText(/не удалось обработать видео/i)).toBeInTheDocument();
    expect(screen.getByText(/попробуйте загрузить видео ещё раз/i)).toBeInTheDocument();
  });

  it('shows the duplicate info panel and renders any existing clips for the hash', async () => {
    renderView('duplicate', [CLIP]);
    await flush();

    expect(screen.getByText(/это видео уже обрабатывалось/i)).toBeInTheDocument();
    expect(screen.getByText('Лучший момент')).toBeInTheDocument();
  });

  it('shows the duplicate panel without a clip list when no clips exist for the hash', async () => {
    renderView('duplicate', []);
    await flush();

    expect(screen.getByText(/это видео уже обрабатывалось/i)).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).toBeNull();
  });
});
