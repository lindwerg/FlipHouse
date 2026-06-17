/** How to invoke the Python stage CLI (`python -m fliphouse_worker.cli`). */
export interface PythonEntry {
  readonly command: string;
  readonly baseArgs: readonly string[];
}

/**
 * Resolve the Python interpreter + module entry from the environment. The
 * interpreter is overridable via `FLIPHOUSE_PYTHON` (e.g. a venv path on
 * Railway); the stage name is appended by the caller.
 */
export function resolvePythonEntry(env: NodeJS.ProcessEnv = process.env): PythonEntry {
  return {
    command: env.FLIPHOUSE_PYTHON ?? 'python',
    baseArgs: ['-m', 'fliphouse_worker.cli'],
  };
}
