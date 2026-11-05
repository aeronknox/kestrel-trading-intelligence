import { BrainCircuit, FlaskConical, ShieldCheck, Wallet } from "lucide-react";

import { Logo } from "@/components/layout/logo";

const FEATURES = [
  { icon: BrainCircuit, title: "Explainable AI signals", body: "Every signal shows the indicators, patterns and model evidence behind it." },
  { icon: FlaskConical, title: "Honest backtesting", body: "Next-bar execution, fees and slippage — no look-ahead bias." },
  { icon: Wallet, title: "Risk-free paper trading", body: "A virtual $100k portfolio with real-time public market prices." },
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-border bg-sidebar lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="bg-grid pointer-events-none absolute inset-0 opacity-40 [mask-image:radial-gradient(ellipse_at_30%_40%,black,transparent_75%)]" />
        <div
          className="pointer-events-none absolute -top-40 -left-40 size-[520px] rounded-full opacity-25 blur-3xl"
          style={{ background: "radial-gradient(circle, var(--chart-1), transparent 65%)" }}
        />
        <Logo className="relative" />
        <div className="relative max-w-md">
          <h2 className="text-3xl leading-tight font-semibold tracking-tight">
            Market intelligence you can <span className="text-primary">audit</span>.
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
            Research crypto markets with transparent technical analysis, test strategies against real history and practice
            execution in a fully simulated environment.
          </p>
          <ul className="mt-8 space-y-5">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-border bg-card">
                  <f.icon className="size-4 text-primary" />
                </span>
                <div>
                  <p className="text-sm font-medium">{f.title}</p>
                  <p className="text-xs text-muted-foreground">{f.body}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <ShieldCheck className="size-3.5" /> Simulation &amp; research platform. Not investment advice. No real-money trading.
        </p>
      </section>
      <section className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          {children}
        </div>
      </section>
    </div>
  );
}
