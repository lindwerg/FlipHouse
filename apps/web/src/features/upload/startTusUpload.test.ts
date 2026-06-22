import type { TusUpload, TusUploadFactory, TusUploadOptions } from './startTusUpload';
import { describe, expect, it, vi } from 'vitest';
import { TUS_RETRY_DELAYS, startTusUpload } from './startTusUpload';

function fakeFile(name = 'clip.mp4', type = 'video/mp4', size = 1234): File {
  return { name, type, size } as unknown as File;
}

type FakeUploadConfig = {
  previous?: ReadonlyArray<{ urlStorageKey: string }>;
};

// A controllable fake of tus.Upload that records the options it was built with
// and exposes the captured lifecycle callbacks so a test can fire them.
function makeFakeUploadFactory(config: FakeUploadConfig = {}) {
  const calls = {
    options: null as TusUploadOptions | null,
    findPreviousUploads: 0,
    resumeFrom: null as unknown,
    start: 0,
    abort: 0,
  };

  const factory: TusUploadFactory = (_file, options) => {
    calls.options = options;
    const upload: TusUpload = {
      async findPreviousUploads() {
        calls.findPreviousUploads += 1;
        return (config.previous ?? []) as never;
      },
      resumeFromPreviousUpload(previous) {
        calls.resumeFrom = previous;
      },
      start() {
        calls.start += 1;
      },
      async abort() {
        calls.abort += 1;
      },
    };
    return upload;
  };

  return { factory, calls };
}

const baseArgs = {
  endpoint: 'http://localhost:1080/files/',
  ownerId: 'user_42',
  sha256: 'a'.repeat(64),
};

describe('startTusUpload', () => {
  it('builds tus metadata with ownerId, sha256, filename and filetype', async () => {
    const { factory, calls } = makeFakeUploadFactory();
    const file = fakeFile('my video.mp4', 'video/mp4');

    await startTusUpload(file, { ...baseArgs, uploadFactory: factory });

    expect(calls.options?.metadata).toEqual({
      ownerId: 'user_42',
      sha256: 'a'.repeat(64),
      filename: 'my video.mp4',
      filetype: 'video/mp4',
    });
  });

  it('configures the tus endpoint, retry delays and removeFingerprintOnSuccess', async () => {
    const { factory, calls } = makeFakeUploadFactory();

    await startTusUpload(fakeFile(), { ...baseArgs, uploadFactory: factory });

    expect(calls.options?.endpoint).toBe('http://localhost:1080/files/');
    expect(calls.options?.retryDelays).toEqual(TUS_RETRY_DELAYS);
    expect(calls.options?.removeFingerprintOnSuccess).toBe(true);
  });

  it('checks for previous uploads and starts when there are none', async () => {
    const { factory, calls } = makeFakeUploadFactory({ previous: [] });

    await startTusUpload(fakeFile(), { ...baseArgs, uploadFactory: factory });

    expect(calls.findPreviousUploads).toBe(1);
    expect(calls.resumeFrom).toBeNull();
    expect(calls.start).toBe(1);
  });

  it('resumes from the first previous upload before starting', async () => {
    const previous = [{ urlStorageKey: 'tus::1' }, { urlStorageKey: 'tus::2' }];
    const { factory, calls } = makeFakeUploadFactory({ previous });

    await startTusUpload(fakeFile(), { ...baseArgs, uploadFactory: factory });

    expect(calls.resumeFrom).toEqual({ urlStorageKey: 'tus::1' });
    expect(calls.start).toBe(1);
  });

  it('forwards onProgress to the tus options', async () => {
    const { factory, calls } = makeFakeUploadFactory();
    const onProgress = vi.fn();

    await startTusUpload(fakeFile(), { ...baseArgs, uploadFactory: factory, onProgress });

    calls.options?.onProgress?.(50, 100);

    expect(onProgress).toHaveBeenCalledWith(50, 100);
  });

  it('forwards onSuccess to the tus options', async () => {
    const { factory, calls } = makeFakeUploadFactory();
    const onSuccess = vi.fn();

    await startTusUpload(fakeFile(), { ...baseArgs, uploadFactory: factory, onSuccess });

    calls.options?.onSuccess?.({} as never);

    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it('forwards onError to the tus options', async () => {
    const { factory, calls } = makeFakeUploadFactory();
    const onError = vi.fn();
    const error = new Error('boom');

    await startTusUpload(fakeFile(), { ...baseArgs, uploadFactory: factory, onError });

    calls.options?.onError?.(error);

    expect(onError).toHaveBeenCalledWith(error);
  });

  it('returns a handle whose abort delegates to the tus upload', async () => {
    const { factory, calls } = makeFakeUploadFactory();

    const handle = await startTusUpload(fakeFile(), { ...baseArgs, uploadFactory: factory });
    await handle.abort();

    expect(calls.abort).toBe(1);
  });
});
