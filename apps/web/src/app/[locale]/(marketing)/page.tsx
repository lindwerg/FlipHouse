import type { Metadata } from 'next';
import { setRequestLocale } from 'next-intl/server';
import { Landing } from '@/components/landing/Landing';

type IndexProps = {
  params: Promise<{ locale: string }>;
};

export const metadata: Metadata = {
  title: 'FlipHouse — одно видео, пачка ранжированных шортсов',
  description:
    'FlipHouse превращает одно длинное видео в ранжированную пачку вертикальных шортсов — авто-нарезка, реврейм 9:16, субтитры. Плюс маркетплейс, который платит креаторам за нативные размещения.',
};

export default async function Index(props: IndexProps) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  return <Landing />;
};
