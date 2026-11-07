/** TypeScript mirrors of the backend's Pydantic response models. */

export type Role = "user" | "admin";
export type Timeframe = "1m" | "5m" | "15m" | "1h" | "6h" | "1d";
export const TIMEFRAMES: Timeframe[] = ["1m", "5m", "15m", "1h", "6h", "1d"];

export interface UserSettings {
  default_timeframe: Timeframe;
  default_symbol: string;
  risk_tolerance: "conservative" | "moderate" | "aggressive";
  preferences: Record<string, unknown>;
}

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  email_verified: boolean;
  /** Throwaway sandbox account from "Try the demo"; deleted after a day. */
  is_demo: boolean;
  created_at: string;
  last_login_at: string | null;
  settings: UserSettings | null;
}

export interface DataMeta {
  source: string;
  is_sample: boolean;
  attribution: string;
  stale?: boolean;
  fetched_at?: string | null;
}

export interface Asset {
  id: number;
  symbol: string;
  name: string;
  asset_class: "crypto" | "stock" | "forex";
  base_currency: string;
  quote_currency: string;
  provider: string;
}

export interface Ticker {
  symbol: string;
  price: number;
  open_24h: number;
  high_24h: number;
  low_24h: number;
  volume_24h: number;
  change_pct_24h: number;
  ts: string;
}

export interface AssetWithTicker {
  asset: Asset;
  ticker: Ticker | null;
}

export interface MarketOverview {
  assets: AssetWithTicker[];
  meta: DataMeta;
}

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Point {
  time: number;
  value: number;
}

export interface CandlesResponse {
  symbol: string;
  timeframe: Timeframe;
  candles: Candle[];
  indicators: Record<string, Point[]>;
  latest: Record<string, number | null>;
  meta: DataMeta;
}

export interface CatalogEntry {
  symbol: string;
  base: string;
  quote: string;
  name: string;
  tracked: boolean;
}

export interface Watchlist {
  id: number;
  name: string;
  items: { id: number; asset: Asset; position: number; added_at: string }[];
}

export interface FearGreed {
  value: number;
  classification: string;
  history: { ts: number; value: number }[];
  source: string;
}

export interface Sentiment {
  fear_greed: FearGreed | null;
  breadth_above_sma50_pct: number | null;
  avg_rsi: number | null;
  advancers: number;
  decliners: number;
  avg_change_pct_24h: number | null;
  label: string;
  meta?: DataMeta;
}

// ---------------------------------------------------------------- analysis
export type SignalAction = "buy" | "sell" | "hold";

export interface SignalComponent {
  name: string;
  score: number;
  weight: number;
  reason: string;
}

export interface Risk {
  level: "high" | "medium" | "low" | "info";
  title: string;
  detail: string;
}

export interface Signal {
  id: number;
  asset: Asset;
  timeframe: Timeframe;
  action: SignalAction;
  score: number;
  confidence: number;
  price_at_signal: number;
  components: SignalComponent[];
  risks: Risk[];
  created_at: string;
}

export interface Pattern {
  name: string;
  bias: "bullish" | "bearish" | "neutral";
  strength: number;
  description: string;
  time: number | null;
}

export interface Trend {
  direction: "uptrend" | "downtrend" | "sideways";
  slope_pct_per_bar: number;
  regression_move_pct: number;
  r_squared: number;
  lookback_bars: number;
  above_sma_50: boolean;
  above_sma_200: boolean;
  strength: number;
}

export interface Level {
  price: number;
  touches: number;
}

export interface MlResult {
  model: string;
  horizon_bars: number;
  label: string;
  available: boolean;
  reason?: string;
  prob_up?: number;
  oos_accuracy?: number;
  baseline_accuracy?: number;
  skill?: number;
  n_train?: number;
  n_test?: number;
  top_features?: { feature: string; contribution: number }[];
}

