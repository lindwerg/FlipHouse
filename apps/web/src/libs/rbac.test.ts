import { auth } from '@clerk/nextjs/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAccountType } from '@/libs/accountType';
import { requireAccountType } from './rbac';

// `redirect` throws in Next (NEXT_REDIRECT) so control never returns past it.
// The mock mirrors that by throwing, encoding the target path in the message —
// this both stops execution (like prod) and lets us assert the destination.
vi.mock('next/navigation', () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));
vi.mock('@/libs/accountType', () => ({ getAccountType: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
});

describe('requireAccountType', () => {
  it('requireAccountType allows matching type', async () => {
    vi.mocked(getAccountType).mockResolvedValue('creator');

    await expect(requireAccountType('creator')).resolves.toBe('creator');
  });

  it('requireAccountType redirects creator away from advertiser dashboard', async () => {
    vi.mocked(getAccountType).mockResolvedValue('creator');

    await expect(requireAccountType('advertiser')).rejects.toThrow(
      'REDIRECT:/dashboard/creator',
    );
  });

  it('redirects to /onboarding when accountType is null', async () => {
    vi.mocked(getAccountType).mockResolvedValue(null);

    await expect(requireAccountType('creator')).rejects.toThrow(
      'REDIRECT:/onboarding',
    );
  });

  it('redirects to sign-in when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    await expect(requireAccountType('creator')).rejects.toThrow(
      'REDIRECT:/sign-in',
    );
    expect(getAccountType).not.toHaveBeenCalled();
  });
});
