import { describe, expect, it } from "vitest";

import { benchmarkTimeframe, buyAndHold } from "./benchmark";

const H = 3600;

describe("buyAndHold", () => {
  const candles = [
    { time: 0, close: 100 },
    { time: H, close: 110 },
    { time: 2 * H, close: 90 },
  ];

  it("scales the starting equity by the asset's move, using the bar open at each point", () => {
    const curve = [
      { time: 10, equity: 1000 },
      { time: H + 5, equity: 1020 },
      { time: 2 * H + 1800, equity: 990 },
    ];
    expect(buyAndHold(curve, candles)?.map((p) => p.benchmark)).toEqual([1000, 1100, 900]);
  });

  it("does not invent a price before the first candle", () => {
    expect(buyAndHold([{ time: -10, equity: 1000 }, { time: H, equity: 1000 }], candles)).toBeNull();
    expect(buyAndHold([{ time: 10, equity: 1000 }], candles)).toBeNull(); // nothing to compare yet
    expect(buyAndHold([{ time: 10, equity: 1000 }, { time: 20, equity: 1000 }], [])).toBeNull();
  });

  it("keeps the curve's own fields and sorts by time", () => {
    const out = buyAndHold([{ time: H, equity: 2, tag: "b" }, { time: 0, equity: 1, tag: "a" }], candles);
    expect(out?.map((p) => [p.tag, p.benchmark])).toEqual([["a", 1], ["b", 1.1]]);
  });
});

describe("benchmarkTimeframe", () => {
  it("picks the finest timeframe that fits", () => {
    expect(benchmarkTimeframe(2 * H)).toBe("5m");
    expect(benchmarkTimeframe(10 * 24 * H)).toBe("15m");
    expect(benchmarkTimeframe(60 * 24 * H)).toBe("1h");
    expect(benchmarkTimeframe(20 * 365 * 24 * H)).toBe("1d");
  });
});
