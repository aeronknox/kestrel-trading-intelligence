import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BacktestDetailView } from "@/features/backtesting/backtest-views";

export const metadata: Metadata = { title: "Backtest result" };

export default async function BacktestPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const num = Number(id);
  if (!Number.isInteger(num) || num <= 0) notFound();
  return <BacktestDetailView id={num} />;
}
