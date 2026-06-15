import { auth } from '@clerk/nextjs/server';
import { redirect } from 'next/navigation';
import { getAccountType } from '@/libs/accountType';
import { getI18nPath } from '@/utils/Helpers';

// Dashboard index is a router: it sends the signed-in user to their typed
// dashboard, or to onboarding when no role has been chosen yet. The per-type
// dashboards enforce the matching gate via `requireAccountType`.
export default async function DashboardIndexPage(props: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;
  const { userId } = await auth();

  if (!userId) {
    redirect(getI18nPath('/sign-in', locale));
  }

  const accountType = await getAccountType(userId);

  if (accountType === null) {
    redirect(getI18nPath('/onboarding', locale));
  }

  redirect(getI18nPath(`/dashboard/${accountType}`, locale));
}

export const dynamic = 'force-dynamic';
