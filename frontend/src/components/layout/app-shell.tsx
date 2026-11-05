"use client";

import { useQuery } from "@tanstack/react-query";
import { FlaskRound, LogOut, Menu, Moon, Search, Sun, User as UserIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { AssetIcon } from "@/components/common/finance";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
} from "@/components/ui/overlays";
import { Badge, Input } from "@/components/ui/primitives";
import { useLogout } from "@/hooks/use-auth";
import { useMarketStream } from "@/hooks/use-market-stream";
import { useTheme } from "@/hooks/use-theme";
import { formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";
import { api } from "@/services/api";
import type { User } from "@/types/api";

import { Logo } from "./logo";
import { NAV_GROUPS } from "./nav";

function SidebarNav({ user, onNavigate }: { user: User; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-1 flex-col gap-5 overflow-y-auto px-3 py-4 scrollbar-thin">
      {NAV_GROUPS.map((group) => {
        const items = group.items.filter((i) => !i.adminOnly || user.role === "admin");
        if (!items.length) return null;
        return (
          <div key={group.label}>
            <p className="mb-1.5 px-2 text-[10px] font-semibold tracking-wider text-muted-foreground/70 uppercase">{group.label}</p>
            <ul className="space-y-0.5">
              {items.map((item) => {
                const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={onNavigate}
                      className={cn(
                        "group flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm transition-colors",
                        active ? "bg-primary/12 text-foreground" : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )}
                    >
                      <item.icon className={cn("size-4", active ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
                      {item.label}
                      {active && <span className="ml-auto h-4 w-0.5 rounded-full bg-primary" />}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function SimulationNotice() {
  return (
    <div className="mx-3 mb-3 rounded-lg border border-border bg-muted/40 p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium">
        <FlaskRound className="size-3.5 text-primary" /> Simulation mode
      </div>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
        Research &amp; paper trading only. No real money or brokerage connections.
      </p>
    </div>
  );
}

function LiveStatus() {
  const { status } = useMarketStream();
  const label = status === "live" ? "Live" : status === "connecting" ? "Connecting" : "Offline";
  return (
    <Tooltip content={status === "live" ? "Streaming prices via WebSocket" : "Live price stream unavailable — retrying"}>
      <span className="hidden items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground sm:inline-flex">
        <span className={cn("size-1.5 rounded-full", status === "live" ? "bg-gain animate-pulse" : status === "connecting" ? "bg-warn" : "bg-loss")} />
        {label}
      </span>
    </Tooltip>
  );
}

function AssetSearch() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const { tickers } = useMarketStream();
  const assets = useQuery({ queryKey: ["assets"], queryFn: () => api.market.assets(), staleTime: 300_000 });

  const results = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return [];
    return (assets.data ?? []).filter((a) => a.symbol.toLowerCase().includes(term) || a.name.toLowerCase().includes(term)).slice(0, 7);
  }, [q, assets.data]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const go = (symbol: string) => {
    setQ("");
    setOpen(false);
    router.push(`/markets/${symbol}`);
  };

  return (
    <div ref={ref} className="relative w-full max-w-xs">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results[0]) go(results[0].symbol);
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder="Search assets…"
        className="h-8 pl-8 text-xs"
        aria-label="Search assets"
      />
      {open && q && (
        <div className="absolute top-full z-50 mt-1 w-full overflow-hidden rounded-md border border-border bg-popover shadow-xl">
          {results.length === 0 ? (
            <p className="px-3 py-3 text-xs text-muted-foreground">
              No tracked asset matches. Add new ones from <Link className="text-primary" href="/markets" onClick={() => setOpen(false)}>Markets</Link>.
            </p>
          ) : (
            results.map((a) => (
              <button key={a.id} onClick={() => go(a.symbol)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent">
                <AssetIcon symbol={a.symbol} className="size-6" />
                <span className="font-medium">{a.symbol}</span>
                <span className="truncate text-xs text-muted-foreground">{a.name}</span>
                <span className="ml-auto text-xs tabular text-muted-foreground">{formatPrice(tickers[a.symbol]?.price)}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { theme, toggle } = useTheme();
  const logout = useLogout();
  const { meta } = useMarketStream();
  const initials = user.full_name.split(/\s+/).map((p) => p[0]).join("").slice(0, 2).toUpperCase();

  return (
    <div className="flex min-h-dvh">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border bg-sidebar lg:flex">
        <div className="flex h-14 items-center px-4">
          <Link href="/dashboard">
            <Logo />
          </Link>
        </div>
        <SidebarNav user={user} />
        <SimulationNotice />
      </aside>

      {/* Mobile drawer */}
      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <DialogContent className="top-0 left-0 h-dvh max-h-dvh w-72 max-w-72 translate-x-0 translate-y-0 gap-0 rounded-none border-y-0 border-l-0 p-0 data-[state=open]:slide-in-from-left">
          <DialogTitle className="sr-only">Navigation</DialogTitle>
          <div className="flex h-14 items-center px-4">
            <Logo />
          </div>
          <div className="flex h-[calc(100dvh-3.5rem)] flex-col">
            <SidebarNav user={user} onNavigate={() => setMobileOpen(false)} />
            <SimulationNotice />
          </div>
        </DialogContent>
      </Dialog>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background/85 px-4 backdrop-blur-md sm:px-6">
          <Button variant="ghost" size="icon-sm" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation">
            <Menu />
          </Button>
          <div className="lg:hidden">
            <Logo showText={false} />
          </div>
          <AssetSearch />
          <div className="ml-auto flex items-center gap-2">
            <LiveStatus />
            <Badge variant="outline" className="hidden md:inline-flex">
              Paper trading
            </Badge>
            <Button variant="ghost" size="icon-sm" onClick={toggle} aria-label="Toggle theme">
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="flex size-8 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label="Account menu">
                  {initials || <UserIcon className="size-4" />}
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel>
                  <div className="font-medium text-foreground">{user.full_name}</div>
                  <div className="truncate">{user.email}</div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link href="/settings">
                    <UserIcon /> Profile &amp; settings
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => logout.mutate()}>
                  <LogOut /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        {meta?.is_sample && (
          <div className="border-b border-warn/30 bg-warn-soft px-4 py-1.5 text-center text-xs font-medium text-warn sm:px-6">
            SAMPLE DATA MODE — prices are synthetic and for development only. Set MARKET_DATA_PROVIDER=coinbase for real market data.
          </div>
        )}

        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
