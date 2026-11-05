import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/common/states";
import { BacktestCompareView } from "@/features/backtesting/backtest-views";

export const metadata: Metadata = { title: "Compare backtests" };

export default function ComparePage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <BacktestCompareView />
    </Suspense>
  );
}
