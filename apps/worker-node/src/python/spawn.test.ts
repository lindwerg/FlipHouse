import { EventEmitter } from 'node:events';

import { STAGE_REQUEST_VERSION } from '@fliphouse/shared';
import type { StageRequest } from '@fliphouse/shared';
import { expect, test } from 'vitest';

import { RESULT_FRAME_PREFIX, runPythonStage } from './spawn.js';

const REQ: StageRequest = {
  version: STAGE_REQUEST_VERSION,
  stage: 'transcode',
  contentHash: 'a'.repeat(64),
  ownerId: 'user_1',
  inputs: { source: 'uploads/a.mp4' },
  outputPrefix: 'intermediate/abc/transcode',
  params: {},
};

class FakeChild extends EventEmitter {
  readonly stdout = new EventEmitter();
  readonly stderr = new EventEmitter();
  readonly stdinWrites: string[] = [];
  stdinEnded = false;
  readonly stdin = {
    write: (chunk: string): void => {
      this.stdinWrites.push(chunk);
    },
    end: (): void => {
      this.stdinEnded = true;
    },
  };
  readonly killed: Array<NodeJS.Signals | number | undefined> = [];

  constructor(readonly pid: number | undefined = 4321) {
    super();
  }

  kill(signal?: NodeJS.Signals | number): boolean {
    this.killed.push(signal);
    return true;
  }

  emitStdout(s: string): void {
    this.stdout.emit('data', s);
  }

  emitStderr(s: string): void {
    this.stderr.emit('data', s);
  }

  frame(result: unknown): void {
    this.emitStdout(`${RESULT_FRAME_PREFIX}${JSON.stringify(result)}`);
  }
}

function spawnReturning(child: FakeChild): () => FakeChild {
  return () => child;
}

test('returns the framed success result and forwards the request on stdin', async () => {
  const child = new FakeChild();
  const promise = runPythonStage(REQ, { _spawn: spawnReturning(child) });
  child.emitStdout('mediapipe banner noise\n');
  child.frame({ ok: true, outputs: [{ key: 'out/clip_000.mp4' }], metrics: { ms: 10 } });
  child.emit('close', 0, null);

  await expect(promise).resolves.toEqual({
    ok: true,
    outputs: [{ key: 'out/clip_000.mp4' }],
    metrics: { ms: 10 },
  });
  expect(child.stdinWrites.join('')).toBe(JSON.stringify(REQ));
  expect(child.stdinEnded).toBe(true);
});

test('returns a framed failure as-is even on a non-zero exit', async () => {
  const child = new FakeChild();
  const promise = runPythonStage(REQ, { _spawn: spawnReturning(child) });
  child.frame({ ok: false, kind: 'fatal', code: 'OPENROUTER_402', message: 'no credits' });
  child.emit('close', 1, null);

  await expect(promise).resolves.toEqual({
    ok: false,
    kind: 'fatal',
    code: 'OPENROUTER_402',
    message: 'no credits',
  });
});

test('synthesizes NO_RESULT when stdout has no framed envelope', async () => {
  const child = new FakeChild();
  const promise = runPythonStage(REQ, { _spawn: spawnReturning(child) });
  child.emit('close', 1, null);

  await expect(promise).resolves.toMatchObject({ ok: false, kind: 'retryable', code: 'NO_RESULT' });
});

test('synthesizes KILLED when the subprocess dies on a signal', async () => {
  const child = new FakeChild();
  const promise = runPythonStage(REQ, { _spawn: spawnReturning(child) });
  child.emit('close', null, 'SIGKILL');

  await expect(promise).resolves.toMatchObject({ ok: false, kind: 'retryable', code: 'KILLED' });
});

test('synthesizes SPAWN_FAILED on a spawn error (and ignores a later close)', async () => {
  const child = new FakeChild();
  const promise = runPythonStage(REQ, { _spawn: spawnReturning(child) });
  child.emit('error', new Error('ENOENT python'));
  child.emit('close', 1, null); // settled guard: must not change the result

  await expect(promise).resolves.toMatchObject({ ok: false, kind: 'retryable', code: 'SPAWN_FAILED' });
});

