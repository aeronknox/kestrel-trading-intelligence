import type { Metadata } from "next";

import { BacktestListView } from "@/features/backtesting/backtest-views";

export const metadata: Metadata = { title: "Backtests" };

export default function BacktestsPage() {
  return <BacktestListView />;
}
