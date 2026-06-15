import { clerkClient } from '@clerk/nextjs/server';

// The FlipHouse role of a user. Stored on the Clerk user's publicMetadata —
// there are no organizations; a user signs up, picks a role, and proceeds
// (founder decision 2026-06-15).
export type AccountType = 'creator' | 'advertiser';

function readAccountType(publicMetadata: unknown): AccountType | null {
  const value = (publicMetadata as { accountType?: unknown } | null | undefined)
    ?.accountType;

  return value === 'creator' || value === 'advertiser' ? value : null;
}

/**
 * Reads the account type from a Clerk user's publicMetadata.
 * @param userId The Clerk user id.
 * @returns The stored role, or `null` when the user has not onboarded.
 */
export async function getAccountType(userId: string): Promise<AccountType | null> {
  const client = await clerkClient();
  const user = await client.users.getUser(userId);

  return readAccountType(user.publicMetadata);
}

/**
 * Persists the account type on a Clerk user. Immutable once set: a second call
 * for a user that already has a role throws.
 * @param userId The Clerk user id.
 * @param type The role chosen during onboarding.
 * @throws When the user already has an account type.
 */
export async function setAccountType(userId: string, type: AccountType): Promise<void> {
  const existing = await getAccountType(userId);
  if (existing !== null) {
    throw new Error('account type already set');
  }

  const client = await clerkClient();
  await client.users.updateUser(userId, { publicMetadata: { accountType: type } });
}
