import { NextResponse, type NextRequest } from "next/server";

import { contentSecurityPolicy } from "@/lib/csp";

/** Gives every page request a fresh CSP nonce; see src/lib/csp.ts for the policy. */
export function proxy(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const csp = contentSecurityPolicy(nonce);
  // Next.js reads the nonce from the request's CSP header while rendering.
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", csp);
  return response;
}

export const config = {
  matcher: [
    {
      // Pages only: not the API proxy, static files or prefetches.
      source: "/((?!api/|_next/static|_next/image|favicon.ico|icon|apple-icon).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
