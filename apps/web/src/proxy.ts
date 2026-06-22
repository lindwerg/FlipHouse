import type { NextFetchEvent, NextRequest } from 'next/server';
import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import createMiddleware from 'next-intl/middleware';
import { routing } from './libs/I18nRouting';

const handleI18nRouting = createMiddleware(routing);

const isProtectedRoute = createRouteMatcher([
  '/dashboard(.*)',
  '/:locale/dashboard(.*)',
  '/onboarding(.*)',
  '/:locale/onboarding(.*)',
]);

const isAuthPage = createRouteMatcher([
  '/sign-in(.*)',
  '/:locale/sign-in(.*)',
  '/sign-up(.*)',
  '/:locale/sign-up(.*)',
]);

// Authenticated API routes (upload grant, clips dashboard, SSE progress) call
// Clerk's `auth()` in their handlers, so they need clerkMiddleware() context —
// but NOT i18n locale routing (that would mangle API paths). The public
// `/api/health` stays excluded from the matcher and bypasses Clerk entirely.
const isClerkApiRoute = createRouteMatcher(['/api/uploads(.*)']);

export default async function proxy(
  request: NextRequest,
  event: NextFetchEvent,
) {
  // Attach the Clerk auth context to authed API routes and continue (no i18n).
  if (isClerkApiRoute(request)) {
    return clerkMiddleware()(request, event);
  }

  // Clerk keyless mode doesn't work with i18n, this is why we need to run the middleware conditionally
  if (
    isAuthPage(request) || isProtectedRoute(request)
  ) {
    return clerkMiddleware(async (auth, req) => {
      // Check if the current route is protected and requires authentication
      // If user is not authenticated, redirect them to the sign-in page with proper locale
      if (isProtectedRoute(req)) {
        const locale = req.nextUrl.pathname.match(/(\/.*)\/dashboard/)?.at(1) ?? '';

        const signInUrl = new URL(`${locale}/sign-in`, req.url);

        await auth.protect({
          unauthenticatedUrl: signInUrl.toString(),
        });
      }

      // FlipHouse has no organizations: a signed-in user picks a role on
      // /onboarding (stored on the Clerk user). The role gate for the dashboard
      // lives in the route components via requireAccountType, not here.
      return handleI18nRouting(req);
    })(request, event);
  }

  return handleI18nRouting(request);
}

export const config = {
  // Match all pathnames except for
  // - … if they start with `/_next`, `/_vercel`, `monitoring` or `api`
  //   (most `/api/*` bypasses Clerk + i18n, e.g. the public healthcheck)
  // - … the ones containing a dot (e.g. `favicon.ico`)
  // PLUS the authed upload API routes, which DO need Clerk auth() context.
  matcher: [
    '/((?!_next|_vercel|monitoring|api|.*\\..*).*)',
    '/api/uploads/:path*',
  ],
};
