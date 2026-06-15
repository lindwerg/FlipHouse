import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';
import './src/libs/Env';

// Base Next.js configuration. Sentry / bundle-analyzer wrappers from the
// upstream ixartz/SaaS-Boilerplate are intentionally dropped for FlipHouse P1
// (peripheral tooling, re-introduced later only if needed).
const baseConfig: NextConfig = {
  devIndicators: {
    position: 'bottom-right',
  },
  poweredByHeader: false,
  reactStrictMode: true,
  reactCompiler: process.env.NODE_ENV === 'production', // Keep the development environment fast
  logging: {
    browserToTerminal: process.env.BROWSER_TO_TERMINAL_DISABLED !== 'true',
  },
  outputFileTracingIncludes: {
    '/': ['./migrations/**/*'],
  },
};

const nextConfig = createNextIntlPlugin('./src/libs/I18n.ts')(baseConfig);

export default nextConfig;
