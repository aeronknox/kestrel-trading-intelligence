import { describe, expect, it } from "vitest";

import type { AssetWithTicker } from "@/types/api";

import { nextSort, sortRows } from "./market-sort";

const row = (base: string, price: number | null, change: number, volume: number): AssetWithTicker =>
  ({
    asset: { id: base.length, symbol: `${base}-USD`, base_currency: base },
    ticker: price === null ? null : { price, change_pct_24h: change, volume_24h: volume },
  }) as unknown as AssetWithTicker;

const rows = [row("BTC", 70_000, 1, 10), row("DOGE", 0.1, 5, 1_000_000), row("ETH", 3_000, -2, 100), row("XYZ", null, 0, 0)];
const names = (r: AssetWithTicker[]) => r.map((x) => x.asset.base_currency);

describe("sortRows", () => {
  it("keeps the given order without a sort", () => {
    expect(names(sortRows(rows, null))).toEqual(["BTC", "DOGE", "ETH", "XYZ"]);
  });

  it("compares volume in USD, not coins, and puts rows without a price last", () => {
    // BTC 700k, DOGE 100k, ETH 300k (USD)
    expect(names(sortRows(rows, { key: "volume", dir: "desc" }))).toEqual(["BTC", "ETH", "DOGE", "XYZ"]);
    expect(names(sortRows(rows, { key: "volume", dir: "asc" }))).toEqual(["DOGE", "ETH", "BTC", "XYZ"]);
  });

  it("sorts by change and name, and prefers the live price", () => {
    expect(names(sortRows(rows, { key: "change", dir: "desc" }))).toEqual(["DOGE", "BTC", "ETH", "XYZ"]);
    expect(names(sortRows(rows, { key: "name", dir: "desc" }))).toEqual(["XYZ", "ETH", "DOGE", "BTC"]);
    const live = { "ETH-USD": { price: 3_000, change_pct_24h: 9, volume_24h: 100 } } as never;
    expect(names(sortRows(rows, { key: "change", dir: "desc" }, live))[0]).toBe("ETH");
  });
});

describe("nextSort", () => {
  it("cycles descending, ascending, default (names start ascending)", () => {
    expect(nextSort(null, "change")).toEqual({ key: "change", dir: "desc" });
    expect(nextSort({ key: "change", dir: "desc" }, "change")).toEqual({ key: "change", dir: "asc" });
    expect(nextSort({ key: "change", dir: "asc" }, "change")).toBeNull();
    expect(nextSort({ key: "change", dir: "asc" }, "name")).toEqual({ key: "name", dir: "asc" });
  });
});