export interface Analysis {
  id: number;
  asset: Asset;
  timeframe: Timeframe;
  trend: string;
  summary: string;
  narrative: string;
  narrative_source: string;
  indicators: {
    latest: Record<string, number | null>;
    trend: Trend;
    levels: { supports: Level[]; resistances: Level[] };
  };
  patterns: Pattern[];
  ml: MlResult;
  data_source: string;
  data_as_of: string;
  created_at: string;
  signal: Signal | null;
  disclaimer: string;
}

// -------------------------------------------------------------- strategies
export type IndicatorName =
  | "close" | "open" | "high" | "low" | "volume" | "sma" | "ema" | "rsi"
  | "macd" | "bollinger" | "atr" | "volume_sma" | "roc"; // prettier-ignore

export type Operator = ">" | "<" | ">=" | "<=" | "crosses_above" | "crosses_below";

export interface Operand {
  indicator?: IndicatorName | null;
  params?: Record<string, number>;
  field?: string | null;
  value?: number | null;
}

export interface Condition {
  left: Operand;
  op: Operator;
  right: Operand;
}

export interface RuleSet {
  logic: "all" | "any";
  conditions: Condition[];
}

export interface RiskParams {
  position_size_pct: number;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  trailing_stop_pct: number | null;
  max_bars_in_trade: number | null;
}

export interface StrategyConfig {
  id: number;
  version: number;
  asset: Asset;
  timeframe: Timeframe;
  entry_rules: RuleSet;
  exit_rules: RuleSet;
  risk: RiskParams;
  created_at: string;
}

export interface BacktestSummary {
  id: number;
  strategy_id: number;
  status: "pending" | "running" | "completed" | "failed";
  timeframe: Timeframe;
  created_at: string;
  total_return_pct: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  win_rate: number | null;
  num_trades: number | null;
}

export interface Strategy {
  id: number;
  name: string;
  description: string;
  is_archived: boolean;
  current_version: number;
  created_at: string;
  updated_at: string;
  current_config: StrategyConfig | null;
  latest_backtest: BacktestSummary | null;
}

export interface StrategyInput {
  name: string;
  description: string;
  config: {
    symbol: string;
    timeframe: Timeframe;
    entry: RuleSet;
    exit: RuleSet;
    risk: Partial<RiskParams>;
  };
}

export interface StrategyTemplate {
  key: string;
  name: string;
  description: string;
  timeframe: Timeframe;
  definition: { entry: RuleSet; exit: RuleSet; risk: Partial<RiskParams> };
}

export interface IndicatorSpec {
  name: IndicatorName;
  params: Record<string, { default: number; min: number; max: number }>;
  fields: string[];
}

export interface BacktestTrade {
  entry_time: number;
  entry_price: number;
  quantity: number;
  entry_fee: number;
  exit_time: number | null;
  exit_price: number | null;
  exit_fee: number;
  exit_reason: string;
  pnl: number;
  return_pct: number;
  bars_held: number;
}

export interface BacktestMetrics {
  initial_capital: number;
  final_equity: number;
  total_return_pct: number;
  buy_hold_return_pct: number;
  cagr_pct: number | null;
  max_drawdown_pct: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  volatility_annual_pct: number | null;
  num_trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  gross_profit: number;
  gross_loss: number;
  avg_trade_return_pct: number | null;
  best_trade_pct: number | null;
  worst_trade_pct: number | null;
  avg_bars_held: number | null;
  exposure_pct: number;
  total_fees: number;
  bars: number;
  period_years: number;
  warmup_bars: number;
  signal_counts: { entries: number; exits: number };
  bars_requested?: number;
  history_complete?: boolean;
  /** Buy-and-hold of the same capital with the same costs. Absent on backtests run before it existed. */
  benchmark?: {
    name: "buy_and_hold";
    total_return_pct: number;
    max_drawdown_pct: number;
    sharpe_ratio: number | null;
    volatility_annual_pct: number | null;
  };
  excess_return_pct?: number;
  beta?: number | null;
  correlation?: number | null;
}

