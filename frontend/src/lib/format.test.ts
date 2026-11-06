import { describe, expect, it } from "vitest";

import { formatPct, formatPrice, formatUsd, pnlClass, timeAgo } from "./format";

describe("formatters", () => {
  it("adapts price precision to magnitude", () => {
    expect(formatPrice(79494.17)).toBe("79,494.17");
    expect(formatPrice(0.19412)).toBe("0.1941");
    expect(formatPrice(0.000012345)).toBe("0.000012");
    expect(formatPrice(null)).toBe("—");
  });

  it("formats signed currency and percentages", () => {
    expect(formatUsd(1234.5, { sign: true })).toBe("+$1,234.50");
    expect(formatUsd(-50)).toBe("-$50.00");
    expect(formatPct(3.14159)).toBe("+3.14%");
    expect(formatPct(-1)).toBe("-1.00%");
    expect(formatPct(Number.NaN)).toBe("—");
  });

  it("colors P&L", () => {
    expect(pnlClass(1)).toBe("text-gain");
    expect(pnlClass(-1)).toBe("text-loss");
    expect(pnlClass(0)).toBe("text-muted-foreground");
  });

  it("renders relative times", () => {
    const now = new Date("2026-01-01T12:00:00Z");
    expect(timeAgo("2026-01-01T11:59:50Z", now)).toBe("just now");
    expect(timeAgo("2026-01-01T11:00:00Z", now)).toBe("1h ago");
    expect(timeAgo("2025-12-30T12:00:00Z", now)).toBe("2d ago");
  });
});

describe("barsSpan", () => {
  it("describes how much time a number of candles covers", async () => {
    const { barsSpan } = await import("./format");
    expect(barsSpan(20_000, "1h")).toBe("≈ 2.3 years");
    expect(barsSpan(2000, "1h")).toBe("≈ 3 months");
    expect(barsSpan(300, "1h")).toBe("≈ 13 days");
    expect(barsSpan(30, "1m")).toBe("≈ 1 hour");
    expect(barsSpan(5, "1h")).toBe("≈ 5 hours");
  });
});
