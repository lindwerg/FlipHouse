// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useUrlIngest } from './useUrlIngest';

describe('useUrlIngest', () => {
  it('starts idle with no error', () => {
    const { result } = renderHook(() => useUrlIngest(vi.fn().mockResolvedValue(undefined)));

    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  it('transitions submitting → queued on a successful post', async () => {
    const postUrl = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useUrlIngest(postUrl));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    expect(postUrl).toHaveBeenCalledWith('https://youtu.be/abc');
    expect(result.current.status).toBe('queued');
    expect(result.current.error).toBeNull();
  });

  it('surfaces the thrown error message on a failed post', async () => {
    const postUrl = vi.fn().mockRejectedValue(new Error('YouTube заблокировал загрузку'));
    const { result } = renderHook(() => useUrlIngest(postUrl));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe('YouTube заблокировал загрузку');
  });

  it('falls back to a generic message when the error has no message', async () => {
    const postUrl = vi.fn().mockRejectedValue(new Error(''));
    const { result } = renderHook(() => useUrlIngest(postUrl));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toMatch(/не удалось/i);
  });

  it('falls back to a generic message when a non-Error is thrown', async () => {
    const postUrl = vi.fn().mockRejectedValue('plain string boom');
    const { result } = renderHook(() => useUrlIngest(postUrl));

    await act(async () => {
      await result.current.submit('https://youtu.be/abc');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toMatch(/не удалось/i);
  });

  it('clears a prior error when a new submit succeeds', async () => {
    const postUrl = vi
      .fn()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce(undefined);
    const { result } = renderHook(() => useUrlIngest(postUrl));

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
});