test('synthesizes BAD_RESULT for invalid JSON and for schema-mismatched envelopes', async () => {
  const badJson = new FakeChild();
  const p1 = runPythonStage(REQ, { _spawn: spawnReturning(badJson) });
  badJson.emitStdout(`${RESULT_FRAME_PREFIX}{not json`);
  badJson.emit('close', 0, null);
  await expect(p1).resolves.toMatchObject({ ok: false, code: 'BAD_RESULT' });

  const badShape = new FakeChild();
  const p2 = runPythonStage(REQ, { _spawn: spawnReturning(badShape) });
  badShape.frame({ ok: 'maybe' });
  badShape.emit('close', 0, null);
  await expect(p2).resolves.toMatchObject({ ok: false, code: 'BAD_RESULT' });
});

test('emits complete stderr lines and buffers partial ones', async () => {
  const child = new FakeChild();
  const lines: string[] = [];
  const promise = runPythonStage(REQ, { _spawn: spawnReturning(child), onStderrLine: (l) => lines.push(l) });
  child.emitStderr('partial'); // no newline → buffered
  child.emitStderr(' first\nsecond\n');
  child.frame({ ok: true, outputs: [], metrics: {} });
  child.emit('close', 0, null);

  await promise;
  expect(lines).toEqual(['partial first', 'second']);
});

test('stderr without an onStderrLine callback does not throw', async () => {
  const child = new FakeChild();
  const promise = runPythonStage(REQ, { _spawn: spawnReturning(child) });
  child.emitStderr('ignored\n');
  child.frame({ ok: true, outputs: [], metrics: {} });
  child.emit('close', 0, null);

  await expect(promise).resolves.toMatchObject({ ok: true });
});

test('an already-aborted signal kills the process group and returns ABORTED', async () => {
  const controller = new AbortController();
  controller.abort();
  const child = new FakeChild(999);
  const kills: Array<[number, NodeJS.Signals]> = [];
  const result = await runPythonStage(REQ, {
    signal: controller.signal,
    _spawn: spawnReturning(child),
    _processKill: (pid, sig) => kills.push([pid, sig]),
  });

  expect(result).toMatchObject({ ok: false, kind: 'retryable', code: 'ABORTED' });
  expect(kills).toEqual([[-999, 'SIGKILL']]);
});

test('aborting mid-run kills the group', async () => {
  const controller = new AbortController();
  const child = new FakeChild(50);
  const kills: Array<[number, NodeJS.Signals]> = [];
  const promise = runPythonStage(REQ, {
    signal: controller.signal,
    _spawn: spawnReturning(child),
    _processKill: (pid, sig) => kills.push([pid, sig]),
  });
  controller.abort();

  await expect(promise).resolves.toMatchObject({ code: 'ABORTED' });
  expect(kills).toEqual([[-50, 'SIGKILL']]);
});

test('falls back to child.kill when the pid is unknown', async () => {
  const controller = new AbortController();
  const child = new FakeChild();
  // A default parameter would resurrect 4321 from `undefined`, so unset it directly.
  (child as unknown as { pid: number | undefined }).pid = undefined;
  const kills: number[] = [];
  const promise = runPythonStage(REQ, {
    signal: controller.signal,
    _spawn: spawnReturning(child),
    _processKill: (pid) => kills.push(pid),
  });
  controller.abort();

  await promise;
  expect(child.killed).toContain('SIGKILL');
  expect(kills).toHaveLength(0);
});

test('falls back to child.kill when the group kill throws', async () => {
  const controller = new AbortController();
  const child = new FakeChild(7);
  const promise = runPythonStage(REQ, {
    signal: controller.signal,
    _spawn: spawnReturning(child),
    _processKill: () => {
      throw new Error('EPERM');
    },
  });
  controller.abort();

  await promise;
  expect(child.killed).toContain('SIGKILL');
});
