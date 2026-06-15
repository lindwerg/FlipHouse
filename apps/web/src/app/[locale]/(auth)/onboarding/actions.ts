'use server';

import type { AccountType } from '@/libs/accountType';
import { auth } from '@clerk/nextjs/server';
import { redirect } from 'next/navigation';
import { setAccountType } from '@/libs/accountType';
import { routing } from '@/libs/I18nRouting';
import { getI18nPath } from '@/utils/Helpers';

/**
 * Onboarding server action: persists the chosen role on the signed-in user
 * (immutable — throws if already set) and routes to the matching dashboard.
 * @param type The account type the user picked.
 * @param locale The active locale (drives the locale-aware redirect).
 */
export async function selectAccountType(
  type: AccountType,
  locale: string = routing.defaultLocale,
): Promise<void> {
  const { userId } = await auth();

  if (!userId) {
    redirect(getI18nPath('/sign-in', locale));
  }

  await setAccountType(userId, type);

  redirect(getI18nPath(`/dashboard/${type}`, locale));
}
