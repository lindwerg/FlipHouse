import { describe, expect, it } from 'vitest';
import { uploadBadge } from './upload-badge';

describe('uploadBadge', () => {
  it('maps done to готово', () => {
    expect(uploadBadge('done')).toEqual({ label: 'готово', color: 'var(--foreground)' });
  });

  it('maps failed to ошибка', () => {
    expect(uploadBadge('failed')).toEqual({ label: 'ошибка', color: 'var(--pop)' });
  });

  it('maps duplicate to дубликат', () => {
    expect(uploadBadge('duplicate')).toEqual({ label: 'дубликат', color: 'var(--ink-soft)' });
  });

  it('collapses every non-terminal stage to обрабатывается', () => {
    for (const status of ['queued', 'hashing', 'scoring', 'rendering', 'publishing'] as const) {
      expect(uploadBadge(status).label).toBe('обрабатывается');
    }
  });
});
