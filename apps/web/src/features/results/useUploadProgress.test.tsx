// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useUploadProgress } from './useUploadProgress';

const HASH = 'a'.repeat(64);

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

function clipBody(status: string, clips: unknown[] = []): unknown {
  return { status, clips };
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
  title: 'best',
};

// Flush all pending microtasks (the in-flight tick promise chain) under fake
// timers without relying on waitFor (which itself schedules real timers).
async function flush(): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('useUploadProgress', () => {
  it('stays idle and never polls when the contentHash is null', () => {
    const fetchSpy = vi.fn();
    const { result } = renderHook(() => useUploadProgress(null, { fetch: fetchSpy as unknown as typeof fetch }));

    expect(result.current.phase).toBe('loading');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('polls /clips and reports the processing phase, percent and Russian label', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(clipBody('scoring')));
    const { result } = renderHook(() =>
      useUploadProgress(HASH, { fetch: fetchSpy as unknown as typeof fetch }),
    );

    await flush();

    expect(fetchSpy).toHaveBeenCalledWith(`/api/uploads/${HASH}/clips`, { cache: 'no-store' });
    expect(result.current.phase).toBe('processing');
    expect(result.current.percent).toBeGreaterThan(0);
    expect(result.current.phaseLabel).toBe('Оцениваем виральность');
  });

  it('surfaces clips and stops polling once the status is terminal-done', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(clipBody('rendering')))
      .mockResolvedValueOnce(jsonResponse(clipBody('done', [CLIP])));
    const { result } = renderHook(() =>
      useUploadProgress(HASH, { fetch: fetchSpy as unknown as typeof fetch, intervalMs: 1000 }),
    );

    await flush();
    expect(result.current.phase).toBe('processing');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(result.current.phase).toBe('done');
    expect(result.current.clips).toHaveLength(1);
    expect(result.current.percent).toBe(100);

    const callsAfterDone = fetchSpy.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    // No more polls after the terminal status.
    expect(fetchSpy.mock.calls.length).toBe(callsAfterDone);
  });

  it('maps a failed status to the failed phase with an error label', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(clipBody('failed')));
    const { result } = renderHook(() =>
      useUploadProgress(HASH, { fetch: fetchSpy as unknown as typeof fetch }),
    );

    await flush();

    expect(result.current.phase).toBe('failed');
    expect(result.current.error).toBe('Ошибка обработки');
  });

  it('maps a duplicate status to the duplicate phase', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(clipBody('duplicate')));
    const { result } = renderHook(() =>
      useUploadProgress(HASH, { fetch: fetchSpy as unknown as typeof fetch }),
    );

    await flush();

    expect(result.current.phase).toBe('duplicate');
  });

  it('records an error message when a poll fails but keeps the prior phase', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse({ error: 'boom' }, false, 500));
    const { result } = renderHook(() =>
      useUploadProgress(HASH, { fetch: fetchSpy as unknown as typeof fetch }),
    );

    await flush();

    expect(result.current.error).toBe('status 500');
  });

  it('falls back to a generic message when a non-Error rejection is thrown', async () => {
    const fetchSpy = vi.fn().mockRejectedValue('weird');
    const { result } = renderHook(() =>
      useUploadProgress(HASH, { fetch: fetchSpy as unknown as typeof fetch }),
    );

    await flush();

    expect(result.current.error).toBe('Не удалось получить статус обработки');
  });

  it('ignores an in-flight poll that resolves after unmount (no state update)', async () => {
    let resolveFetch: (res: Response) => void = () => {};
    const fetchSpy = vi.fn().mockImplementation(
      () => new Promise<Response>((resolve) => {
        resolveFetch = resolve;
      }),
    );
    const { result, unmount } = renderHook(() =>
      useUploadProgress(HASH, { fetch: fetchSpy as unknown as typeof fetch }),
    );

    // Unmount while the first poll is still pending, then resolve it: the
    // cancelled guard must drop the late result without throwing.
    unmount();
    await act(async () => {
      resolveFetch(jsonResponse(clipBody('done', [CLIP])));
      await vi.advanceTimersByTimeAsync(0);
    });

    // State never advanced past the initial loading phase.
    expect(result.current.phase).toBe('loading');
  });

  it('ignores an in-flight poll that REJECTS after unmount (no error state set)', async () => {
    let rejectFetch: (err: unknown) => void = () => {};
    const fetchSpy = vi.fn().mockImplementation(
      () => new Promise<Response>((_resolve, reject) => {
        rejectFetch = reject;
      }),
    );
    const { result, unmount } = renderHook(() =>
      useUploadProgress(HASH, { fetch: fetchSpy as unknown as typeof fetch }),
    );

    unmount();
    await act(async () => {
      rejectFetch(new Error('late failure'));
      await vi.advanceTimersByTimeAsync(0);
    });

    // The catch's cancelled guard drops the late rejection — no error surfaced.
    expect(result.current.error).toBeNull();
  });

  it('clears polling and resets when the hash changes to null', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(jsonResponse(clipBody('scoring')));
    const { result, rerender } = renderHook(
      ({ hash }) => useUploadProgress(hash, { fetch: fetchSpy as unknown as typeof fetch }),
      { initialProps: { hash: HASH as string | null } },
    );

    await flush();
    expect(result.current.phase).toBe('processing');

    rerender({ hash: null });
    expect(result.current.phase).toBe('loading');

    const callsBefore = fetchSpy.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchSpy.mock.calls.length).toBe(callsBefore);
  });
});
