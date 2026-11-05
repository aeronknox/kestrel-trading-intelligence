"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Toaster } from "sonner";

import { TooltipProvider } from "@/components/ui/overlays";
import { ME_KEY } from "@/hooks/use-auth";
import { ThemeProvider, useTheme } from "@/hooks/use-theme";
import { ApiError } from "@/services/api";

function ThemedToaster() {
  const { theme } = useTheme();
  return <Toaster theme={theme} position="bottom-right" richColors closeButton />;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => {
    // A 401 anywhere means the session expired or was revoked: drop the cached user so the
    // authenticated layout redirects to /login instead of rendering error cards.
    const onError = (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) qc.setQueryData(ME_KEY, null);
    };
    const qc: QueryClient = new QueryClient({
        queryCache: new QueryCache({ onError }),
        mutationCache: new MutationCache({ onError }),
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
          },
        },
      });
    return qc;
  });
  return (
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <TooltipProvider>
          {children}
          <ThemedToaster />
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
