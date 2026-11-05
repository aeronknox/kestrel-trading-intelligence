import type { Metadata } from "next";

import { AdminView } from "@/features/admin/admin-view";

export const metadata: Metadata = { title: "Admin" };

export default function AdminPage() {
  return <AdminView />;
}