export interface Backtest {
  id: number;
  strategy_id: number;
  strategy_name: string;
  strategy_version: number;
  asset: Asset;
  timeframe: Timeframe;
  start_at: string | null;
  end_at: string | null;
  initial_capital: number;
  fee_bps: number;
  slippage_bps: number;
  status: BacktestSummary["status"];
  error: string | null;
  data_source: string;
  created_at: string;
  completed_at: string | null;
  metrics: BacktestMetrics | null;
  equity_curve: { time: number; equity: number; drawdown_pct: number; benchmark?: number }[] | null;
  trades: BacktestTrade[] | null;
  disclaimer: string;
}

// ----------------------------------------------------------- paper trading
export type OrderSide = "buy" | "sell";
export type OrderType = "market" | "limit";
export type OrderStatus = "open" | "filled" | "cancelled" | "rejected";

export interface Order {
  id: number;
  asset: Asset;
  side: OrderSide;
  order_type: OrderType;
  quantity: number;
  limit_price: number | null;
  status: OrderStatus;
  filled_price: number | null;
  fee: number;
  reject_reason: string | null;
  created_at: string;
  filled_at: string | null;
}

export interface Trade {
  id: number;
  order_id: number;
  asset: Asset;
  side: OrderSide;
  quantity: number;
  price: number;
  fee: number;
  realized_pnl: number;
  executed_at: string;
}

export interface Position {
  id: number;
  asset: Asset;
  quantity: number;
  avg_entry_price: number;
  current_price: number | null;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number | null;
  realized_pnl: number;
  allocation_pct: number;
  opened_at: string;
}

export interface RiskLimits {
  max_position_pct: number;
  max_open_positions: number;
  daily_loss_limit_pct: number;
}

export interface Portfolio {
  id: number;
  name: string;
  starting_balance: number;
  cash_balance: number;
  /** Worst-case cost of open limit buys, held back from new orders. */
  reserved_cash: number;
  available_cash: number;
  positions_value: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_return_pct: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  total_fees: number;
  risk_limits: RiskLimits;
  positions: Position[];
  prices_complete: boolean;
  fee_bps: number;
  slippage_bps: number;
  simulated: true;
}

export interface Snapshot {
  ts: string;
  equity: number;
  cash: number;
  positions_value: number;
}

export interface PortfolioAnalytics {
  total_trades: number;
  closed_trades: number;
  win_rate: number | null;
  profit_factor: number | null;
  avg_win: number | null;
  avg_loss: number | null;
  best_trade: number | null;
  worst_trade: number | null;
  total_fees: number;
  max_drawdown_pct: number;
}

// --------------------------------------------------------------- dashboard
export interface Dashboard {
  portfolio: Portfolio;
  equity_history: Snapshot[];
  market: AssetWithTicker[];
  watchlist: AssetWithTicker[];
  recent_orders: Order[];
  signals: Signal[];
  insight: {
    id: number;
    symbol: string;
    timeframe: Timeframe;
    summary: string;
    narrative: string;
    narrative_source: string;
    created_at: string;
  } | null;
  sentiment: Sentiment | null;
  meta: DataMeta;
}

// --------------------------------------------------------------- assistant
export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  meta: { engine?: string; tools?: string[]; sources?: string[] };
  created_at: string;
}

