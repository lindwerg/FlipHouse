// @vitest-environment jsdom
import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { UseVideoUploadDeps } from './useVideoUpload';
import { useVideoUpload } from './useVideoUpload';

function fakeFile(name = 'clip.mp4'): File {
  return { name, type: 'video/mp4', size: 10 } as unknown as File;
}

// A fully-injected deps set: grant, hashFile and startTusUpload are all swapped
// for controllable fakes so the hook's status machine is tested without fetch,
// a Worker, or a real tus PATCH.
function makeDeps(overrides: Partial<UseVideoUploadDeps> = {}): {
  deps: UseVideoUploadDeps;
  abort: ReturnType<typeof vi.fn>;
  tusCallbacks: { onSuccess?: () => void; onError?: (error: Error) => void; onProgress?: (sent: number, total: number) => void };
} {
  const abort = vi.fn().mockResolvedValue(undefined);
  const tusCallbacks: {
    onSuccess?: () => void;
    onError?: (error: Error) => void;
    onProgress?: (sent: number, total: number) => void;
  } = {};

  const deps: UseVideoUploadDeps = {
    fetchGrant: vi.fn().mockResolvedValue({ ownerId: 'user_42', tusEndpoint: 'http://t/files/' }),
    hashFile: vi.fn().mockResolvedValue('a'.repeat(64)),
    startTusUpload: vi.fn().mockImplementation((_file, args) => {
      tusCallbacks.onSuccess = args.onSuccess;
      tusCallbacks.onError = args.onError;
      tusCallbacks.onProgress = args.onProgress;
      return Promise.resolve({ abort });
    }),
    ...overrides,
  };

  return { deps, abort, tusCallbacks };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('useVideoUpload', () => {
  it('starts idle with no progress and no error', () => {
    const { deps } = makeDeps();
    const { result } = renderHook(() => useVideoUpload(deps));

    expect(result.current.status).toBe('idle');
    expect(result.current.progress).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it('runs grant → hash → upload and lands on done via onSuccess', async () => {
    const { deps, tusCallbacks } = makeDeps();
    const { result } = renderHook(() => useVideoUpload(deps));

    await act(async () => {
      await result.current.flip(fakeFile());
    });

    expect(deps.fetchGrant).toHaveBeenCalledTimes(1);
    expect(deps.hashFile).toHaveBeenCalledTimes(1);
    expect(deps.startTusUpload).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe('uploading');

    act(() => tusCallbacks.onSuccess?.());

    await waitFor(() => expect(result.current.status).toBe('done'));
  });

  it('passes the grant ownerId/endpoint and hashed sha256 to startTusUpload', async () => {
    const { deps } = makeDeps();
    const { result } = renderHook(() => useVideoUpload(deps));
    const file = fakeFile('vid.mp4');

    await act(async () => {
      await result.current.flip(file);
    });

    const [passedFile, args] = vi.mocked(deps.startTusUpload).mock.calls[0]!;

    expect(passedFile).toBe(file);
    expect(args.endpoint).toBe('http://t/files/');
    expect(args.ownerId).toBe('user_42');
    expect(args.sha256).toBe('a'.repeat(64));
  });

  it('updates progress from the tus onProgress callback', async () => {
    const { deps, tusCallbacks } = makeDeps();
    const { result } = renderHook(() => useVideoUpload(deps));

    await act(async () => {
      await result.current.flip(fakeFile());
    });

    act(() => tusCallbacks.onProgress?.(25, 100));

    await waitFor(() => expect(result.current.progress).toBe(25));
  });

  it('reports 0 progress when total bytes is not yet known (guards divide-by-zero)', async () => {
    const { deps, tusCallbacks } = makeDeps();
    const { result } = renderHook(() => useVideoUpload(deps));

    await act(async () => {
      await result.current.flip(fakeFile());
    });

    act(() => tusCallbacks.onProgress?.(0, 0));

    await waitFor(() => expect(result.current.progress).toBe(0));
  });

  it('sets status error when the grant returns 401 unauthenticated', async () => {
    const fetchGrant = vi.fn().mockRejectedValue(new Error('unauthenticated'));
    const { deps } = makeDeps({ fetchGrant });
    const { result } = renderHook(() => useVideoUpload(deps));

    await act(async () => {
      await result.current.flip(fakeFile());
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('unauthenticated');
    expect(deps.startTusUpload).not.toHaveBeenCalled();
  });

  it('sets status error when hashing fails', async () => {
    const hashFile = vi.fn().mockRejectedValue(new Error('hash boom'));
    const { deps } = makeDeps({ hashFile });
    const { result } = renderHook(() => useVideoUpload(deps));

    await act(async () => {
      await result.current.flip(fakeFile());
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('hash boom');
  });

  it('sets status error from the tus onError callback', async () => {
    const { deps, tusCallbacks } = makeDeps();
    const { result } = renderHook(() => useVideoUpload(deps));

    await act(async () => {
      await result.current.flip(fakeFile());
    });

    act(() => tusCallbacks.onError?.(new Error('upload failed')));

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error).toBe('upload failed');
  });

  it('falls back to a generic message when a non-Error is thrown', async () => {
    const fetchGrant = vi.fn().mockRejectedValue('weird');
    const { deps } = makeDeps({ fetchGrant });
    const { result } = renderHook(() => useVideoUpload(deps));

    await act(async () => {
      await result.current.flip(fakeFile());
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error).toBe('Не удалось загрузить видео');
  });

  it('re-submitting after an error clears the error and runs again', async () => {
    const hashFile = vi
      .fn()
      .mockRejectedValueOnce(new Error('hash boom'))
      .mockResolvedValue('b'.repeat(64));
    const { deps } = makeDeps({ hashFile });
    const { result } = renderHook(() => useVideoUpload(deps));

    await act(async () => {
      await result.current.flip(fakeFile());
    });
    expect(result.current.status).toBe('error');

    await act(async () => {
      await result.current.flip(fakeFile());
    });

    expect(result.current.status).toBe('uploading');
    expect(result.current.error).toBeNull();
  });
});
