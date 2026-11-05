import { describe, expect, it } from "vitest";

import type { IndicatorSpec, RuleSet } from "@/types/api";

import { defaultOperand, describeCondition, describeRuleSet, validateStrategy } from "./rules";

const catalog: IndicatorSpec[] = [
  { name: "rsi", params: { period: { default: 14, min: 2, max: 100 } }, fields: [] },
  { name: "macd", params: { fast: { default: 12, min: 2, max: 100 }, slow: { default: 26, min: 3, max: 200 }, signal: { default: 9, min: 2, max: 100 } }, fields: ["macd", "signal", "hist"] },
];

describe("strategy rules", () => {
  it("builds operands with catalog defaults", () => {
    expect(defaultOperand("rsi", catalog)).toEqual({ indicator: "rsi", params: { period: 14 }, field: null });
    expect(defaultOperand("macd", catalog).field).toBe("macd");
  });

  it("describes conditions in plain English", () => {
    const text = describeCondition({ left: { indicator: "rsi", params: { period: 14 } }, op: "crosses_above", right: { value: 30 } });
    expect(text).toBe("RSI(14) crosses above 30");
    const rs: RuleSet = {
      logic: "any",
      conditions: [
        { left: { indicator: "close" }, op: ">", right: { indicator: "sma", params: { period: 200 } } },
        { left: { indicator: "rsi", params: { period: 14 } }, op: "<", right: { value: 30 } },
      ],
    };
    expect(describeRuleSet(rs)).toBe("Close price is above SMA(200) OR RSI(14) is below 30");
  });

  it("validates like the backend", () => {
    const empty: RuleSet = { logic: "all", conditions: [] };
    const one: RuleSet = { logic: "all", conditions: [{ left: { indicator: "close" }, op: ">", right: { value: 1 } }] };
    expect(validateStrategy(empty, empty, {})).toMatch(/entry/);
    expect(validateStrategy(one, empty, {})).toMatch(/exit/);
    expect(validateStrategy(one, empty, { stop_loss_pct: 5 })).toBeNull();
    expect(validateStrategy(one, one, { position_size_pct: 150 })).toMatch(/Position size/);
  });
});
