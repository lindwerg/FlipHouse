import { beforeEach, describe, expect, it, vi } from 'vitest';
import { getAccountType, setAccountType } from './accountType';

// Account type lives on the Clerk user's publicMetadata (no organizations, no
// DB — founder decision 2026-06-15). We mock the Clerk backend client.
const clerk = vi.hoisted(() => ({
  getUser: vi.fn(),
  updateUser: vi.fn(),
}));

vi.mock('@clerk/nextjs/server', () => ({
  clerkClient: vi.fn(async () => ({
    users: { getUser: clerk.getUser, updateUser: clerk.updateUser },
  })),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('accountType (Clerk publicMetadata)', () => {
  it('returns the account type stored on the user', async () => {
    clerk.getUser.mockResolvedValue({ publicMetadata: { accountType: 'creator' } });

    expect(await getAccountType('user_1')).toBe('creator');
  });

  it('returns null when the user has no account type yet', async () => {
    clerk.getUser.mockResolvedValue({ publicMetadata: {} });

    expect(await getAccountType('user_1')).toBeNull();
  });

  it('returns null for an unexpected metadata value', async () => {
    clerk.getUser.mockResolvedValue({ publicMetadata: { accountType: 'admin' } });

    expect(await getAccountType('user_1')).toBeNull();
  });

  it('writes the account type to publicMetadata when unset', async () => {
    clerk.getUser.mockResolvedValue({ publicMetadata: {} });

    await setAccountType('user_1', 'advertiser');

    expect(clerk.updateUser).toHaveBeenCalledWith('user_1', {
      publicMetadata: { accountType: 'advertiser' },
    });
  });

  it('throws and does not overwrite when already set (immutable)', async () => {
    clerk.getUser.mockResolvedValue({ publicMetadata: { accountType: 'creator' } });

    await expect(setAccountType('user_1', 'advertiser')).rejects.toThrow(
      /already set/,
    );
    expect(clerk.updateUser).not.toHaveBeenCalled();
  });
});
