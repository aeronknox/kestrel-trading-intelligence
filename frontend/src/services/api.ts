/**
 * Typed API client. Requests go to the same-origin `/api/v1/*` proxy (see
 * `src/app/api/v1/[...path]/route.ts`), so the httpOnly session cookie is sent
 * automatically and never exposed to JavaScript.
 */
import { validationMessage } from "@/lib/validation-message";
import type {
  PriceAlert,
  AlertEventsPage,
  AlertSettings,
  ForwardTest,
  Analysis,
  AuditLog,
  Backtest,
  BacktestSummary,
  CandlesResponse,
  CatalogEntry,
  ChatMessage,
  Conversation,
  ConversationSummary,
  Dashboard,
  HistoryCoverage,
  IndicatorSpec,
  MarketOverview,
  Asset,
  Order,
  OrderSide,
  OrderStatus,
  OrderType,
  Portfolio,
  PortfolioRequestBody,
  PortfolioAnalytics,
  ResearchRequest,
  ResearchRun,
  ResearchSummary,
  RiskLimits,
  Sentiment,
  Signal,
  Snapshot,
  Strategy,
  StrategyAlert,
  TunableParameter,
  Webhook,
  NotificationsPage,
  JournalEntry,
  JournalPage,
  StrategyInput,
  StrategyTemplate,
  Ticker,
  Timeframe,
  Trade,
  User,
  UserSettings,
  Watchlist,
} from "@/types/api";

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function qs(query?: Query): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== "") params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : "";
}

