import type { Metadata } from "next";
import { Suspense } from "react";

import { VerifyEmailView } from "@/features/auth/account-email";

export const metadata: Metadata = { title: "Verify email", referrer: "no-referrer" };

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailView />
    </Suspense>
  );
}
