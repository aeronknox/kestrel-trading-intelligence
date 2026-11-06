import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/common/states";
import { NewResearchView } from "@/features/research/research-views";

export const metadata: Metadata = { title: "New analysis" };

export default function NewResearchPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <NewResearchView />
    </Suspense>
  );
}
