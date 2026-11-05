"use client";

import { ErrorState } from "@/components/common/states";
import { Card } from "@/components/ui/card";

export default function AppError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <Card>
      <ErrorState error={error} onRetry={reset} />
    </Card>
  );
}
