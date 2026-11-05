import type { Metadata } from "next";

import { AssistantView } from "@/features/assistant/assistant-view";

export const metadata: Metadata = { title: "Assistant" };

export default function AssistantPage() {
  return <AssistantView />;
}
