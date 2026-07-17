export type SimulationConfig = {
  starting_cash: number;
  default_quantity: number;
  max_allocation_pct: number;
  fill_ratio: number;
  slippage_bps: number;
  commission_per_order: number;
  latency_ms: number;
  reject_below_confidence: number;
  default_trailing_percent: number;
  regular_stop_percent: number;
  take_profit_percent: number;
  signal_buy_threshold: number;
  signal_sell_threshold: number;
};

export type Position = {
  symbol: string;
  quantity: number;
  avg_entry: number;
  entry_price: number;
  current_price: number;
  pnl: number;
  pnl_pct: number;
  trailing_enabled: boolean;
  trailing_percent?: number | null;
};

export type ReplaySession = {
  session_id: string;
  name: string;
  source: string;
  symbols: string[];
  bar_count: number;
  first_timestamp: string;
  last_timestamp: string;
};

export type SimulationSnapshot = {
  config: SimulationConfig;
  sessions: ReplaySession[];
  replay: {
    active: boolean;
    session_id?: string | null;
    speed: number;
    loop: boolean;
    index: number;
    current_timestamp?: string | null;
  };
  current_prices: Record<string, number>;
  account: {
    starting_cash: number;
    cash: number;
    total_equity: number;
    buying_power: number;
    day_pnl_dollar: number;
    day_pnl_pct: number;
    open_positions: number;
    positions: Record<string, Position>;
  };
  tickers: Array<{ symbol: string; enabled: boolean; trailing_enabled: boolean; trailing_percent?: number | null; auto_stop_reason?: string | null }>;
  decisions: Array<Record<string, unknown>>;
  event_log: Array<Record<string, unknown>>;
};

export type RecorderSettings = {
  discord_token: string;
  discord_channel_ids: string[];
  drift_amount_threshold: number;
  drift_percent_threshold: number;
  yfinance_enabled: boolean;
  record_all_channels: boolean;
};

export type RecorderStatus = {
  discord_connected: boolean;
  discord_state: string;
  active_session_id?: string | null;
  monitored_channels: string[];
  messages_recorded: number;
  parsed_alerts: number;
  unparsed_alerts: number;
  drift_alerts: number;
  last_message_timestamp?: string | null;
  last_error: string;
};

export type DiscordTestResult = {
  ok: boolean;
  status?: string;
  token_configured?: boolean;
  channel_ids?: string[];
  record_all_channels?: boolean;
  channels?: Array<Record<string, unknown>>;
  bot_user?: Record<string, unknown> | null;
  state?: string;
  last_error?: string;
};

export type ParsedAlert = {
  message_id: string;
  parse_status: 'parsed' | 'unparsed' | 'error';
  raw_text: string;
  parse_error?: string;
  action?: string | null;
  ticker?: string | null;
  expiration?: string | null;
  strike?: number | null;
  option_type?: string | null;
  alert_price?: number | null;
  sell_percentage?: number | null;
  confidence?: string;
  normalized?: Record<string, unknown>;
};

export type PriceDriftEvent = {
  alert_id: string;
  alert_price?: number | null;
  market_price?: number | null;
  price_drift_amount?: number | null;
  price_drift_pct?: number | null;
  drift_direction: string;
  price_drift_alert: boolean;
};

export type ExportRecord = {
  export_id: string;
  created_at: string;
  channel_id: string;
  channel_name: string;
  format: 'csv' | 'jsonl';
  file_path: string;
  row_count: number;
};

export type RecordingSession = {
  session_id: string;
  started_at: string;
  stopped_at?: string | null;
  channel_ids: string[];
  source: string;
  notes: string;
};

export type SentinelEchoReplayEvent = {
  event_id: string;
  type: 'discord_alert';
  timestamp: string;
  channel_id: string;
  payload: Record<string, unknown>;
};

export type SentinelEchoReplayResponse = {
  contract_version: string;
  mode: string;
  execution: string;
  event_count: number;
  manifest_hash_algorithm: string;
  manifest_sha256: string;
  filters: Record<string, unknown>;
  next_cursor?: string | null;
  events: SentinelEchoReplayEvent[];
};

export type SentinelEchoTestRun = {
  contract_version: string;
  mode: string;
  execution: string;
  run_id: string;
  name: string;
  created_at: string;
  execution_mode: string;
  replay_contract_version: string;
  event_count: number;
  file_path: string;
  manifest_hash_algorithm: string;
  manifest_sha256: string;
  replay_url: string;
  filters: Record<string, unknown>;
};

