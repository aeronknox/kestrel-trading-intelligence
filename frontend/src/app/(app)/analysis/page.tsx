import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/common/states";
import { AnalysisView } from "@/features/ai-analysis/analysis-view";

export const metadata: Metadata = { title: "AI Analysis" };

export default function AnalysisPage() {
  return (
    <Suspense fallback={<LoadingRows rows={6} />}>
      <AnalysisView />
    </Suspense>
  );
}
