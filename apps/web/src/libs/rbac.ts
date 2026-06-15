import type { AccountType } from '@/libs/accountType';
import { auth } from '@clerk/nextjs/server';
import { redirect } from 'next/navigation';
import { getAccountType } from '@/libs/accountType';
import { getI18nPath } from '@/utils/Helpers';
import { routing } from './I18nRouting';

/**
 * Gates a dashboard route by the signed-in user's account type.
 *
 * - Not signed in → sign-in.
 * - No account type yet (onboarding incomplete) → `/onboarding`.
 * - Account type set but mismatched → the user's own dashboard (e.g. a creator
 *   hitting the advertiser dashboard is sent to `/dashboard/creator`).
 * - Matching type → returns it so the caller can proceed.
 *
 * @param type The account type the route requires.
 * @param locale The active locale (drives locale-aware redirects).
 * @returns The user's account type when it matches the required one.
 */
export async function requireAccountType(
  type: AccountType,
  locale: string = routing.defaultLocale,
): Promise<AccountType> {
  const { userId } = await auth();

  if (!userId) {
    redirect(getI18nPath('/sign-in', locale));
  }

  const accountType = await getAccountType(userId);

  if (accountType === null) {
    redirect(getI18nPath('/onboarding', locale));
  }

  if (accountType !== type) {
    redirect(getI18nPath(`/dashboard/${accountType}`, locale));
  }

  return accountType;
}
