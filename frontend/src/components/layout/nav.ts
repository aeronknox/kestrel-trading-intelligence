import {
  Bell,
  Bot,
  BrainCircuit,
  CandlestickChart,
  FlaskConical,
  SlidersHorizontal,
  LayoutDashboard,
  type LucideIcon,
  NotebookPen,
  PieChart,
  Settings,
  ShieldCheck,
  Workflow,
  Wallet,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  adminOnly?: boolean;
}

export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { href: "/markets", label: "Markets", icon: CandlestickChart },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/analysis", label: "AI Analysis", icon: BrainCircuit },
      { href: "/assistant", label: "Assistant", icon: Bot },
    ],
  },
  {
    label: "Research",
    items: [
      { href: "/strategies", label: "Strategies", icon: Workflow },
      { href: "/backtests", label: "Backtests", icon: FlaskConical },
      { href: "/research", label: "Optimization", icon: SlidersHorizontal },
      { href: "/alerts", label: "Alerts", icon: Bell },
    ],
  },
  {
    label: "Simulation",
    items: [
      { href: "/paper-trading", label: "Paper Trading", icon: Wallet },
      { href: "/portfolio", label: "Portfolio", icon: PieChart },
      { href: "/journal", label: "Journal", icon: NotebookPen },
    ],
  },
  {
    label: "Account",
    items: [
      { href: "/settings", label: "Settings", icon: Settings },
      { href: "/admin", label: "Admin", icon: ShieldCheck, adminOnly: true },
    ],
  },
];
