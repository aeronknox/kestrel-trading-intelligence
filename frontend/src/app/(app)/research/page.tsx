import type { Metadata } from "next";

import { ResearchListView } from "@/features/research/research-views";

export const metadata: Metadata = { title: "Optimization" };

export default function ResearchPage() {
  return <ResearchListView />;
}
