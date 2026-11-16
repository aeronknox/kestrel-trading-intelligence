import { describe, expect, it } from "vitest";

import { tradeMarkers } from "./trade-markers";

const at = (s: number) => new Date(s * 1000).toISOString();
const bars = [3600, 7200, 10800];

describe("tradeMarkers", () => {
  it("puts each fill on the bar it happened in, buys below and sells above", () => {
    const m = tradeMarkers(
      [
        { side: "buy", quantity: 1, price: 100, executed_at: at(3700) },
        { side: "sell", quantity: 1, price: 110.5, executed_at: at(7200) },
      ],
      bars,
    );
    expect(m).toEqual([
      { time: 3600, position: "belowBar", shape: "arrowUp", color: "gain", text: "B @ 100" },
      { time: 7200, position: "aboveBar", shape: "arrowDown", color: "loss", text: "S @ 110.5" },
    ]);
  });

  it("combines fills in one bar at their average price, and skips fills before the chart", () => {
    const m = tradeMarkers(
      [
        { side: "buy", quantity: 1, price: 100, executed_at: at(11000) },
        { side: "buy", quantity: 3, price: 104, executed_at: at(12000) }, // after the last bar: on the forming one
        { side: "sell", quantity: 1, price: 90, executed_at: at(100) },
      ],
      bars,
    );
    expect(m).toEqual([{ time: 10800, position: "belowBar", shape: "arrowUp", color: "gain", text: "B @ 103" }]);
  });

  it("handles no candles and small prices", () => {
    expect(tradeMarkers([{ side: "buy", quantity: 1, price: 1, executed_at: at(5000) }], [])).toEqual([]);
    expect(tradeMarkers([{ side: "sell", quantity: 10, price: 0.123456, executed_at: at(5000) }], bars)[0].text).toBe("S @ 0.1235");
  });
});
