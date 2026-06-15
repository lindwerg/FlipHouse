import { describe, expect, it } from 'vitest';
import {
  ALLOWED_REVEAL_PROPERTIES,
  BANNED_ANIMATION_PROPERTIES,
  REVEAL_CONFIGS,
  revealProperties,
} from './scrollReveal';

describe('scrollReveal configs', () => {
  it('reveal animations only touch transform/opacity/clip-path', () => {
    const allowed = new Set<string>(ALLOWED_REVEAL_PROPERTIES);
    const banned = new Set<string>(BANNED_ANIMATION_PROPERTIES);

    const configs = Object.values(REVEAL_CONFIGS);
    expect(configs.length).toBeGreaterThan(0);

    for (const config of configs) {
      const props = revealProperties(config);
      expect(props.length).toBeGreaterThan(0);
      for (const prop of props) {
        expect(allowed.has(prop)).toBe(true);
        expect(banned.has(prop)).toBe(false);
      }
    }
  });
});