export type AssetClass = 'crypto' | 'crypto_futures' | 'stock' | 'options' | 'futures' | 'darkpool' | 'futures_risk';
export type TradeSide = 'long' | 'short';
export type BacktestRunKind = 'run' | 'sweep' | 'walk_forward' | 'stress';
export type OptionAction = 'buy' | 'sell' | 'exit';

export type MarketPriceBar = {
  timestamp: string;
  symbol: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  bid?: number | null;
  ask?: number | null;
  vwap?: number | null;
  trade_count?: number | null;
  mark_price?: number | null;
  index_price?: number | null;
  open_interest?: number | null;
};

export type OptionAlert = {
  timestamp: string;
  contract_key: string;
  action: OptionAction;
  quantity?: number;
  alert_price?: number | null;
  fill_price?: number | null;
};

export type OptionQuote = {
  timestamp: string;
  contract_key: string;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  last?: number | null;
};

export type BacktestCostModel = {
  fee_bps: number;
  slippage_bps: number;
  funding_bps_per_step: number;
  commission_per_trade: number;
  option_fill_price: 'mid' | 'last' | 'bid' | 'ask';
  option_multiplier: number;
  maker_fee_bps?: number | null;
  taker_fee_bps?: number | null;
  spread_bps?: number;
  commission_per_contract?: number;
  exchange_fee_per_contract?: number;
  liquidation_fee_bps?: number;
};

export type BacktestRunRequest = {
  asset_class: AssetClass;
  symbol: string;
  side: TradeSide;
  quantity: number;
  starting_equity: number;
  leverage: number;
  stop_loss_pct?: number | null;
  take_profit_pct?: number | null;
  trailing_stop_pct?: number | null;
  close_final_position: boolean;
  cost_model: BacktestCostModel;
  bars: MarketPriceBar[];
  option_alerts: OptionAlert[];
  option_quotes: OptionQuote[];
  metadata?: Record<string, unknown>;
};

export type BacktestTrade = {
  symbol: string;
  side: TradeSide;
  quantity: number;
  entry_time: string;
  entry_price: number;
  exit_time: string;
  exit_price: number;
  pnl: number;
  fees: number;
  mae: number;
  mfe: number;
  exit_reason: string;
};

export type BacktestMetrics = {
  starting_equity: number;
  ending_equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  total_return_pct: number;
  win_rate: number;
  trade_count: number;
  gross_profit: number;
  gross_loss: number;
  profit_factor: number;
  max_drawdown_pct: number;
  mae: number;
  mfe: number;
  average_win: number;
  average_loss: number;
  total_fees: number;
  slippage: number;
  funding: number;
  safety_score: number;
  safety_flags: string[];
};

export type BacktestReport = {
  run_id?: string;
  asset_class: AssetClass;
  symbol: string;
  metrics: BacktestMetrics;
  trades: BacktestTrade[];
  warnings: string[];
  assumptions: Record<string, unknown>;
};

export type BacktestWalkForwardWindow = {
  train_range: { start: string; end: string };
  test_range: { start: string; end: string };
  report: BacktestReport;
};

export type BacktestRunRecord = {
  run_id: string;
  created_at: string;
  kind: BacktestRunKind;
  asset_class: AssetClass;
  symbol: string;
  fingerprint: string;
  request: Record<string, unknown>;
  report: BacktestReport;
  result: {
    reports?: BacktestReport[];
    windows?: BacktestWalkForwardWindow[];
    [key: string]: unknown;
  };
};

export type BacktestRunsResponse = {
  runs: BacktestRunRecord[];
  limit?: number;
  offset?: number;
  total?: number;
  has_more?: boolean;
};

export type PresetCatalog = {
  strategies: Array<Record<string, unknown>>;
  brackets: Array<Record<string, unknown>>;
  risk: Array<Record<string, unknown>>;
  cost_models: Array<Record<string, unknown>>;
  suite_profiles: Array<Record<string, unknown>>;
};

