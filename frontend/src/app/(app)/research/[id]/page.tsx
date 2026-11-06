import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ResearchDetailView } from "@/features/research/research-views";

export const metadata: Metadata = { title: "Analysis result" };

export default async function ResearchRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const num = Number(id);
  if (!Number.isInteger(num) || num <= 0) notFound();
  return <ResearchDetailView id={num} />;
}
