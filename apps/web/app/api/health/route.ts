import { buildHealthPayload } from '@/lib/health';

// Railway healthcheck endpoint (docs/01 §7). Static so it never touches a DB.
export const dynamic = 'force-static';

export function GET(): Response {
  return Response.json(buildHealthPayload());
}
