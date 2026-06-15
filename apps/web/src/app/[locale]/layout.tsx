import type { Metadata, Viewport } from 'next';
import { hasLocale, NextIntlClientProvider } from 'next-intl';
import { setRequestLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { routing } from '@/libs/I18nRouting';
import { fontVariables } from '@/styles/fonts';
import { AppConfig } from '@/utils/AppConfig';
import { getBaseUrl } from '@/utils/Helpers';
import '@/styles/global.css';

/**
 * Maps the next-intl routing locale id to the BCP-47 language tag used on the
 * `<html lang>` attribute and OpenGraph `locale`. The product copy is Russian
 * regardless of the routing locale, so the default `en` routing slug must still
 * advertise `ru` to crawlers. The routing/message system is intentionally left
 * untouched — see FIX notes for the full locale-migration follow-up.
 */
const htmlLangByLocale: Record<string, string> = {
  en: 'ru',
  fr: 'fr',
};

const resolveHtmlLang = (locale: string): string => htmlLangByLocale[locale] ?? 'ru';

export const metadata: Metadata = {
  metadataBase: new URL(getBaseUrl()),
  title: {
    default: 'FlipHouse: одно видео, пачка ранжированных шортсов',
    template: '%s · FlipHouse',
  },
  description:
    'FlipHouse режет длинное видео на вертикальные шортсы 9:16, ранжирует их по виральности и добавляет субтитры по словам. Маркетплейс платит авторам за нативные размещения.',
  applicationName: AppConfig.name,
  openGraph: {
    type: 'website',
    siteName: AppConfig.name,
    locale: 'ru_RU',
    title: 'FlipHouse: одно видео, пачка ранжированных шортсов',
    description:
      'Загрузите длинное видео. FlipHouse найдёт залетающие моменты, переведёт в вертикаль 9:16 с удержанием спикера, добавит субтитры по словам и вернёт пачку, ранжированную по виральности.',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'FlipHouse: одно видео, пачка ранжированных шортсов',
    description:
      'Одно длинное видео превращается в пачку вертикальных шортсов, ранжированных по виральности. Плюс маркетплейс нативных размещений для авторов и рекламодателей.',
  },
  icons: [
    {
      rel: 'apple-touch-icon',
      url: '/apple-touch-icon.png',
    },
    {
      rel: 'icon',
      type: 'image/png',
      sizes: '32x32',
      url: '/favicon-32x32.png',
    },
    {
      rel: 'icon',
      type: 'image/png',
      sizes: '16x16',
      url: '/favicon-16x16.png',
    },
    {
      rel: 'icon',
      url: '/favicon.ico',
    },
  ],
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
};

export function generateStaticParams() {
  return routing.locales.map(locale => ({ locale }));
}

export default async function RootLayout(props: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await props.params;

  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  setRequestLocale(locale);

  return (
    <html lang={resolveHtmlLang(locale)} className={fontVariables} suppressHydrationWarning>
      <body>
        <NextIntlClientProvider>
          {props.children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
