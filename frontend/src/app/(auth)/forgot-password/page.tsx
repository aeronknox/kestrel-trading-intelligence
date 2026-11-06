import type { Metadata } from "next";

import { ForgotPasswordForm } from "@/features/auth/account-email";

export const metadata: Metadata = { title: "Forgot password" };

export default function ForgotPasswordPage() {
  return <ForgotPasswordForm />;
}