export type ArchiveDatasetRecord = {
  dataset_id: string;
  created_at: string;
  name: string;
  asset_class: AssetClass;
  symbol: string;
  fingerprint: string;
  bars: MarketPriceBar[];
  funding_events?: FundingEvent[];
  contract_spec?: FuturesContractSpec | null;
  option_alerts: OptionAlert[];
  option_quotes: OptionQuote[];
  metadata: Record<string, unknown>;
};

export type FundingEvent = { timestamp: string; rate: number; mark_price?: number | null };

export type FuturesContractSpec = {
  symbol: string;
  venue: string;
  instrument_type: 'listed_future' | 'crypto_perpetual' | 'crypto_delivery';
  contract_multiplier: number;
  tick_size: number;
  quantity_step: number;
  minimum_quantity: number;
  maximum_quantity?: number | null;
  initial_margin_rate: number;
  maintenance_margin_rate: number;
  maximum_leverage: number;
  inverse?: boolean;
};

export type MarketDataProviderInfo = {
  provider_id: string;
  name: string;
  free_access: boolean;
  authentication: string;
  asset_classes: string[];
  capabilities: string[];
  limitations: string[];
  homepage: string;
};

export type MarketDataFetchResult = {
  provider: string;
  symbol: string;
  asset_class: AssetClass;
  interval: string;
  fingerprint: string;
  bars: MarketPriceBar[];
  funding_events: FundingEvent[];
  warnings: string[];
  metadata: Record<string, unknown>;
  dataset_id?: string | null;
};

export type DerivativesReport = {
  run_id: string;
  fingerprint: string;
  bot_id: string;
  symbol: string;
  contract: FuturesContractSpec;
  metrics: Record<string, number | string | string[]>;
  executions: Array<Record<string, unknown>>;
  account_curve: Array<Record<string, unknown>>;
  warnings: string[];
  assumptions: Record<string, unknown>;
};

export type DifferentialAuditReport = {
  audit_id: string;
  fingerprint: string;
  name: string;
  layers: Record<string, DerivativesReport>;
  divergences: Array<Record<string, unknown>>;
  combined_assessment: Record<string, unknown>;
};

export type ArchiveDatasetsResponse = {
  datasets: ArchiveDatasetRecord[];
  limit: number;
  offset: number;
  total: number;
  has_more: boolean;
};

export type SuiteComputeBudget = {
  max_jobs: number;
  max_runtime_seconds?: number | null;
  priority?: 'low' | 'normal' | 'high';
};

export type SuitePlanRequest = {
  name: string;
  profile?: string | null;
  bots?: string[];
  test_families?: string[];
  assets?: string[];
  timeframe?: string | null;
  date_range?: Record<string, string>;
  strategy_presets?: string[];
  bracket_presets?: string[];
  risk_presets?: string[];
  cost_model?: Record<string, unknown>;
  compute_budget?: SuiteComputeBudget;
  schedule?: Record<string, unknown>;
  change_triggers?: string[];
  allow_live_execution?: boolean;
  required_bots?: string[];
};

export type SuiteJob = {
  job_id: string;
  bot_id: string;
  test_family: string;
  status: 'planned' | 'skipped' | 'passed' | 'warning' | 'failed';
  repo_path?: string | null;
  assets: string[];
  skipped_reason?: string | null;
  evidence: Record<string, unknown>;
};

export type SuitePlan = {
  plan_id: string;
  created_at: string;
  name: string;
  profile?: string | null;
  fingerprint: string;
  jobs: SuiteJob[];
  request: Record<string, unknown>;
};

export type SuiteRun = {
  run_id: string;
  plan_id: string;
  created_at: string;
  status: 'planned' | 'skipped' | 'passed' | 'warning' | 'failed';
  fingerprint: string;
  jobs: SuiteJob[];
};

function queryString(params: Record<string, string | number | null | undefined>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : '';
}

function channelIdsValue(channelIds?: string[]) {
  const clean = (channelIds ?? []).map((item) => item.trim()).filter(Boolean);
  return clean.length ? clean.join(',') : undefined;
}

export async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;
  if (!response.ok) {
    const message = payload && typeof payload === 'object' && 'detail' in payload ? String((payload as { detail: unknown }).detail) : `${response.status} ${response.statusText}`;
    throw new Error(message);
  }
  return payload as T;
}

