import type { Metadata } from 'next';
import { setRequestLocale } from 'next-intl/server';
import { Landing } from '@/components/landing/Landing';
import { ScrollProvider } from '@/components/landing/ScrollProvider';
import { routing } from '@/libs/I18nRouting';
import { AppConfig } from '@/utils/AppConfig';
import { getBaseUrl, getI18nPath } from '@/utils/Helpers';

type IndexProps = {
  params: Promise<{ locale: string }>;
};

const PAGE_TITLE = 'FlipHouse: одно видео, пачка ранжированных шортсов';
const PAGE_DESCRIPTION
  = 'FlipHouse режет длинное видео на вертикальные шортсы 9:16, ранжирует их по виральности и добавляет субтитры по словам. Маркетплейс платит авторам за нативные размещения.';

export async function generateMetadata(props: IndexProps): Promise<Metadata> {
  const { locale } = await props.params;

  const canonical = getI18nPath('/', locale);
  const languages = Object.fromEntries(
    routing.locales.map(loc => [loc, getI18nPath('/', loc)]),
  );

  return {
    // `absolute` opts out of the root layout title template so the homepage
    // does not render as "FlipHouse — … · FlipHouse".
    title: { absolute: PAGE_TITLE },
    description: PAGE_DESCRIPTION,
    alternates: {
      canonical,
      languages: {
        ...languages,
        'x-default': getI18nPath('/', routing.defaultLocale),
      },
    },
    openGraph: {
      url: canonical,
      title: PAGE_TITLE,
      description: PAGE_DESCRIPTION,
    },
  };
}

export default async function Index(props: IndexProps) {
  const { locale } = await props.params;
  setRequestLocale(locale);

  const baseUrl = getBaseUrl();

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'WebApplication',
    'name': AppConfig.name,
    'url': baseUrl,
    'applicationCategory': 'MultimediaApplication',
    'operatingSystem': 'Web',
    'inLanguage': 'ru-RU',
    'description': PAGE_DESCRIPTION,
    'offers': {
      '@type': 'Offer',
      'price': '0',
      'priceCurrency': 'USD',
    },
  };

  return (
    <>
      <script
        type="application/ld+json"
        // JSON-LD is a trusted, statically-built object — safe to inline.
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <Landing />
      <ScrollProvider />
    </>
  );
};
