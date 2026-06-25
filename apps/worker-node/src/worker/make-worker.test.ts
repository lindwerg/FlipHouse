import type { Job } from 'bullmq';
import { expect, test, vi } from 'vitest';

import { attachWorkerObservability, type ListenableWorker } from './make-worker.js';

/** A tiny fake Worker that records its listeners so we can fire them. */
function fakeWorker(): {
  worker: ListenableWorker;
  fire: (event: 'failed' | 'error', ...args: unknown[]) => void;
} {
  const handlers: Record<string, (...args: never[]) => void> = {};
  const worker: ListenableWorker = {
    on(event: 'failed' | 'error', cb: (...args: never[]) => void) {
      handlers[event] = cb;
      return worker;
    },
  };
  return {
    worker,
    fire: (event, ...args) => handlers[event]?.(...(args as never[])),
  };
}

test('attachWorkerObservability logs structured fields when a job fails', () => {
  const { worker, fire } = fakeWorker();
  const logger = { error: vi.fn() };
  attachWorkerObservability(worker, 'cpu', logger);

  const job = { id: 'score-abc', attemptsMade: 3 } as unknown as Job;
  fire('failed', job, new Error('OpenRouter 402'));

  expect(logger.error).toHaveBeenCalledWith(
    { queue: 'cpu', jobId: 'score-abc', attemptsMade: 3, err: 'OpenRouter 402' },
    'worker job failed',
  );
});

test('attachWorkerObservability tolerates a missing job on the failed event', () => {
  const { worker, fire } = fakeWorker();
  const logger = { error: vi.fn() };
  attachWorkerObservability(worker, 'gpu', logger);

  fire('failed', undefined, new Error('lock lost'));

  expect(logger.error).toHaveBeenCalledWith(
    { queue: 'gpu', jobId: undefined, attemptsMade: undefined, err: 'lock lost' },
    'worker job failed',
  );
});

test('attachWorkerObservability logs a connection error', () => {
  const { worker, fire } = fakeWorker();
  const logger = { error: vi.fn() };
  attachWorkerObservability(worker, 'cpu', logger);

  fire('error', new Error('ECONNREFUSED redis'));

  expect(logger.error).toHaveBeenCalledWith(
    { queue: 'cpu', err: 'ECONNREFUSED redis' },
    'worker connection error',
  );
});
