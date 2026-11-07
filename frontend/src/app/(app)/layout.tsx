"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { Logo } from "@/components/layout/logo";
import { ErrorState } from "@/components/common/states";
import { DemoBanner, VerifyEmailBanner } from "@/features/auth/account-email";
import { useMe } from "@/hooks/use-auth";
import { MarketStreamProvider } from "@/hooks/use-market-stream";

export default function AuthedLayout({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const router = useRouter();

  useEffect(() => {
    if (me.data === null) router.replace("/login");
  }, [me.data, router]);

  if (me.error) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <ErrorState error={me.error} onRetry={() => me.refetch()} />
      </div>
    );
  }
  if (!me.data) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <div className="animate-pulse">
          <Logo />
        </div>
      </div>
    );
  }
  return (
    <MarketStreamProvider>
      <AppShell user={me.data}>
        {me.data.is_demo ? <DemoBanner /> : !me.data.email_verified && <VerifyEmailBanner email={me.data.email} />}
        {children}
      </AppShell>
    </MarketStreamProvider>
  );
}
