import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/common/states";
import { NewStrategyView } from "@/features/strategies/strategy-pages";

export const metadata: Metadata = { title: "New strategy" };

export default function NewStrategyPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <NewStrategyView />
    </Suspense>
  );
}