export const api = {
  state: () => requestJson<SimulationSnapshot>('/api/simulation/state'),
  updateConfig: (config: SimulationConfig) =>
    requestJson<SimulationSnapshot>('/api/simulation/config', {
      method: 'PUT',
      body: JSON.stringify(config),
    }),
  importCsv: (name: string, csvText: string) =>
    requestJson<{ ok: boolean; session: ReplaySession }>('/api/simulation/replay/import/csv', {
      method: 'POST',
      body: JSON.stringify({ name, csv_text: csvText }),
    }),
  startReplay: (sessionId: string, speed: number, loop: boolean) =>
    requestJson<SimulationSnapshot>(`/api/simulation/replay/sessions/${sessionId}/start`, {
      method: 'POST',
      body: JSON.stringify({ speed, loop }),
    }),
  stepReplay: () => requestJson<SimulationSnapshot>('/api/simulation/replay/step', { method: 'POST', body: '{}' }),
  stopReplay: () => requestJson<SimulationSnapshot>('/api/simulation/replay/stop', { method: 'POST', body: '{}' }),
  handoff: (payload: Record<string, unknown>) =>
    requestJson<Record<string, unknown>>('/api/edge/handoff', {
      method: 'POST',
      headers: { 'X-API-Key': 'local-sim-key' },
      body: JSON.stringify(payload),
    }),
  recorderSettings: () => requestJson<RecorderSettings>('/api/recorder/discord/settings'),
  updateRecorderSettings: (settings: RecorderSettings) =>
    requestJson<RecorderSettings>('/api/recorder/discord/settings', {
      method: 'PUT',
      body: JSON.stringify(settings),
    }),
  recorderStatus: () => requestJson<RecorderStatus>('/api/recorder/discord/status'),
  testDiscordRecorder: () => requestJson<DiscordTestResult>('/api/recorder/discord/test', { method: 'POST', body: '{}' }),
  startDiscordRecorder: () => requestJson<RecorderStatus>('/api/recorder/discord/start', { method: 'POST', body: '{}' }),
  stopDiscordRecorder: () => requestJson<RecorderStatus>('/api/recorder/discord/stop', { method: 'POST', body: '{}' }),
  startRecordingSession: (notes = '', source = 'ui') =>
    requestJson<{ active_session_id: string; session: RecordingSession; status: string }>('/api/recordings/sessions/start', {
      method: 'POST',
      body: JSON.stringify({ notes, source }),
    }),
  stopRecordingSession: () => requestJson<{ active_session_id: string | null; session: RecordingSession | null; status: string }>('/api/recordings/sessions/stop', { method: 'POST', body: '{}' }),
  parsePreview: (rawText: string) =>
    requestJson<ParsedAlert>('/api/recorder/discord/parse-preview', {
      method: 'POST',
      body: JSON.stringify({ raw_text: rawText }),
    }),
  importDiscordCsv: (csvText: string) =>
    requestJson<{ inserted: number; rows: number }>('/api/recorder/discord/import-csv', {
      method: 'POST',
      body: JSON.stringify({ csv_text: csvText }),
    }),
  importOptionsCsv: (csvText: string) =>
    requestJson<{ inserted: number }>('/api/recorder/market/import/options-csv', {
      method: 'POST',
      body: JSON.stringify({ csv_text: csvText }),
    }),
  importStocksCsv: (csvText: string) =>
    requestJson<{ inserted: number }>('/api/recorder/market/import/stocks-csv', {
      method: 'POST',
      body: JSON.stringify({ csv_text: csvText }),
    }),
  recorderAlerts: () => requestJson<{ alerts: ParsedAlert[] }>('/api/recordings/alerts?limit=50'),
  recorderDriftEvents: () => requestJson<{ drift_events: PriceDriftEvent[] }>('/api/recordings/drift-events?limit=50'),
  recorderExports: () => requestJson<{ exports: ExportRecord[] }>('/api/recordings/exports?limit=20'),
  exportRecordings: (channelIds?: string[], exportType: 'alerts' | 'joined' = 'joined') =>
    requestJson<ExportRecord>('/api/recordings/export', {
      method: 'POST',
      body: JSON.stringify({ channel_ids: channelIds ?? [], export_type: exportType }),
    }),
  replayEvents: () => requestJson<{ events: Array<Record<string, unknown>> }>('/api/replay/events?limit=100'),
  sentinelEchoReplayEvents: (channelIds?: string[], since?: string, limit = 100) =>
    requestJson<SentinelEchoReplayResponse>(`/api/sentinel-echo/replay/events${queryString({ channel_ids: channelIdsValue(channelIds), since, limit })}`),
  createSentinelEchoTestRun: (name: string, channelIds?: string[], since?: string, limit = 1000) =>
    requestJson<SentinelEchoTestRun>('/api/sentinel-echo/test-runs', {
      method: 'POST',
      body: JSON.stringify({ name, channel_ids: channelIds ?? [], since: since || null, limit }),
    }),
  archivePresets: () => requestJson<PresetCatalog>('/api/archive/presets'),
  archiveRuns: (filters: Record<string, string | number | null | undefined> = {}) => requestJson<BacktestRunsResponse>(`/api/archive/backtest/runs${queryString(filters)}`),
  archiveRun: (runId: string) => requestJson<BacktestRunRecord>(`/api/archive/backtest/runs/${encodeURIComponent(runId)}`),
  runArchiveBacktest: (request: BacktestRunRequest) =>
    requestJson<BacktestRunRecord>('/api/archive/backtest/run', {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  runArchiveSweep: (body: { base_request: BacktestRunRequest; stop_loss_pcts: Array<number | null>; take_profit_pcts: Array<number | null>; leverage_values: number[] }) =>
    requestJson<BacktestRunRecord>('/api/archive/backtest/sweeps', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  runArchiveWalkForward: (body: { base_request: BacktestRunRequest; train_size: number; test_size: number; step_size: number }) =>
    requestJson<BacktestRunRecord>('/api/archive/backtest/walk-forward', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  runArchiveStress: (body: { base_request: BacktestRunRequest; scenarios: Array<{ name: string; price_shock_pct: number; slippage_bps?: number | null }> }) =>
    requestJson<BacktestRunRecord>('/api/archive/backtest/stress', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  archiveDatasets: (filters: Record<string, string | number | null | undefined> = {}) => requestJson<ArchiveDatasetsResponse>(`/api/archive/datasets${queryString(filters)}`),
  createArchiveDataset: (body: { name: string; asset_class: AssetClass; symbol: string; bars: MarketPriceBar[]; option_alerts: OptionAlert[]; option_quotes: OptionQuote[]; metadata?: Record<string, unknown> }) =>
    requestJson<ArchiveDatasetRecord>('/api/archive/datasets', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  marketDataProviders: () => requestJson<{ providers: MarketDataProviderInfo[] }>('/api/archive/market-data/providers'),
  fetchMarketData: (body: Record<string, unknown>) =>
    requestJson<MarketDataFetchResult>('/api/archive/market-data/fetch', { method: 'POST', body: JSON.stringify(body) }),
  derivativesContracts: () => requestJson<{ contracts: Record<string, FuturesContractSpec>; warning: string }>('/api/archive/derivatives/contracts'),
  runDerivatives: (body: Record<string, unknown>) =>
    requestJson<DerivativesReport>('/api/archive/derivatives/run', { method: 'POST', body: JSON.stringify(body) }),
  compareDerivatives: (body: Record<string, unknown>) =>
    requestJson<DifferentialAuditReport>('/api/archive/derivatives/compare', { method: 'POST', body: JSON.stringify(body) }),
  derivativesRuns: (filters: Record<string, string | number | null | undefined> = {}) =>
    requestJson<{ runs: Array<DerivativesReport | DifferentialAuditReport> }>(`/api/archive/derivatives/runs${queryString(filters)}`),
  suitePlans: (limit = 100) => requestJson<{ plans: SuitePlan[] }>(`/api/archive/bot-suite/plans${queryString({ limit })}`),
  createSuitePlan: (request: SuitePlanRequest) =>
    requestJson<SuitePlan>('/api/archive/bot-suite/plans', {
      method: 'POST',
      body: JSON.stringify(request),
    }),
  suiteRuns: (limit = 100) => requestJson<{ runs: SuiteRun[] }>(`/api/archive/bot-suite/runs${queryString({ limit })}`),
  runSuitePlan: (planId: string) => requestJson<SuiteRun>(`/api/archive/bot-suite/plans/${encodeURIComponent(planId)}/run`, { method: 'POST', body: '{}' }),
  suiteRun: (runId: string) => requestJson<SuiteRun>(`/api/archive/bot-suite/runs/${encodeURIComponent(runId)}`),
};
