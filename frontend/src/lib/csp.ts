/**
 * Content-Security-Policy for pages, with a per-request script nonce (see src/proxy.ts).
 *
 * Only scripts carrying the nonce run (Next.js adds it to its own scripts; the root layout
 * adds it to the theme script), plus what they load ('strict-dynamic'). An injected <script>
 * or inline event handler is blocked. Styles stay 'unsafe-inline' because the chart
 * libraries set style attributes, which nonces can't cover.
 */

/** ws(s):// origin of the live price socket (NEXT_PUBLIC_WS_URL is fixed at build time). */
export function socketOrigin(url = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/api/v1/ws/market"): string {
  try {
    return new URL(url).origin.replace(/^http/, "ws");
  } catch {
    return "";
  }
}

export function contentSecurityPolicy(nonce: string, dev = process.env.NODE_ENV === "development", wsOrigin = socketOrigin()): string {
  return [
    "default-src 'self'",
    // React uses eval only in development, for better error stacks.
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' ${wsOrigin}`.trim(),
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}