export interface ConversationSummary {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Conversation extends ConversationSummary {
  messages: ChatMessage[];
}

export interface AuditLog {
  id: number;
  user_id: number | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  ip_address: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

// ------------------------------------------------------------------ research
export interface TunableParameter {
  path: string;
  label: string;
  current: number | null;
  min: number | null;
  max: number | null;
  integer: boolean;
}

export type ResearchObjective = "sharpe_ratio" | "total_return_pct" | "return_over_drawdown";

export interface RunSummaryMetrics {
  total_return_pct: number;
  sharpe_ratio: number | null;
  max_drawdown_pct: number;
  num_trades: number;
  win_rate: number | null;
  profit_factor: number | null;
}

export interface SweepCell {
  values: number[];
  valid: boolean;
  metrics: RunSummaryMetrics | null;
  score: number | null;
}

export interface SweepResult {
  objective: ResearchObjective;
  min_trades: number;
  params: { path: string; label: string; values: number[] }[];
  cells: SweepCell[];
  best_index: number | null;
  baseline: RunSummaryMetrics;
  buy_hold_return_pct: number;
  robustness: { valid_cells: number; profitable_share_pct: number | null; best_neighbors_mean_score: number | null };
}

export interface WalkForwardFold {
  fold: number;
  in_sample: { start: number; end: number; bars: number };
  out_of_sample: { start: number; end: number; bars: number };
  chosen: Record<string, number> | null;
  is_score: number | null;
  is_metrics: RunSummaryMetrics;
  oos_metrics: RunSummaryMetrics;
  oos_score: number | null;
  baseline_oos_return_pct: number;
}

export interface WalkForwardResult {
  objective: ResearchObjective;
  min_trades: number;
  folds: number;
  is_ratio: number;
  params: { path: string; label: string; values: number[] }[];
  fold_results: WalkForwardFold[];
  oos_metrics: BacktestMetrics;
  baseline_oos_return_pct: number;
  efficiency: number | null;
  distinct_choices: number;
  verdict: { level: "robust" | "weak" | "overfit" | "unprofitable" | "inconclusive"; headline: string; notes: string[] };
  equity_curve: { time: number; equity: number; baseline: number; benchmark: number }[];
}

export interface ResearchSummary {
  id: number;
  kind: "sweep" | "walk_forward";
  strategy_id: number;
  strategy_name: string;
  strategy_version: number;
  asset: Asset;
  timeframe: Timeframe;
  start_at: string | null;
  end_at: string | null;
  data_source: string;
  created_at: string;
  headline: string | null;
}

export interface ResearchRequest {
  strategy_id: number;
  bars: number;
  initial_capital: number;
  fee_bps: number;
  slippage_bps: number;
  params: { path: string; values: number[] }[];
  objective: ResearchObjective;
  min_trades: number;
  folds?: number;
  is_ratio?: number;
  /** Set on saved runs: bars actually loaded, which can be fewer than requested near an asset's listing date. */
  bars_used?: number;
  history_complete?: boolean;
}

export type ResearchRun = ResearchSummary & { request: ResearchRequest; disclaimer: string } & (
    | { kind: "sweep"; result: SweepResult }
    | { kind: "walk_forward"; result: WalkForwardResult }
  );

export interface HistoryCoverage {
  symbol: string;
  timeframe: Timeframe;
  /** null for synthetic sample data, which is generated on demand and never stored */
  stored_bars: number | null;
  first: string | null;
  last: string | null;
  is_sample: boolean;
  max_bars: number;
}

// -------------------------------------------------------------------- alerts
export interface AlertSettings {
  enabled: boolean;
  on_entry: boolean;
  on_exit: boolean;
  notify_email: boolean;
}

export interface StrategyAlert extends AlertSettings {
  id: number;
  strategy_id: number;
  strategy_name: string;
  symbol: string | null;
  timeframe: Timeframe | null;
  last_bar_at: string | null;
  last_checked_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface AlertEvent {
  id: number;
  strategy_id: number;
  strategy_version: number;
  kind: "entry" | "exit";
  symbol: string;
  timeframe: Timeframe;
  bar_at: string;
  close_price: number;
  message: string;
  data_source: string;
  created_at: string;
  read_at: string | null;
  emailed_at: string | null;
}

export interface AlertEventsPage {
  events: AlertEvent[];
  unread: number;
  disclaimer: string;
}
