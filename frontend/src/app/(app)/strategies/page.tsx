import type { Metadata } from "next";

import { StrategiesView } from "@/features/strategies/strategies-view";

export const metadata: Metadata = { title: "Strategies" };

export default function StrategiesPage() {
  return <StrategiesView />;
}
