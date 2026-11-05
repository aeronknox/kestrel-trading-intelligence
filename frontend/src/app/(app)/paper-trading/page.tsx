import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/common/states";
import { PaperTradingView } from "@/features/paper-trading/paper-trading-view";

export const metadata: Metadata = { title: "Paper Trading" };

export default function PaperTradingPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <PaperTradingView />
    </Suspense>
  );
}
