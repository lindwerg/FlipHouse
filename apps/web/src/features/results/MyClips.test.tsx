// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { OwnerUploadView } from './api-schemas';
import { MyClips } from './MyClips';

const HASH_A = 'a'.repeat(64);
const HASH_B = 'b'.repeat(64);

function upload(overrides: Partial<OwnerUploadView> = {}): OwnerUploadView {
  return {
    contentHash: HASH_A,
    status: 'done',
    durationSec: 120,
    createdAt: '2026-01-15T00:00:00.000Z',
    clips: [
      {
        rank: 0,
        score: 87.5,
        startTime: 12,
        endTime: 41.5,
        durationS: 29.5,
        width: 1080,
        height: 1920,
        clipUrl: 'https://clips.example.com/clips/a/clip_00.mp4',
        title: 'Лучший момент',
      },
    ],
    ...overrides,
  };
}

/** A fake fetch that resolves a 200 JSON body once. */
function okFetch(body: unknown): typeof fetch {
  return vi.fn(async () =>
    new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }),
  ) as unknown as typeof fetch;
}

describe('MyClips', () => {
  it('shows a loading state before the request resolves', () => {
    // A fetch that never resolves keeps the component in its loading branch.
    const pending = vi.fn(() => new Promise<Response>(() => {})) as unknown as typeof fetch;
    render(<MyClips deps={{ fetch: pending }} />);
    expect(screen.getByText(/загружаем вашу историю/i)).toBeInTheDocument();
  });

  it('renders uploads newest-first with a status badge and reused ranked clips', async () => {
    const fetchImpl = okFetch({
      uploads: [
        upload({ contentHash: HASH_B, status: 'done', createdAt: '2026-02-20T00:00:00.000Z' }),
        upload({ contentHash: HASH_A, status: 'failed', clips: [], createdAt: '2026-01-15T00:00:00.000Z' }),
      ],
    });
    render(<MyClips deps={{ fetch: fetchImpl }} />);

    await waitFor(() => expect(screen.getByText('Лучший момент')).toBeInTheDocument());
    expect(screen.getByText('готово')).toBeInTheDocument();
    expect(screen.getByText('ошибка')).toBeInTheDocument();
    expect(screen.getByText('20.02.2026')).toBeInTheDocument();
    expect(screen.getByText('15.01.2026')).toBeInTheDocument();
    expect(fetchImpl).toHaveBeenCalledWith('/api/uploads', expect.anything());
  });

  it('shows an empty-state when the owner has no uploads', async () => {
    render(<MyClips deps={{ fetch: okFetch({ uploads: [] }) }} />);
    await waitFor(() =>
      expect(screen.getByText(/здесь появятся ваши готовые клипы/i)).toBeInTheDocument(),
    );
  });

  it('shows an error message when the request fails', async () => {
    const failing = vi.fn(async () => new Response('nope', { status: 500 })) as unknown as typeof fetch;
    render(<MyClips deps={{ fetch: failing }} />);
    await waitFor(() => expect(screen.getByText(/не удалось загрузить ваши клипы/i)).toBeInTheDocument());
  });
});
