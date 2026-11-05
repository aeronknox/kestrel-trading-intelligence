import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { EditStrategyView } from "@/features/strategies/strategy-pages";

export const metadata: Metadata = { title: "Edit strategy" };

export default async function StrategyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const num = Number(id);
  if (!Number.isInteger(num) || num <= 0) notFound();
  return <EditStrategyView id={num} />;
}
