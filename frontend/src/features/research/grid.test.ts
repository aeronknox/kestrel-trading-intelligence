import { describe, expect, it } from "vitest";

import { defaultRange, gridProblem, MAX_VALUES, rangeValues } from "./grid";

describe("rangeValues", () => {
  it("is inclusive and free of float drift", () => {
    expect(rangeValues(1, 2, 0.1)).toEqual([1, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2]);
    expect(rangeValues(20, 40, 5)).toEqual([20, 25, 30, 35, 40]);
  });
  it("rounds integer parameters and drops duplicates", () => {
    expect(rangeValues(10, 12, 0.5, true)).toEqual([10, 11, 12]);
  });
  it("rejects empty or invalid ranges and stops past the value cap", () => {
    expect(rangeValues(5, 1, 1)).toEqual([]);
    expect(rangeValues(1, 5, 0)).toEqual([]);
    expect(rangeValues(0, 1000, 1).length).toBe(MAX_VALUES + 1); // reported as a problem, not silently truncated
  });
});

describe("defaultRange / gridProblem", () => {
  it("centres on the current value within bounds", () => {
    const r = defaultRange({ path: "p", label: "RSI period", current: 14, min: 2, max: 100, integer: true });
    expect(r).toEqual({ from: 8, to: 20, step: 3 });
    const low = defaultRange({ path: "p", label: "stop", current: 1, min: 0.1, max: 90, integer: false });
    expect(low.from).toBeGreaterThanOrEqual(0.1);
  });
  it("explains what is wrong", () => {
    expect(gridProblem([{ label: "A", values: [1], min: null, max: null }])).toMatch(/at least 2/);
    expect(gridProblem([{ label: "A", values: [0, 1], min: 0.1, max: 9 }])).toMatch(/between/);
    const ten = Array.from({ length: 11 }, (_, i) => i + 1);
    expect(gridProblem([{ label: "A", values: ten, min: null, max: null }, { label: "B", values: ten, min: null, max: null }])).toMatch(/121 combinations/);
    expect(gridProblem([{ label: "A", values: [1, 2], min: null, max: null }])).toBeNull();
  });
});

describe("labels and objectives", () => {
  it("shortens parameter labels", async () => {
    const { shortLabel } = await import("./grid");
    expect(shortLabel("Entry #1 (RSI(14) crosses above 30): threshold")).toBe("Entry #1: threshold");
    expect(shortLabel("Risk: stop loss pct")).toBe("Risk: stop loss pct");
  });
  it("mirrors the backend objective", async () => {
    const { objectiveValue } = await import("./grid");
    const m = { total_return_pct: 12, sharpe_ratio: 1.5, max_drawdown_pct: -4, num_trades: 1, win_rate: null, profit_factor: null };
    expect(objectiveValue("sharpe_ratio", m)).toBe(1.5);
    expect(objectiveValue("return_over_drawdown", m)).toBe(3);
    expect(objectiveValue("return_over_drawdown", { ...m, max_drawdown_pct: -0.2 })).toBe(12); // drawdown floored at 1%
  });
});
