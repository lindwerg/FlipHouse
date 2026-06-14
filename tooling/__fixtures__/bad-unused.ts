// Intentionally bad fixture for the ESLint guard test.
// Globally ignored by eslint.config.mjs so `pnpm lint` stays clean;
// the lint-config test lints it directly via the ESLint API.
export function sample(): number {
  const unused = 42;
  return 1;
}
