import { describe, expect, it } from "vitest";

import { contentSecurityPolicy, socketOrigin } from "./csp";

function directives(policy: string): Record<string, string> {
  return Object.fromEntries(policy.split("; ").map((d) => [d.split(" ")[0], d.slice(d.indexOf(" ") + 1)]));
}

describe("contentSecurityPolicy", () => {
  it("only runs scripts carrying the nonce in production", () => {
    const d = directives(contentSecurityPolicy("abc123", false, "wss://example.com"));
    expect(d["script-src"]).toBe("'self' 'nonce-abc123' 'strict-dynamic'");
    expect(d["script-src"]).not.toContain("unsafe-inline");
    expect(d["object-src"]).toBe("'none'");
    expect(d["frame-ancestors"]).toBe("'none'");
    expect(d["connect-src"]).toBe("'self' wss://example.com");
  });

  it("allows eval only in development", () => {
    expect(directives(contentSecurityPolicy("n", true, ""))["script-src"]).toContain("'unsafe-eval'");
    expect(directives(contentSecurityPolicy("n", false, ""))["script-src"]).not.toContain("'unsafe-eval'");
  });
});

describe("socketOrigin", () => {
  it("keeps the scheme and host of the socket URL", () => {
    expect(socketOrigin("wss://trading.example.com/api/v1/ws/market")).toBe("wss://trading.example.com");
    expect(socketOrigin("ws://localhost:8000/api/v1/ws/market")).toBe("ws://localhost:8000");
    expect(socketOrigin("not a url")).toBe("");
  });
});
