import { auth } from '@clerk/nextjs/server';
import { redirect } from 'next/navigation';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { setAccountType } from '@/libs/accountType';
import { selectAccountType } from './actions';

// `redirect` throws in Next; the mock encodes the path so we can assert the
// destination while stopping execution the way prod does.
vi.mock('next/navigation', () => ({
  redirect: vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
}));
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));
vi.mock('@/libs/accountType', () => ({ setAccountType: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
});

describe('selectAccountType', () => {
  it('selectAccountType writes creator to user and redirects to /dashboard/creator', async () => {
    await expect(selectAccountType('creator')).rejects.toThrow(
      'REDIRECT:/dashboard/creator',
    );

    expect(setAccountType).toHaveBeenCalledWith('user_1', 'creator');
  });

  it('selectAccountType writes advertiser and redirects to /dashboard/advertiser', async () => {
    await expect(selectAccountType('advertiser')).rejects.toThrow(
      'REDIRECT:/dashboard/advertiser',
    );

    expect(setAccountType).toHaveBeenCalledWith('user_1', 'advertiser');
  });

  it('selectAccountType rejects when the user already has a type', async () => {
    vi.mocked(setAccountType).mockRejectedValue(
      new Error('account type already set'),
    );

    await expect(selectAccountType('creator')).rejects.toThrow('already set');
    expect(redirect).not.toHaveBeenCalled();
  });

  it('redirects to sign-in when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    await expect(selectAccountType('creator')).rejects.toThrow(
      'REDIRECT:/sign-in',
    );
    expect(setAccountType).not.toHaveBeenCalled();
  });
});
