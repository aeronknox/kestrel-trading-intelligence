/** A month as calendar rows, weeks starting on Monday: each cell an ISO date (YYYY-MM-DD), or null for padding. */
export function monthGrid(year: number, month: number): (string | null)[][] {
  const days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const lead = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7; // Monday = 0
  const cells: (string | null)[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= days; d++) cells.push(isoDate(year, month, d));
  while (cells.length % 7) cells.push(null);
  return Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7));
}

export function isoDate(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** `{year, month}` moved by `delta` months (month is 0-based, as in Date). */
export function addMonths(ym: { year: number; month: number }, delta: number): { year: number; month: number } {
  const total = ym.year * 12 + ym.month + delta;
  return { year: Math.floor(total / 12), month: ((total % 12) + 12) % 12 };
}

/** The browser's IANA timezone, e.g. "Europe/London" (UTC if it can't tell). */
export function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
