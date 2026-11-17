import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/common/states";
import { MarketsView } from "@/features/markets/markets-view";

export const metadata: Metadata = { title: "Markets" };

export default function MarketsPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <MarketsView />
    </Suspense>
  );
}
