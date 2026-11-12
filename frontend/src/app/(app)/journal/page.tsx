import type { Metadata } from "next";

import { JournalView } from "@/features/journal/journal-view";

export const metadata: Metadata = { title: "Journal" };

export default function JournalPage() {
  return <JournalView />;
}
