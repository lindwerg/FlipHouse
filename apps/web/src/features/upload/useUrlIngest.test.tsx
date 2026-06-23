// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { IngestPollResult, SubmitUrlRequest } from './useUrlIngest';
import { INGEST_MAX_POLLS, useUrlIngest } from './useUrlIngest';

/** A submit that succeeds with an ingestId; a never-resolving delay freezes the poll loop. */
function okSubmit(ingestId = 'ingest:' + 'a'.repeat(64)): SubmitUrlRequest {
  return vi.fn<SubmitUrlRequest>().mockResolvedValue(ingestId);
}

/** A delay that never resolves — keeps the poll loop parked so a test owns the clock. */
const frozenDelay = (): Promise<void> => new Promise<void>(() => {});

describe('useUrlIngest', () => {
  it('starts idle with no error', () => {
    const { result } = renderHook(() =>
      useUrlIngest({ submitUrl: okSubmit(), delay: frozenDelay }),
    );

    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  it('renders with the default fetch/poll/timer seams when no deps are given', () => {
    // Render-only: exercises the `?? default*` fallbacks without invoking real fetch
    // (submit is never called, so no network happens).
    const { result } = renderHook(() => useUrlIngest());

    expect(result.current.status).toBe('idle');
    expect(typeof result.current.submit).toBe('function');
  });

  it('transitions submitting → queued on a successful post', async () => {
    const submitUrl = okSubmit();
    const { result } = renderHook(() => useUrlIngest({ submitUrl, delay: frozenDelay }));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    expect(submitUrl).toHaveBeenCalledWith('https://youtu.be/abc');
    expect(result.current.status).toBe('queued');
    expect(result.current.error).toBeNull();
  });

  it('surfaces the thrown error message on a failed post', async () => {
    const submitUrl = vi.fn<SubmitUrlRequest>().mockRejectedValue(new Error('YouTube заблокировал загрузку'));
    const { result } = renderHook(() => useUrlIngest({ submitUrl, delay: frozenDelay }));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe('YouTube заблокировал загрузку');
  });

  it('falls back to a generic message when the error has no message', async () => {
    const submitUrl = vi.fn<SubmitUrlRequest>().mockRejectedValue(new Error(''));
    const { result } = renderHook(() => useUrlIngest({ submitUrl, delay: frozenDelay }));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toMatch(/не удалось/i);
  });

  it('falls back to a generic message when a non-Error is thrown', async () => {
    const submitUrl = vi.fn<SubmitUrlRequest>().mockRejectedValue('plain string boom');
    const { result } = renderHook(() => useUrlIngest({ submitUrl, delay: frozenDelay }));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toMatch(/не удалось/i);
  });

  it('clears a prior error when a new submit succeeds', async () => {
    const submitUrl = vi
      .fn<SubmitUrlRequest>()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce('ingest:' + 'b'.repeat(64));
    const { result } = renderHook(() => useUrlIngest({ submitUrl, delay: frozenDelay }));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });
    expect(result.current.status).toBe('error');

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });
    expect(result.current.status).toBe('queued');
    expect(result.current.error).toBeNull();
  });

  it('surfaces a LOUD failure recorded by the worker via polling (never a silent hang)', async () => {
    const submitUrl = okSubmit();
    const pollStatus = vi
      .fn<(id: string) => Promise<IngestPollResult>>()
      .mockResolvedValueOnce({ status: 'pending' })
      .mockResolvedValueOnce({
        status: 'failed',
        error: 'YouTube заблокировал загрузку с нашего сервера.',
      });
    const immediate = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useUrlIngest({ submitUrl, pollStatus, delay: immediate }),
    );

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    // Polling is fire-and-forget; wait for the background loop to surface the failure.
    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toMatch(/youtube заблокировал/i);
    // Polled past the first `pending` before surfacing the failure.
    expect(pollStatus).toHaveBeenCalledTimes(2);
  });

  it('keeps polling through transient poll errors without surfacing them', async () => {
    const submitUrl = okSubmit();
    const pollStatus = vi
      .fn<(id: string) => Promise<IngestPollResult>>()
      .mockRejectedValueOnce(new Error('network blip'))
      .mockResolvedValueOnce({ status: 'failed', error: 'Видео приватное' });
    const immediate = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useUrlIngest({ submitUrl, pollStatus, delay: immediate }),
    );

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe('Видео приватное');
    expect(pollStatus).toHaveBeenCalledTimes(2);
  });

  it('stops polling after the bound when the download never reports a failure', async () => {
    const submitUrl = okSubmit();
    const pollStatus = vi
      .fn<(id: string) => Promise<IngestPollResult>>()
      .mockResolvedValue({ status: 'pending' });
    const immediate = vi.fn().mockResolvedValue(undefined);

    const { result } = renderHook(() =>
      useUrlIngest({ submitUrl, pollStatus, delay: immediate }),
    );

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    // The background loop polls up to the bound and then gives up (the download
    // either succeeded — surfacing in "Мои клипы" — or exceeded our window).
    await waitFor(() => expect(pollStatus).toHaveBeenCalledTimes(INGEST_MAX_POLLS));
    // Stays 'queued' (no failure was ever recorded), never an error.
    expect(result.current.status).toBe('queued');
    expect(result.current.error).toBeNull();
  });

  it('a newer submit supersedes a prior in-flight poll loop (no stale clobber)', async () => {
    // First submit's poll is parked on a slow delay; a second submit bumps the run
    // token. When the first delay resolves and the stale loop reports a failure, the
    // token check drops it — the second (queued) submit is never clobbered.
    let releaseFirstDelay: (() => void) | null = null;
    const delay = vi
      .fn<(ms: number) => Promise<void>>()
      // First submit's first poll-delay: held open until we release it.
      .mockImplementationOnce(() => new Promise<void>((resolve) => (releaseFirstDelay = resolve)))
      // Second submit's poll-delays: never resolve (keeps it parked at 'queued').
      .mockImplementation(() => new Promise<void>(() => {}));

    const pollStatus = vi
      .fn<(id: string) => Promise<IngestPollResult>>()
      .mockResolvedValue({ status: 'failed', error: 'stale failure' });

    const { result } = renderHook(() =>
      useUrlIngest({ submitUrl: okSubmit(), pollStatus, delay }),
    );

    await act(async () => {
      await result.current.submit('https://youtu.be/first');
    });
    await act(async () => {
      await result.current.submit('https://youtu.be/second');
    });

    // Release the first (now stale) loop's delay so it polls + tries to set error.
    await act(async () => {
      releaseFirstDelay?.();
      await Promise.resolve();
    });

    // The stale failure was dropped by the run-token guard — still 'queued', no error.
    expect(result.current.status).toBe('queued');
    expect(result.current.error).toBeNull();
  });

  it('drops a stale submit whose POST resolves after a newer submit began', async () => {
    // First submit's POST is held open; a second submit (fast) bumps the token and
    // reaches 'queued'. When the first POST finally resolves, its run is stale, so it
    // neither flips to 'queued' again nor starts a poll loop.
    let releaseFirstPost: ((id: string) => void) | null = null;
    const submitUrl = vi
      .fn<(url: string) => Promise<string>>()
      .mockImplementationOnce(() => new Promise<string>((resolve) => (releaseFirstPost = resolve)))
      .mockResolvedValueOnce('ingest:' + 'c'.repeat(64));
    const pollStatus = vi
      .fn<(id: string) => Promise<IngestPollResult>>()
      .mockResolvedValue({ status: 'pending' });

    const { result } = renderHook(() =>
      useUrlIngest({ submitUrl, pollStatus, delay: () => new Promise<void>(() => {}) }),
    );

    // Kick off the first submit (parked on its POST) without awaiting it.
    let firstSubmit: Promise<void> = Promise.resolve();
    await act(async () => {
      firstSubmit = result.current.submit('https://youtu.be/first');
      await Promise.resolve();
    });
    // Second submit resolves to 'queued' and bumps the run token.
    await act(async () => {
      await result.current.submit('https://youtu.be/second');
    });

    // Now resolve the stale first POST: its run is no longer current → dropped.
    await act(async () => {
      releaseFirstPost?.('ingest:' + 'd'.repeat(64));
      await firstSubmit;
    });

    expect(result.current.status).toBe('queued');
    expect(result.current.error).toBeNull();
  });

  it('drops a stale submit whose POST rejects after a newer submit began', async () => {
    let rejectFirstPost: ((err: Error) => void) | null = null;
    const submitUrl = vi
      .fn<(url: string) => Promise<string>>()
      .mockImplementationOnce(() => new Promise<string>((_, reject) => (rejectFirstPost = reject)))
      .mockResolvedValueOnce('ingest:' + 'e'.repeat(64));

    const { result } = renderHook(() =>
      useUrlIngest({ submitUrl, delay: () => new Promise<void>(() => {}) }),
    );

    let firstSubmit: Promise<void> = Promise.resolve();
    await act(async () => {
      firstSubmit = result.current.submit('https://youtu.be/first');
      await Promise.resolve();
    });
    await act(async () => {
      await result.current.submit('https://youtu.be/second');
    });

    // The stale first POST rejects: its run is stale → no error surfaces.
    await act(async () => {
      rejectFirstPost?.(new Error('stale boom'));
      await firstSubmit;
    });

    expect(result.current.status).toBe('queued');
    expect(result.current.error).toBeNull();
  });

  it('drops a poll result whose run goes stale between the poll and the token check', async () => {
    // The poll itself triggers a newer submit (bumping the token) before resolving
    // with a failure — so the post-poll token check drops the now-stale failure.
    const immediate = vi.fn().mockResolvedValue(undefined);
    let resultRef: { submit: (url: string) => Promise<void> } | null = null;
    let bumped = false;

    const pollStatus = vi.fn<(id: string) => Promise<IngestPollResult>>().mockImplementation(async () => {
      if (!bumped) {
        bumped = true;
        // A concurrent newer submit bumps the run token mid-poll. Its OWN poll loop
        // (next calls) returns pending, so only THIS stale call carries a failure.
        void resultRef?.submit('https://youtu.be/newer');
        return { status: 'failed', error: 'stale-after-poll' };
      }
      return { status: 'pending' };
    });

    const { result } = renderHook(() =>
      useUrlIngest({ submitUrl: okSubmit(), pollStatus, delay: immediate }),
    );
    resultRef = result.current;

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
      await Promise.resolve();
    });

    // The first loop's failure was dropped (stale); the newer submit is 'queued'.
    await waitFor(() => expect(pollStatus).toHaveBeenCalled());
    expect(result.current.error).not.toBe('stale-after-poll');
  });

  it('aborts an in-flight poll loop on unmount (no setState after teardown)', async () => {
    let releaseDelay: (() => void) | null = null;
    const delay = vi
      .fn<(ms: number) => Promise<void>>()
      .mockImplementation(() => new Promise<void>((resolve) => (releaseDelay = resolve)));
    const pollStatus = vi
      .fn<(id: string) => Promise<IngestPollResult>>()
      .mockResolvedValue({ status: 'failed', error: 'after unmount' });

    const { result, unmount } = renderHook(() =>
      useUrlIngest({ submitUrl: okSubmit(), pollStatus, delay }),
    );

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    unmount();
    // Releasing the delay AFTER unmount: the loop's token check aborts before polling.
    await act(async () => {
      releaseDelay?.();
      await Promise.resolve();
    });

    expect(pollStatus).not.toHaveBeenCalled();
  });
});
