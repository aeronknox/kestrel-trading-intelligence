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
  /** "short" profits from falling prices (backtests and research only). */
  direction: "long" | "short";
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
  /** Absent on backtests run before short selling existed (they were long). */
  side?: "long" | "short";
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
  direction?: "long" | "short";
  /** Equity reached zero or below at some point (possible for shorts on a gap). */
  ruined?: boolean;
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
/** "stop" is a stop-market order: it becomes a market order once the price reaches stop_price. */
export type OrderType = "market" | "limit" | "stop" | "trailing_stop";
export type OrderStatus = "open" | "filled" | "cancelled" | "rejected" | "expired";

export interface Order {
  id: number;
  asset: Asset;
  side: OrderSide;
  order_type: OrderType;
  quantity: number;
  limit_price: number | null;
  stop_price?: number | null;
  /** Trailing stops: distance (%) from the best price since placement (trail_anchor); stop_price follows it. */
  trail_pct?: number | null;
  trail_anchor?: number | null;
  /** Entry orders: protection attached once they fill. */
  bracket_stop_loss?: number | null;
  bracket_take_profit?: number | null;
  /** Only shrinks a position; cancelled automatically once the position is closed. */
  reduce_only?: boolean;
  /** One-cancels-other group, e.g. a position's stop-loss and take-profit. */
  oco_group?: string | null;
  status: OrderStatus;
  filled_price: number | null;
  fee: number;
  reject_reason: string | null;
  created_at: string;
  filled_at: string | null;
  /** Time in force: a resting order still open at this time expires. Null: good till cancelled. */
  expires_at?: string | null;
  /** Set when a strategy's forward test placed the order. */
  strategy_id?: number | null;
  /** Why the system placed it, e.g. a margin call. */
  note?: string | null;
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
  side?: "long" | "short";
  /** Signed: negative for a short. */
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
  /** Simulated short selling: sell while flat, buy to cover. */
  allow_short?: boolean;
  /** Your new positions must carry a stop-loss. */
  require_stop_loss?: boolean;
  /** Cap on what a new position's stop-loss would lose, as % of equity; implies a stop. Null: off. */
  max_risk_per_trade_pct?: number | null;
}

export interface Portfolio {
  id: number;
  name: string;
  starting_balance: number;
  cash_balance: number;
  /** Worst-case cost of open orders that add risk, held back from new orders. */
  reserved_cash: number;
  /** Cost to buy back all shorts at current prices. */
  short_liability?: number;
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
  kind: "sweep" | "walk_forward" | "portfolio";
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
  /** Multi-asset runs: assets whose history was still being downloaded. */
  incomplete_history?: string[];
}

export interface PortfolioRequestBody {
  strategy_id: number;
  symbols: string[];
  bars: number;
  initial_capital: number;
  fee_bps: number;
  slippage_bps: number;
}

export interface PortfolioAsset extends RunSummaryMetrics {
  symbol: string;
  bars: number;
  buy_hold_return_pct: number;
  final_equity: number;
}

export interface PortfolioResult {
  symbols: string[];
  window: { start: number; end: number };
  capital_per_asset: number;
  per_asset: PortfolioAsset[];
  metrics: BacktestMetrics;
  correlation: { symbols: string[]; matrix: (number | null)[][]; average: number | null };
  equity_curve: { time: number; equity: number; drawdown_pct: number; benchmark: number }[];
}

export type ResearchRun = ResearchSummary & { request: ResearchRequest & { symbols?: string[] }; disclaimer: string } & (
    | { kind: "sweep"; result: SweepResult }
    | { kind: "walk_forward"; result: WalkForwardResult }
    | { kind: "portfolio"; result: PortfolioResult }
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
  /** Post events to the webhook set in account settings. */
  notify_webhook: boolean;
  /** Forward test: place simulated paper orders on the strategy's signals. */
  auto_trade: boolean;
}

export interface Webhook {
  url: string | null;
  /** Also post simulated paper order fills, rejections and margin calls. */
  orders: boolean;
  format: "slack" | "discord" | "json" | null;
  /** Signs generic JSON deliveries (X-Kestrel-Signature). */
  secret: string | null;
  last_status: string | null;
  last_at: string | null;
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
  order_id?: number | null;
}

export interface ForwardTrip {
  entry_at: string;
  exit_at: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  return_pct: number;
  note: string | null;
}

export interface ForwardTest {
  started_at: string | null;
  orders: number;
  rejected: number;
  round_trips: ForwardTrip[];
  open_position: { symbol: string; quantity: number; entry_price: number; entry_at: string; current_price: number; unrealized_pnl: number } | null;
  realized_pnl: number;
  num_trades: number;
  win_rate: number | null;
  as_of: string;
  disclaimer: string;
}

export interface JournalEntry {
  setup: string | null;
  emotion: string | null;
  /** How well the plan was followed, 1-5. */
  rating: number | null;
  notes: string;
  lesson: string;
  /** Where the plan was to exit at a loss; overrides the stop found on the orders. */
  planned_stop: number | null;
  updated_at: string;
}

/** One simulated round trip: from flat, into a position, and back to flat. */
export interface JournalTrip {
  /** The opening fill; journal entries attach to it. */
  trade_id: number;
  symbol: string;
  side: "long" | "short";
  opened_at: string;
  closed_at: string | null;
  quantity: number;
  entry_price: number;
  exit_price: number | null;
  /** Null while the trip is open. */
  pnl: number | null;
  pnl_pct: number | null;
  fees: number;
  holding_seconds: number | null;
  fills: number;
  /** The first stop: from the journal, the entry's stop-loss, or the first protective stop order. */
  initial_stop: number | null;
  stop_source: "journal" | "bracket" | "stop order" | null;
  /** What hitting the initial stop would have lost. */
  risk: number | null;
  /** P&L in units of that risk; null while open or without a stop. */
  r_multiple: number | null;
  entry: JournalEntry | null;
}

export interface JournalGroup {
  /** Null: not reviewed / not recorded. */
  name: string | null;
  trades: number;
  win_rate: number;
  total_pnl: number;
  /** Expectancy: the average result per trade. */
  avg_pnl: number;
  avg_win: number | null;
  avg_loss: number | null;
  avg_rating: number | null;
  /** Trades with a known initial risk, and their average R-multiple. */
  r_trades: number;
  avg_r: number | null;
}

export interface JournalPage {
  trips: JournalTrip[];
  by_setup: JournalGroup[];
  by_emotion: JournalGroup[];
  setups: string[];
  emotions: string[];
  needs_review: number;
  /** Every closed trade; null before the first one closes. */
  overall: JournalGroup | null;
  disclaimer: string;
}

/** A simulated paper order that filled or failed in the background (not a strategy alert). */
export interface AppNotification {
  id: number;
  kind: "order_filled" | "order_rejected" | "order_expired" | "margin_call";
  title: string;
  message: string;
  symbol: string | null;
  order_id: number | null;
  created_at: string;
  read_at: string | null;
}

export interface NotificationsPage {
  notifications: AppNotification[];
  unread: number;
}

export interface AlertEventsPage {
  events: AlertEvent[];
  unread: number;
  disclaimer: string;
}
