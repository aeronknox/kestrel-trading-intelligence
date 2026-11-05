/**
 * Same-origin proxy to the FastAPI backend.
 *
 * Keeping the API behind the Next.js origin means the session cookie is
 * first-party, httpOnly and SameSite=Lax — no tokens in JavaScript, no CORS
 * credentials juggling. The backend URL is read at runtime (BACKEND_INTERNAL_URL).
 */
import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const BACKEND = (process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
const PROXY_SECRET = process.env.PROXY_SHARED_SECRET ?? "";
const TRUST_PROXY_HEADERS = process.env.TRUST_PROXY_HEADERS === "true";

const FORWARD_REQUEST_HEADERS = ["content-type", "cookie", "user-agent", "accept", "x-request-id", "authorization"];
const DROP_RESPONSE_HEADERS = new Set(["connection", "keep-alive", "transfer-encoding", "content-encoding", "content-length", "set-cookie"]);

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const target = `${BACKEND}/api/v1/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  for (const name of FORWARD_REQUEST_HEADERS) {
    const v = req.headers.get(name);
    if (v) headers.set(name, v);
  }
  // Browsers can send their own X-Forwarded-For, and Next.js passes it through unchanged.
  // Only relay it when a trusted reverse proxy (nginx, a load balancer…) in front of this
  // server sets it; the shared secret then proves to the API that this hop is our proxy.
  if (TRUST_PROXY_HEADERS && PROXY_SECRET) {
    const clientIp = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || req.headers.get("x-real-ip") || "";
    if (clientIp) headers.set("x-forwarded-for", clientIp);
    headers.set("x-proxy-secret", PROXY_SECRET);
  }

  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { error: { code: "backend_unavailable", message: "The API server is unreachable. Is the backend running?" } },
      { status: 503 },
    );
  }

  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!DROP_RESPONSE_HEADERS.has(key.toLowerCase())) out.set(key, value);
  });
  for (const cookie of upstream.headers.getSetCookie()) out.append("set-cookie", cookie);

  return new Response(upstream.status === 204 ? null : upstream.body, { status: upstream.status, headers: out });
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE };
