import type { AssetWithTicker, Ticker } from "@/types/api";

export type SortKey = "name" | "price" | "change" | "volume";
export type Sort = { key: SortKey; dir: "asc" | "desc" } | null;

/** The value a row sorts by; null (no price) always sorts last. Volume compares in USD, not coins. */
function value(key: SortKey, row: AssetWithTicker, t: Ticker | null | undefined): number | string | null {
  if (key === "name") return row.asset.base_currency;
  if (!t) return null;
  if (key === "price") return t.price;
  if (key === "change") return t.change_pct_24h ?? null;
  return t.volume_24h != null ? t.volume_24h * t.price : null;
}

/** Rows in `sort` order using the freshest ticker per symbol; `null` keeps the given order. */
export function sortRows(rows: AssetWithTicker[], sort: Sort, live: Record<string, Ticker | undefined> = {}): AssetWithTicker[] {
  if (!sort) return rows;
  const sign = sort.dir === "asc" ? 1 : -1;
  return rows
    .map((row, i) => ({ row, i, v: value(sort.key, row, live[row.asset.symbol] ?? row.ticker) }))
    .sort((a, b) => {
      if (a.v === null || b.v === null) return a.v === b.v ? a.i - b.i : a.v === null ? 1 : -1;
      const c = typeof a.v === "string" ? a.v.localeCompare(b.v as string) : (a.v as number) - (b.v as number);
      return c ? sign * c : a.i - b.i;
    })
    .map((x) => x.row);
}

/** Clicking a header: first descending (names ascending), then the other way, then back to the default order. */
export function nextSort(current: Sort, key: SortKey): Sort {
  const first = key === "name" ? "asc" : "desc";
  if (!current || current.key !== key) return { key, dir: first };
  return current.dir === first ? { key, dir: first === "asc" ? "desc" : "asc" } : null;
}