async function request<T>(method: string, path: string, body?: unknown, query?: Query): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${qs(query)}`, {
      method,
      credentials: "same-origin",
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "network_error", "Unable to reach the server. Check your connection.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error;
    let message = err?.message ?? `Request failed (${res.status})`;
    // Surface the first field error for validation failures.
    if (err?.code === "validation_failed" && Array.isArray(err.details) && err.details[0]?.msg) {
      const d = err.details[0] as { loc?: (string | number)[]; msg: string };
      message = validationMessage(d.loc, d.msg);
    }
    throw new ApiError(res.status, err?.code ?? "http_error", message, err?.details);
  }
  return data as T;
}

const get = <T>(path: string, query?: Query) => request<T>("GET", path, undefined, query);
const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
const del = <T>(path: string) => request<T>("DELETE", path);

export const api = {
  auth: {
    me: () => get<User>("/auth/me"),
    login: (email: string, password: string) => post<User>("/auth/login", { email, password }),
    register: (email: string, password: string, full_name: string) =>
      post<User>("/auth/register", { email, password, full_name }),
    logout: () => post<{ message: string }>("/auth/logout"),
    changePassword: (current_password: string, new_password: string) =>
      post<{ message: string }>("/auth/change-password", { current_password, new_password }),
    forgotPassword: (email: string) => post<{ message: string }>("/auth/forgot-password", { email }),
    resetPassword: (token: string, new_password: string) =>
      post<{ message: string }>("/auth/reset-password", { token, new_password }),
    verifyEmail: (token: string) => post<{ message: string }>("/auth/verify-email", { token }),
    resendVerification: () => post<{ message: string }>("/auth/verify-email/resend"),
    /** email_delivery "console": reset and verification links go to the server log, not an inbox. */
    config: () => get<{ demo_enabled: boolean; email_delivery?: "console" | "smtp" }>("/auth/config"),
    demo: () => post<User>("/auth/demo"),
    /** Permanently deletes the signed-in account and all of its data (password not needed for a demo). */
    deleteAccount: (password: string | null, confirm: string) => post<{ message: string }>("/auth/delete-account", { password, confirm }),
  },
  users: {
    updateProfile: (full_name: string) => patch<User>("/users/me", { full_name }),
    settings: () => get<UserSettings>("/users/me/settings"),
    updateSettings: (body: Partial<UserSettings>) => patch<UserSettings>("/users/me/settings", body),
    webhook: () => get<Webhook>("/users/me/webhook"),
    setWebhook: (url: string) => put<Webhook>("/users/me/webhook", { url }),
    removeWebhook: () => del<Webhook>("/users/me/webhook"),
    testWebhook: () => post<{ ok: boolean; webhook: Webhook }>("/users/me/webhook/test"),
    rotateWebhookSecret: () => post<Webhook>("/users/me/webhook/secret"),
    setWebhookOptions: (body: { orders: boolean }) => patch<Webhook>("/users/me/webhook", body),
  },
  admin: {
    users: () => get<User[]>("/admin/users"),
    updateUser: (id: number, body: { role?: string; is_active?: boolean }) => patch<User>(`/admin/users/${id}`, body),
    auditLogs: (query?: { action?: string; user_id?: number }) => get<AuditLog[]>("/admin/audit-logs", query),
  },
  market: {
    overview: () => get<MarketOverview>("/market/overview"),
    assets: (q?: string) => get<Asset[]>("/market/assets", { q }),
    catalog: (q: string) => get<CatalogEntry[]>("/market/catalog", { q }),
    track: (symbol: string) => post<Asset>("/market/assets", { symbol }),
    ticker: (symbol: string) => get<Ticker>(`/market/assets/${encodeURIComponent(symbol)}/ticker`),
    candles: (symbol: string, timeframe: Timeframe, limit = 300) =>
      get<CandlesResponse>(`/market/assets/${encodeURIComponent(symbol)}/candles`, { timeframe, limit }),
    sentiment: () => get<Sentiment>("/market/sentiment"),
    history: (symbol: string, timeframe: Timeframe) =>
      get<HistoryCoverage>(`/market/assets/${encodeURIComponent(symbol)}/history`, { timeframe }),
  },
  watchlist: {
    get: () => get<Watchlist>("/watchlists/default"),
    add: (symbol: string) => post<Watchlist>("/watchlists/default/items", { symbol }),
    remove: (symbol: string) => del<Watchlist>(`/watchlists/default/items/${encodeURIComponent(symbol)}`),
  },
  analysis: {
    run: (symbol: string, timeframe: Timeframe) => post<Analysis>("/analysis", { symbol, timeframe }),
    list: (symbol?: string, limit = 20) => get<Analysis[]>("/analysis", { symbol, limit }),
    get: (id: number) => get<Analysis>(`/analysis/${id}`),
    signals: (symbol?: string, limit = 50) => get<Signal[]>("/signals", { symbol, limit }),
  },
  strategies: {
    list: (includeArchived = false) => get<Strategy[]>("/strategies", { include_archived: includeArchived }),
    get: (id: number) => get<Strategy>(`/strategies/${id}`),
    create: (body: StrategyInput) => post<Strategy>("/strategies", body),
    update: (id: number, body: Partial<StrategyInput> & { is_archived?: boolean }) =>
      patch<Strategy>(`/strategies/${id}`, body),
    remove: (id: number) => del<void>(`/strategies/${id}`),
    templates: () => get<{ templates: StrategyTemplate[] }>("/strategies/templates"),
    indicators: () => get<{ indicators: IndicatorSpec[]; operators: string[] }>("/strategies/indicators"),
  },
  backtests: {
    run: (body: { strategy_id: number; bars: number; initial_capital: number; fee_bps: number; slippage_bps: number }) =>
      post<Backtest>("/backtests", body),
    list: (strategyId?: number) => get<BacktestSummary[]>("/backtests", { strategy_id: strategyId }),
    get: (id: number) => get<Backtest>(`/backtests/${id}`),
    compare: (ids: number[]) => get<Backtest[]>("/backtests/compare", { ids: ids.join(",") }),
    remove: (id: number) => del<void>(`/backtests/${id}`),
  },
  alerts: {
    list: () => get<StrategyAlert[]>("/alerts"),
    get: (strategyId: number) => get<StrategyAlert | null>(`/alerts/strategy/${strategyId}`),
    upsert: (strategyId: number, body: AlertSettings) => put<StrategyAlert>(`/alerts/strategy/${strategyId}`, body),
    remove: (strategyId: number) => del<void>(`/alerts/strategy/${strategyId}`),
    events: (limit = 50) => get<AlertEventsPage>("/alerts/events", { limit }),
    markRead: (ids?: number[]) => post<AlertEventsPage>("/alerts/events/read", ids ? { ids } : {}),
    forwardTest: (strategyId: number) => get<ForwardTest>(`/alerts/strategy/${strategyId}/forward-test`),
  },
  research: {
    parameters: (strategyId: number) => get<TunableParameter[]>("/research/parameters", { strategy_id: strategyId }),
    sweep: (body: ResearchRequest) => post<ResearchRun>("/research/sweeps", body),
    walkForward: (body: ResearchRequest) => post<ResearchRun>("/research/walk-forward", body),
    portfolio: (body: PortfolioRequestBody) => post<ResearchRun>("/research/portfolio", body),
    list: (strategyId?: number) => get<ResearchSummary[]>("/research", { strategy_id: strategyId }),
    get: (id: number) => get<ResearchRun>(`/research/${id}`),
    remove: (id: number) => del<void>(`/research/${id}`),
  },
  paper: {
    portfolio: () => get<Portfolio>("/paper/portfolio"),
    placeOrder: (body: { symbol: string; side: OrderSide; order_type: OrderType; quantity: number; limit_price?: number | null; stop_price?: number | null; trail_pct?: number | null; stop_loss?: number | null; take_profit?: number | null; expires_in_hours?: number | null }) =>
      post<Order>("/paper/orders", body),
    protect: (
      symbol: string,
      body: { stop_loss: number | null; trailing_stop_pct?: number | null; take_profit: number | null; partial_take_profit?: number | null; partial_pct?: number; breakeven_after_partial?: boolean },
    ) =>
      post<Order[]>(`/paper/positions/${encodeURIComponent(symbol)}/protect`, body),
    orders: (status?: OrderStatus) => get<Order[]>("/paper/orders", { status }),
    cancelOrder: (id: number) => post<Order>(`/paper/orders/${id}/cancel`),
    trades: () => get<Trade[]>("/paper/trades"),
    history: () => get<Snapshot[]>("/paper/history"),
    analytics: () => get<PortfolioAnalytics>("/paper/analytics"),
    updateRiskLimits: (body: RiskLimits) => put<Portfolio>("/paper/portfolio/risk-limits", body),
    reset: () => post<Portfolio>("/paper/portfolio/reset"),
  },
  journal: {
    get: () => get<JournalPage>("/paper/journal"),
    save: (tradeId: number, body: { setup: string | null; emotion: string | null; rating: number | null; notes: string; lesson: string; planned_stop: number | null }) =>
      put<JournalEntry>(`/paper/journal/${tradeId}`, body),
    remove: (tradeId: number) => del<void>(`/paper/journal/${tradeId}`),
  },
  priceAlerts: {
    list: (symbol?: string) => get<PriceAlert[]>("/price-alerts", symbol ? { symbol } : undefined),
    create: (body: { symbol: string; target: number; note: string; notify_webhook: boolean }) => post<PriceAlert>("/price-alerts", body),
    remove: (id: number) => del<void>(`/price-alerts/${id}`),
  },
  notifications: {
    list: (limit = 50) => get<NotificationsPage>("/notifications", { limit }),
    markRead: (ids?: number[]) => post<NotificationsPage>("/notifications/read", ids ? { ids } : {}),
  },
  dashboard: () => get<Dashboard>("/dashboard"),
  assistant: {
    chat: (message: string, conversation_id?: number | null) =>
      post<{ conversation_id: number; message: ChatMessage }>("/assistant/chat", { message, conversation_id }),
    conversations: () => get<ConversationSummary[]>("/assistant/conversations"),
    conversation: (id: number) => get<Conversation>(`/assistant/conversations/${id}`),
    remove: (id: number) => del<void>(`/assistant/conversations/${id}`),
  },
};
