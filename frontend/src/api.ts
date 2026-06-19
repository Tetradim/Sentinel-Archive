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
  monitored_channels: string[];
  messages_recorded: number;
  parsed_alerts: number;
  unparsed_alerts: number;
  drift_alerts: number;
  last_message_timestamp?: string | null;
  last_error: string;
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

export async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  });
  const payload = (await response.json()) as unknown;
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
  testDiscordRecorder: () => requestJson<Record<string, unknown>>('/api/recorder/discord/test', { method: 'POST', body: '{}' }),
  startDiscordRecorder: () => requestJson<RecorderStatus>('/api/recorder/discord/start', { method: 'POST', body: '{}' }),
  stopDiscordRecorder: () => requestJson<RecorderStatus>('/api/recorder/discord/stop', { method: 'POST', body: '{}' }),
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
  exportRecordings: (channelId?: string) =>
    requestJson<ExportRecord>('/api/recordings/export', {
      method: 'POST',
      body: JSON.stringify({ channel_id: channelId || null }),
    }),
  replayEvents: () => requestJson<{ events: Array<Record<string, unknown>> }>('/api/replay/events?limit=100'),
};
