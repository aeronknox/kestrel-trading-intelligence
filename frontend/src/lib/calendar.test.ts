import { describe, expect, it } from "vitest";

import { addMonths, monthGrid } from "./calendar";

describe("monthGrid", () => {
  it("starts weeks on Monday and pads both ends", () => {
    const nov = monthGrid(2026, 10); // November 2026 starts on a Sunday
    expect(nov[0]).toEqual([null, null, null, null, null, null, "2026-11-01"]);
    expect(nov.at(-1)).toEqual(["2026-11-30", null, null, null, null, null, null]);
    expect(nov.flat().filter(Boolean)).toHaveLength(30);
    expect(nov.every((w) => w.length === 7)).toBe(true);
  });

  it("handles leap years and a month that fills its rows exactly", () => {
    expect(monthGrid(2028, 1).flat().filter(Boolean)).toHaveLength(29);
    const feb2027 = monthGrid(2027, 1); // starts on a Monday, 28 days: exactly four weeks
    expect(feb2027).toHaveLength(4);
    expect(feb2027[0][0]).toBe("2027-02-01");
  });
});

describe("addMonths", () => {
  it("wraps across years both ways", () => {
    expect(addMonths({ year: 2026, month: 11 }, 1)).toEqual({ year: 2027, month: 0 });
    expect(addMonths({ year: 2026, month: 0 }, -1)).toEqual({ year: 2025, month: 11 });
    expect(addMonths({ year: 2026, month: 5 }, -18)).toEqual({ year: 2024, month: 11 });
  });
});
