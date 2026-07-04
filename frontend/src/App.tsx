import React from 'react';
import {
  Activity,
  ArrowRightLeft,
  Banknote,
  Bot,
  Boxes,
  ChartNoAxesCombined,
  ClipboardList,
  Database,
  Download,
  FileJson,
  FileSpreadsheet,
  FileUp,
  Gauge,
  History,
  MessageSquare,
  Pause,
  Play,
  PlugZap,
  RadioTower,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldAlert,
  ShieldCheck,
  SkipForward,
  SlidersHorizontal,
  Trophy,
  Upload,
  Workflow,
} from 'lucide-react';
import {
  api,
  type ArchiveDatasetRecord,
  type AssetClass,
  type BacktestCostModel,
  type BacktestReport,
  type BacktestRunRecord,
  type BacktestRunRequest,
  type BacktestTrade,
  type DiscordTestResult,
  type ExportRecord,
  type MarketPriceBar,
  type OptionAlert,
  type OptionQuote,
  type ParsedAlert,
  type PresetCatalog,
  type PriceDriftEvent,
  type RecorderSettings,
  type RecorderStatus,
  type SentinelEchoReplayResponse,
  type SentinelEchoTestRun,
  type SimulationConfig,
  type SimulationSnapshot,
  type SuiteJob,
  type SuitePlan,
  type SuiteRun,
  type TradeSide,
} from './api';

const emptyCsv = 'timestamp,symbol,open,high,low,close,volume\n';
const emptyDiscordCsv = 'message_id,channel_id,channel_name,author_id,author_name,discord_timestamp,content\n';
const emptyOptionCsv = 'timestamp,underlying,expiration,strike,option_type,open,high,low,close,volume,bid,ask,last\n';

const sampleArchiveBars = `timestamp,symbol,open,high,low,close,volume
2026-07-01T13:30:00Z,SPY,100,101.2,99.4,100.8,10000
2026-07-01T13:31:00Z,SPY,100.8,102.1,100.2,101.7,11200
2026-07-01T13:32:00Z,SPY,101.7,103.4,101.1,102.9,12800
2026-07-01T13:33:00Z,SPY,102.9,104.8,102.2,104.1,14700
2026-07-01T13:34:00Z,SPY,104.1,105.2,103.4,104.7,12000
2026-07-01T13:35:00Z,SPY,104.7,106.4,104.0,105.9,16000`;

const sampleOptionAlerts = `timestamp,contract_key,action,quantity,alert_price,fill_price
2026-07-01T14:00:00Z,SPY-20260717-500-C,buy,1,1.20,
2026-07-01T14:45:00Z,SPY-20260717-500-C,sell,1,1.65,`;

const sampleOptionQuotes = `timestamp,contract_key,bid,ask,mid,last
2026-07-01T14:00:00Z,SPY-20260717-500-C,1.15,1.25,1.20,1.20
2026-07-01T14:45:00Z,SPY-20260717-500-C,1.60,1.70,1.65,1.66`;

const defaultCostModel: BacktestCostModel = {
  fee_bps: 0,
  slippage_bps: 1,
  funding_bps_per_step: 0,
  commission_per_trade: 0,
  option_fill_price: 'mid',
  option_multiplier: 100,
};

type WorkflowKey = 'builder' | 'history' | 'detail' | 'compare' | 'exports' | 'bots' | 'replay';
type Tone = 'good' | 'warn' | 'bad' | 'neutral' | 'purple' | 'gold';

type RankedReport = {
  key: string;
  source: string;
  kind: string;
  report: BacktestReport;
  windowLabel?: string;
};

function money(value: unknown) {
  if (value === null || value === undefined || value === '') return '—';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(parsed);
}

function number(value: unknown, digits = 2) {
  if (value === null || value === undefined || value === '') return '—';
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(parsed);
}

function pct(value: unknown, digits = 2) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '—';
  return `${number(parsed, digits)}%`;
}

function isoMinute() {
  return Math.floor(Date.now() / 60000);
}

function parseChannelIds(value: string) {
  const ids: string[] = [];
  for (const part of value.split(/[\s,;]+/)) {
    const clean = part.trim();
    if (clean && !ids.includes(clean)) ids.push(clean);
  }
  return ids;
}

function formatWhen(value?: string | null) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString();
}

function cleanLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitCsvLine(line: string) {
  const cells: string[] = [];
  let current = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '"') {
      if (quoted && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
      continue;
    }
    if (char === ',' && !quoted) {
      cells.push(current.trim());
      current = '';
      continue;
    }
    current += char;
  }
  cells.push(current.trim());
  return cells;
}

function csvRows(text: string) {
  const lines = cleanLines(text);
  if (lines.length < 2) return [];
  const headers = splitCsvLine(lines[0]).map((header) => header.trim().toLowerCase());
  return lines.slice(1).map((line) => {
    const cells = splitCsvLine(line);
    const row: Record<string, string> = {};
    headers.forEach((header, index) => {
      row[header] = cells[index] ?? '';
    });
    return row;
  });
}

function maybeNumber(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseBarsCsv(text: string, symbolFallback: string): MarketPriceBar[] {
  const rows = csvRows(text);
  const bars = rows.map((row) => {
    const open = maybeNumber(row.open);
    const high = maybeNumber(row.high);
    const low = maybeNumber(row.low);
    const close = maybeNumber(row.close);
    if (!row.timestamp || open === null || high === null || low === null || close === null) {
      throw new Error('Bars CSV needs timestamp, open, high, low, and close columns.');
    }
    return {
      timestamp: row.timestamp,
      symbol: (row.symbol || symbolFallback || 'SPY').toUpperCase(),
      open,
      high,
      low,
      close,
      volume: maybeNumber(row.volume) ?? 0,
    };
  });
  if (!bars.length) throw new Error('Add at least one market bar or choose the options replay asset class.');
  return bars;
}

function parseOptionAlertsCsv(text: string): OptionAlert[] {
  const alerts = csvRows(text).map((row) => {
    if (!row.timestamp || !row.contract_key || !row.action) {
      throw new Error('Option alert CSV needs timestamp, contract_key, and action columns.');
    }
    const action = row.action.toLowerCase();
    if (!['buy', 'sell', 'exit'].includes(action)) throw new Error(`Unsupported option action: ${row.action}`);
    return {
      timestamp: row.timestamp,
      contract_key: row.contract_key,
      action: action as OptionAlert['action'],
      quantity: maybeNumber(row.quantity) ?? 1,
      alert_price: maybeNumber(row.alert_price),
      fill_price: maybeNumber(row.fill_price),
    };
  });
  if (!alerts.length) throw new Error('Options replay needs at least one alert row.');
  return alerts;
}

function parseOptionQuotesCsv(text: string): OptionQuote[] {
  return csvRows(text).map((row) => {
    if (!row.timestamp || !row.contract_key) {
      throw new Error('Option quote CSV needs timestamp and contract_key columns.');
    }
    return {
      timestamp: row.timestamp,
      contract_key: row.contract_key,
      bid: maybeNumber(row.bid),
      ask: maybeNumber(row.ask),
      mid: maybeNumber(row.mid),
      last: maybeNumber(row.last),
    };
  });
}

function parseNullableNumberList(value: string) {
  return value
    .split(/[\s,;]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => (['none', 'null', 'off'].includes(item.toLowerCase()) ? null : Number(item)))
    .filter((item) => item === null || Number.isFinite(item)) as Array<number | null>;
}

function parseStressScenarios(value: string) {
  const rows = cleanLines(value);
  return rows.map((line) => {
    const [name = 'scenario', shock = '0', slippage = ''] = splitCsvLine(line);
    return {
      name: name.trim() || 'scenario',
      price_shock_pct: Number(shock) || 0,
      slippage_bps: maybeNumber(slippage),
    };
  });
}

function barsToCsv(bars: MarketPriceBar[]) {
  return ['timestamp,symbol,open,high,low,close,volume', ...bars.map((bar) => [bar.timestamp, bar.symbol, bar.open, bar.high, bar.low, bar.close, bar.volume ?? 0].join(','))].join('\n');
}

function optionAlertsToCsv(alerts: OptionAlert[]) {
  return ['timestamp,contract_key,action,quantity,alert_price,fill_price', ...alerts.map((alert) => [alert.timestamp, alert.contract_key, alert.action, alert.quantity ?? 1, alert.alert_price ?? '', alert.fill_price ?? ''].join(','))].join('\n');
}

function optionQuotesToCsv(quotes: OptionQuote[]) {
  return ['timestamp,contract_key,bid,ask,mid,last', ...quotes.map((quote) => [quote.timestamp, quote.contract_key, quote.bid ?? '', quote.ask ?? '', quote.mid ?? '', quote.last ?? ''].join(','))].join('\n');
}

function reportsFromRecord(record: BacktestRunRecord | null | undefined): RankedReport[] {
  if (!record) return [];
  if (record.kind === 'walk_forward' && Array.isArray(record.result?.windows)) {
    return record.result.windows.map((window, index) => ({
      key: `${record.run_id}:window:${index}`,
      source: record.run_id,
      kind: record.kind,
      report: window.report,
      windowLabel: `${window.test_range.start} → ${window.test_range.end}`,
    }));
  }
  if (Array.isArray(record.result?.reports)) {
    return record.result.reports.map((report, index) => ({
      key: `${record.run_id}:report:${index}`,
      source: record.run_id,
      kind: record.kind,
      report,
    }));
  }
  return [{ key: `${record.run_id}:report`, source: record.run_id, kind: record.kind, report: record.report }];
}

function reportVariantLabel(report: BacktestReport) {
  const sweep = report.assumptions?.sweep as Record<string, unknown> | undefined;
  const stress = report.assumptions?.stress as Record<string, unknown> | undefined;
  if (sweep) return `SL ${sweep.stop_loss_pct ?? '—'} / TP ${sweep.take_profit_pct ?? '—'} / ${sweep.leverage ?? 1}x`;
  if (stress) return String(stress.name ?? 'stress');
  return report.trades[0]?.exit_reason || 'base report';
}

export function App() {
  const [workflow, setWorkflow] = React.useState<WorkflowKey>('builder');
  const [status, setStatus] = React.useState('Idle');
  const [error, setError] = React.useState('');
  const [archiveStatus, setArchiveStatus] = React.useState('Archive ready');
  const [archiveError, setArchiveError] = React.useState('');

  const [snapshot, setSnapshot] = React.useState<SimulationSnapshot | null>(null);
  const [configDraft, setConfigDraft] = React.useState<SimulationConfig | null>(null);
  const [csvName, setCsvName] = React.useState('Recorded market day');
  const [csvText, setCsvText] = React.useState(emptyCsv);
  const [selectedSession, setSelectedSession] = React.useState('');
  const [speed, setSpeed] = React.useState(30);
  const [loop, setLoop] = React.useState(false);
  const [symbol, setSymbol] = React.useState('SPY');
  const [action, setAction] = React.useState('buy');
  const [confidence, setConfidence] = React.useState(0.9);
  const [trail, setTrail] = React.useState(2);
  const [recorderSettings, setRecorderSettings] = React.useState<RecorderSettings | null>(null);
  const [recorderDirty, setRecorderDirty] = React.useState(false);
  const [recorderStatus, setRecorderStatus] = React.useState<RecorderStatus | null>(null);
  const [discordTestResult, setDiscordTestResult] = React.useState<DiscordTestResult | null>(null);
  const [previewText, setPreviewText] = React.useState('BTO SPY 500C 6/21 @ 1.25');
  const [previewAlert, setPreviewAlert] = React.useState<ParsedAlert | null>(null);
  const [discordCsvText, setDiscordCsvText] = React.useState(emptyDiscordCsv);
  const [optionsCsvText, setOptionsCsvText] = React.useState(emptyOptionCsv);
  const [stocksCsvText, setStocksCsvText] = React.useState(emptyCsv);
  const [recorderAlerts, setRecorderAlerts] = React.useState<ParsedAlert[]>([]);
  const [driftEvents, setDriftEvents] = React.useState<PriceDriftEvent[]>([]);
  const [exportChannelIdsText, setExportChannelIdsText] = React.useState('');
  const [exportType, setExportType] = React.useState<'alerts' | 'joined'>('joined');
  const [exports, setExports] = React.useState<ExportRecord[]>([]);
  const [sentinelEchoChannelIdsText, setSentinelEchoChannelIdsText] = React.useState('');
  const [sentinelEchoSince, setSentinelEchoSince] = React.useState('');
  const [sentinelEchoReplay, setSentinelEchoReplay] = React.useState<SentinelEchoReplayResponse | null>(null);
  const [sentinelEchoTestRun, setSentinelEchoTestRun] = React.useState<SentinelEchoTestRun | null>(null);

  const [presets, setPresets] = React.useState<PresetCatalog | null>(null);
  const [archiveRuns, setArchiveRuns] = React.useState<BacktestRunRecord[]>([]);
  const [historyTotal, setHistoryTotal] = React.useState(0);
  const [historyPage, setHistoryPage] = React.useState(0);
  const [selectedArchiveRun, setSelectedArchiveRun] = React.useState<BacktestRunRecord | null>(null);
  const [datasets, setDatasets] = React.useState<ArchiveDatasetRecord[]>([]);
  const [historyFilters, setHistoryFilters] = React.useState({
    asset_class: '',
    symbol: '',
    kind: '',
    created_at_from: '',
    created_at_to: '',
    safety_score_min: '',
    safety_score_max: '',
  });

  const [assetClass, setAssetClass] = React.useState<AssetClass>('stock');
  const [backtestSymbol, setBacktestSymbol] = React.useState('SPY');
  const [side, setSide] = React.useState<TradeSide>('long');
  const [quantity, setQuantity] = React.useState(10);
  const [startingEquity, setStartingEquity] = React.useState(25000);
  const [leverage, setLeverage] = React.useState(1);
  const [stopLossPct, setStopLossPct] = React.useState(1.2);
  const [takeProfitPct, setTakeProfitPct] = React.useState(2.4);
  const [trailingStopPct, setTrailingStopPct] = React.useState(0.8);
  const [closeFinalPosition, setCloseFinalPosition] = React.useState(true);
  const [costModel, setCostModel] = React.useState<BacktestCostModel>(defaultCostModel);
  const [barsCsv, setBarsCsv] = React.useState(sampleArchiveBars);
  const [optionAlertsText, setOptionAlertsText] = React.useState(sampleOptionAlerts);
  const [optionQuotesText, setOptionQuotesText] = React.useState(sampleOptionQuotes);
  const [sweepStops, setSweepStops] = React.useState('0.8, 1.2, 2');
  const [sweepTargets, setSweepTargets] = React.useState('1.6, 2.4, 4');
  const [sweepLeverages, setSweepLeverages] = React.useState('1');
  const [walkTrain, setWalkTrain] = React.useState(2);
  const [walkTest, setWalkTest] = React.useState(2);
  const [walkStep, setWalkStep] = React.useState(1);
  const [stressScenarios, setStressScenarios] = React.useState('selloff,-3,8\nslippage spike,0,15\nrally,2,2');
  const [datasetName, setDatasetName] = React.useState('Archive UI dataset');

  const [suiteName, setSuiteName] = React.useState('Archive evidence plan');
  const [suiteProfile, setSuiteProfile] = React.useState('');
  const [suiteBotsText, setSuiteBotsText] = React.useState('echo');
  const [suiteFamiliesText, setSuiteFamiliesText] = React.useState('options_replay\nparser_preview\npaper_shadow');
  const [suiteAssetsText, setSuiteAssetsText] = React.useState('SPY');
  const [suiteMaxJobs, setSuiteMaxJobs] = React.useState(8);
  const [suitePriority, setSuitePriority] = React.useState<'low' | 'normal' | 'high'>('normal');
  const [suitePlans, setSuitePlans] = React.useState<SuitePlan[]>([]);
  const [suiteRuns, setSuiteRuns] = React.useState<SuiteRun[]>([]);
  const [selectedSuitePlan, setSelectedSuitePlan] = React.useState<SuitePlan | null>(null);
  const [selectedSuiteRun, setSelectedSuiteRun] = React.useState<SuiteRun | null>(null);

  const historyPageSize = 10;

  const refreshLegacy = React.useCallback(async () => {
    const [next, settings, recorder, alerts, drift, exportList] = await Promise.all([
      api.state(),
      api.recorderSettings(),
      api.recorderStatus(),
      api.recorderAlerts(),
      api.recorderDriftEvents(),
      api.recorderExports(),
    ]);
    setSnapshot(next);
    setRecorderSettings((current) => (recorderDirty && current ? current : settings));
    setRecorderStatus(recorder);
    setRecorderAlerts(alerts.alerts);
    setDriftEvents(drift.drift_events);
    setExports(exportList.exports);
    setConfigDraft((current) => current ?? next.config);
    setSelectedSession((current) => current || next.sessions[0]?.session_id || '');
  }, [recorderDirty]);

  const refreshArchive = React.useCallback(async () => {
    const filters = {
      limit: historyPageSize,
      offset: historyPage * historyPageSize,
      asset_class: historyFilters.asset_class,
      symbol: historyFilters.symbol.trim().toUpperCase(),
      kind: historyFilters.kind,
      created_at_from: historyFilters.created_at_from,
      created_at_to: historyFilters.created_at_to,
      safety_score_min: historyFilters.safety_score_min,
      safety_score_max: historyFilters.safety_score_max,
    };
    const [runList, presetCatalog, datasetList, plans, runs] = await Promise.all([
      api.archiveRuns(filters),
      api.archivePresets(),
      api.archiveDatasets({ limit: 50 }),
      api.suitePlans(50),
      api.suiteRuns(50),
    ]);
    setArchiveRuns(runList.runs);
    setHistoryTotal(runList.total ?? runList.runs.length);
    setPresets(presetCatalog);
    setDatasets(datasetList.datasets);
    setSuitePlans(plans.plans);
    setSuiteRuns(runs.runs);
    setSelectedArchiveRun((current) => current || runList.runs[0] || null);
    setSelectedSuitePlan((current) => current || plans.plans[0] || null);
    setSelectedSuiteRun((current) => current || runs.runs[0] || null);
  }, [historyFilters, historyPage]);

  React.useEffect(() => {
    refreshArchive().catch((err) => setArchiveError(err instanceof Error ? err.message : String(err)));
  }, [refreshArchive]);

  React.useEffect(() => {
    const id = window.setInterval(() => {
      refreshArchive().catch(() => undefined);
    }, 4000);
    return () => window.clearInterval(id);
  }, [refreshArchive]);

  React.useEffect(() => {
    refreshLegacy().catch(() => undefined);
  }, [refreshLegacy]);

  React.useEffect(() => {
    if (workflow !== 'replay') return undefined;
    const id = window.setInterval(() => {
      refreshLegacy().catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(id);
  }, [workflow, refreshLegacy]);

  async function run<T>(label: string, fn: () => Promise<T>) {
    setError('');
    setStatus(label);
    try {
      await fn();
      await refreshLegacy();
      setStatus('Idle');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus('Error');
    }
  }

  async function archiveRun<T>(label: string, fn: () => Promise<T>) {
    setArchiveError('');
    setArchiveStatus(label);
    try {
      await fn();
      await refreshArchive();
      setArchiveStatus('Archive ready');
    } catch (err) {
      setArchiveError(err instanceof Error ? err.message : String(err));
      setArchiveStatus('Archive error');
    }
  }

  async function loadFile(file: File | null) {
    if (!file) return;
    setCsvName(file.name.replace(/\.[^.]+$/, ''));
    setCsvText(await file.text());
  }

  async function loadArchiveBarsFile(file: File | null) {
    if (!file) return;
    setDatasetName(file.name.replace(/\.[^.]+$/, ''));
    setBarsCsv(await file.text());
  }

  function updateConfig<K extends keyof SimulationConfig>(key: K, value: SimulationConfig[K]) {
    setConfigDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  function updateRecorder<K extends keyof RecorderSettings>(key: K, value: RecorderSettings[K]) {
    setRecorderDirty(true);
    setRecorderSettings((current) => (current ? { ...current, [key]: value } : current));
  }

  function updateCost<K extends keyof BacktestCostModel>(key: K, value: BacktestCostModel[K]) {
    setCostModel((current) => ({ ...current, [key]: value }));
  }

  async function saveRecorderSettings(settings: RecorderSettings) {
    const saved = await api.updateRecorderSettings(settings);
    setRecorderSettings(saved);
    setRecorderDirty(false);
  }

  function handoffPayload() {
    const normalized = symbol.trim().toUpperCase() || 'SPY';
    const stopType = action.includes('trailing') ? 'trailing' : action === 'regular_stop' ? 'regular' : undefined;
    return {
      contract_version: 'edge.pulse.handoff.v1',
      symbol: normalized,
      action,
      confidence,
      reason: 'operator simulation control',
      mode: 'paper',
      orb_session: 'market_open',
      stop_type: stopType,
      trailing_percent: stopType === 'trailing' ? trail : undefined,
      idempotency_key: `edge:${normalized}:${action}:market_open:${isoMinute()}:ui`,
      source: 'sentinel_edge',
      created_at: Date.now() / 1000,
      metadata: {},
    };
  }

  function buildBacktestRequest(): BacktestRunRequest {
    const normalizedSymbol = backtestSymbol.trim().toUpperCase() || 'SPY';
    const isOptions = assetClass === 'options';
    return {
      asset_class: assetClass,
      symbol: normalizedSymbol,
      side: assetClass === 'stock' ? 'long' : side,
      quantity,
      starting_equity: startingEquity,
      leverage: assetClass === 'stock' || isOptions ? 1 : leverage,
      stop_loss_pct: stopLossPct > 0 ? stopLossPct : null,
      take_profit_pct: takeProfitPct > 0 ? takeProfitPct : null,
      trailing_stop_pct: trailingStopPct > 0 ? trailingStopPct : null,
      close_final_position: closeFinalPosition,
      cost_model: costModel,
      bars: isOptions ? [] : parseBarsCsv(barsCsv, normalizedSymbol),
      option_alerts: isOptions ? parseOptionAlertsCsv(optionAlertsText) : [],
      option_quotes: isOptions ? parseOptionQuotesCsv(optionQuotesText) : [],
      metadata: {
        source: 'archive-ui',
        notes: [
          assetClass === 'stock' ? 'stock engine is long-only first' : '',
          assetClass === 'options' ? 'options engine is alert replay with explicit quote/fill assumptions' : '',
          assetClass === 'crypto' ? 'crypto liquidation check is simplified and not exchange-specific' : '',
        ].filter(Boolean),
      },
    };
  }

  function applyStrategyPreset(preset: Record<string, unknown>) {
    const request = preset.request as Partial<BacktestRunRequest> | undefined;
    if (!request) return;
    if (request.asset_class) setAssetClass(request.asset_class);
    if (request.symbol) setBacktestSymbol(request.symbol);
    if (request.side) setSide(request.side);
    if (typeof request.quantity === 'number') setQuantity(request.quantity);
    if (typeof request.starting_equity === 'number') setStartingEquity(request.starting_equity);
    if (typeof request.leverage === 'number') setLeverage(request.leverage);
    setStopLossPct(typeof request.stop_loss_pct === 'number' ? request.stop_loss_pct : 0);
    setTakeProfitPct(typeof request.take_profit_pct === 'number' ? request.take_profit_pct : 0);
    setTrailingStopPct(typeof request.trailing_stop_pct === 'number' ? request.trailing_stop_pct : 0);
    if (request.cost_model) setCostModel({ ...defaultCostModel, ...request.cost_model });
  }

  function applyBracketPreset(preset: Record<string, unknown>) {
    setStopLossPct(Number(preset.stop_loss_pct ?? 0));
    setTakeProfitPct(Number(preset.take_profit_pct ?? 0));
    setTrailingStopPct(Number(preset.trailing_stop_pct ?? 0));
  }

  function applyRiskPreset(preset: Record<string, unknown>) {
    if (typeof preset.starting_equity === 'number') setStartingEquity(preset.starting_equity);
    if (typeof preset.quantity === 'number') setQuantity(preset.quantity);
    if (typeof preset.leverage === 'number') setLeverage(preset.leverage);
    if (typeof preset.max_jobs === 'number') setSuiteMaxJobs(preset.max_jobs);
  }

  function applyCostPreset(preset: Record<string, unknown>) {
    const next = preset.cost_model as Partial<BacktestCostModel> | undefined;
    if (next) setCostModel({ ...defaultCostModel, ...next });
  }

  function applySuitePreset(preset: Record<string, unknown>) {
    setSuiteProfile(String(preset.profile ?? ''));
    const bots = Array.isArray(preset.bots) ? preset.bots.map(String) : [];
    const families = Array.isArray(preset.test_families) ? preset.test_families.map(String) : [];
    if (bots.length) setSuiteBotsText(bots.join('\n'));
    if (families.length) setSuiteFamiliesText(families.join('\n'));
    const budget = preset.compute_budget as Record<string, unknown> | undefined;
    if (typeof budget?.max_jobs === 'number') setSuiteMaxJobs(budget.max_jobs);
    if (budget?.priority === 'low' || budget?.priority === 'normal' || budget?.priority === 'high') setSuitePriority(budget.priority);
  }

  function loadDataset(dataset: ArchiveDatasetRecord) {
    setDatasetName(dataset.name);
    setAssetClass(dataset.asset_class);
    setBacktestSymbol(dataset.symbol);
    if (dataset.bars.length) setBarsCsv(barsToCsv(dataset.bars));
    if (dataset.option_alerts.length) setOptionAlertsText(optionAlertsToCsv(dataset.option_alerts));
    if (dataset.option_quotes.length) setOptionQuotesText(optionQuotesToCsv(dataset.option_quotes));
    setWorkflow('builder');
  }

  const positions = Object.values(snapshot?.account.positions ?? {});
  const driftByAlert = React.useMemo(() => new Map(driftEvents.map((event) => [event.alert_id, event])), [driftEvents]);
  const latestExport = exports[0];
  const exportChannelIds = React.useMemo(() => parseChannelIds(exportChannelIdsText), [exportChannelIdsText]);
  const sentinelEchoChannelIds = React.useMemo(() => parseChannelIds(sentinelEchoChannelIdsText), [sentinelEchoChannelIdsText]);
  const sentinelEchoReplayUrl = React.useMemo(() => {
    const params = new URLSearchParams();
    if (sentinelEchoChannelIds.length) params.set('channel_ids', sentinelEchoChannelIds.join(','));
    if (sentinelEchoSince.trim()) params.set('since', sentinelEchoSince.trim());
    params.set('limit', '100');
    return `/api/sentinel-echo/replay/events?${params.toString()}`;
  }, [sentinelEchoChannelIds, sentinelEchoSince]);

  const selectedReports = React.useMemo(() => reportsFromRecord(selectedArchiveRun), [selectedArchiveRun]);
  const rankedReports = React.useMemo(() => {
    const fromHistory = archiveRuns.flatMap(reportsFromRecord);
    const combined = selectedArchiveRun ? [...fromHistory, ...selectedReports] : fromHistory;
    const unique = new Map<string, RankedReport>();
    combined.forEach((item) => unique.set(item.key, item));
    return [...unique.values()].sort((a, b) => {
      const safetyDelta = b.report.metrics.safety_score - a.report.metrics.safety_score;
      return safetyDelta || b.report.metrics.total_pnl - a.report.metrics.total_pnl;
    });
  }, [archiveRuns, selectedArchiveRun, selectedReports]);

  const bestReport = rankedReports[0]?.report;
  const totalPnl = archiveRuns.reduce((sum, item) => sum + (item.report.metrics.total_pnl || 0), 0);
  const suiteJobCount = suiteRuns.reduce((sum, item) => sum + item.jobs.length, 0);

  const workflowItems: Array<{ key: WorkflowKey; label: string; icon: React.ReactNode; help: string }> = [
    { key: 'builder', label: 'Plan', icon: <Workflow size={22} />, help: 'Backtest, sweeps, walk-forward, stress' },
    { key: 'history', label: 'History', icon: <History size={22} />, help: 'Filters and pagination' },
    { key: 'detail', label: 'Detail', icon: <ClipboardList size={22} />, help: 'Report and composite payloads' },
    { key: 'compare', label: 'Ranks', icon: <Trophy size={22} />, help: 'Compare reports across runs' },
    { key: 'exports', label: 'Exports', icon: <Download size={22} />, help: 'JSON, CSV, datasets' },
    { key: 'bots', label: 'Bots', icon: <Bot size={22} />, help: 'Bot-suite evidence' },
    { key: 'replay', label: 'Replay', icon: <RotateCcw size={22} />, help: 'Legacy simulator and recorder' },
  ];

  return (
    <div className="app-shell">
      <div className="ambient ambient-purple" aria-hidden="true" />
      <div className="ambient ambient-gold" aria-hidden="true" />
      <div className="grid-glow" aria-hidden="true" />

      <aside className="left-rail" aria-label="Archive workflow navigation">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">SA</div>
          <div>
            <div className="brand-title">Sentinel Archive</div>
            <div className="brand-subtitle">Backtest Workbench</div>
          </div>
        </div>
        <nav className="rail-nav">
          {workflowItems.map((item) => (
            <button className={`rail-item ${workflow === item.key ? 'active' : ''}`} type="button" key={item.key} onClick={() => setWorkflow(item.key)} title={item.help} aria-label={`${item.label} workflow`}>
              {item.icon}
              <b>{item.label}</b>
            </button>
          ))}
        </nav>
      </aside>

      <section className="main-shell">
        <header className="topbar">
          <div className="system-title">
            <span className="title-dot" />
            <div>
              <h1>Archive Research Console</h1>
              <p>Plan Builder · Run History · Report Detail · Compare/Ranks · Exports · Bot Evidence</p>
            </div>
          </div>
          <div className="ticker-strip" aria-label="Archive summary">
            <Ticker label="Runs" value={number(historyTotal || archiveRuns.length, 0)} sub={`${archiveRuns.length} loaded`} />
            <Ticker label="Best Safety" value={bestReport ? number(bestReport.metrics.safety_score, 0) : '—'} sub={bestReport?.symbol || 'no reports'} tone={bestReport && bestReport.metrics.safety_score < 70 ? 'warn' : 'good'} />
            <Ticker label="History PnL" value={money(totalPnl)} sub="visible page" tone={totalPnl >= 0 ? 'good' : 'bad'} />
            <Ticker label="Bot Evidence" value={number(suiteJobCount, 0)} sub={`${suiteRuns.length} suite runs`} tone="purple" />
          </div>
          <div className="topbar-actions">
            <Badge tone={archiveError ? 'bad' : 'good'} label={archiveError || archiveStatus} />
            <Badge tone={error ? 'bad' : status === 'Idle' ? 'neutral' : 'warn'} label={error || status} />
            <button className="icon-button" type="button" onClick={() => archiveRun('Refreshing archive', refreshArchive)} title="Refresh archive" aria-label="Refresh archive">
              <RefreshCw size={18} />
            </button>
          </div>
        </header>

        <section className="control-ribbon glass-panel">
          <label className="field compact">Asset
            <select value={assetClass} onChange={(event) => setAssetClass(event.target.value as AssetClass)}>
              <option value="stock">Stock</option>
              <option value="crypto">Crypto</option>
              <option value="options">Options</option>
            </select>
          </label>
          <label className="field compact">Symbol
            <input value={backtestSymbol} onChange={(event) => setBacktestSymbol(event.target.value)} />
          </label>
          <label className="field compact">Kind
            <select value={workflow} onChange={(event) => setWorkflow(event.target.value as WorkflowKey)}>
              {workflowItems.map((item) => <option value={item.key} key={item.key}>{item.label}</option>)}
            </select>
          </label>
          <div className="ribbon-copy">
            <strong>{selectedArchiveRun ? selectedArchiveRun.run_id : 'No selected run'}</strong>
            <span>{selectedArchiveRun ? `${selectedArchiveRun.kind} · ${formatWhen(selectedArchiveRun.created_at)}` : 'Create a run from Plan Builder to populate Report Detail.'}</span>
          </div>
          <button className="primary-btn" type="button" onClick={() => archiveRun('Running backtest', async () => {
            const record = await api.runArchiveBacktest(buildBacktestRequest());
            setSelectedArchiveRun(record);
            setWorkflow('detail');
          })}>Run Backtest</button>
          <button className="secondary-btn" type="button" onClick={() => archiveRun('Running sweep', async () => {
            const record = await api.runArchiveSweep({
              base_request: buildBacktestRequest(),
              stop_loss_pcts: parseNullableNumberList(sweepStops),
              take_profit_pcts: parseNullableNumberList(sweepTargets),
              leverage_values: parseNullableNumberList(sweepLeverages).filter((item): item is number => item !== null),
            });
            setSelectedArchiveRun(record);
            setWorkflow('compare');
          })}>Sweep</button>
          <button className="secondary-btn" type="button" onClick={() => setWorkflow('bots')}>Bot Evidence</button>
        </section>

        <main className="workspace">
          {workflow === 'builder' ? renderBuilderWorkflow() : null}
          {workflow === 'history' ? renderHistoryWorkflow() : null}
          {workflow === 'detail' ? renderDetailWorkflow() : null}
          {workflow === 'compare' ? renderCompareWorkflow() : null}
          {workflow === 'exports' ? renderExportsWorkflow() : null}
          {workflow === 'bots' ? renderBotsWorkflow() : null}
          {workflow === 'replay' ? renderReplayWorkflow() : null}
        </main>
      </section>
    </div>
  );

  function renderBuilderWorkflow() {
    return (
      <div className="workflow-grid builder-layout">
        <section className="glass-panel panel-card span-8">
          <PanelHeader icon={<Workflow size={18} />} title="Plan Builder" subtitle="Inline bars and alerts go directly to /api/archive/backtest/* routes." />
          <div className="preset-strip">
            {(presets?.strategies ?? []).map((preset) => (
              <button className="tool-btn" type="button" key={String(preset.id)} onClick={() => applyStrategyPreset(preset)}>{String(preset.name)}</button>
            ))}
          </div>
          <div className="ticket-grid builder-grid">
            <label>Asset class
              <select value={assetClass} onChange={(event) => setAssetClass(event.target.value as AssetClass)}>
                <option value="stock">stock</option>
                <option value="crypto">crypto</option>
                <option value="options">options</option>
              </select>
            </label>
            <label>Symbol
              <input value={backtestSymbol} onChange={(event) => setBacktestSymbol(event.target.value.toUpperCase())} />
            </label>
            <label>Side
              <select value={assetClass === 'stock' ? 'long' : side} disabled={assetClass === 'stock' || assetClass === 'options'} onChange={(event) => setSide(event.target.value as TradeSide)}>
                <option value="long">long</option>
                <option value="short">short</option>
              </select>
            </label>
            <NumberField label="Quantity" value={quantity} step={0.01} onChange={setQuantity} />
            <NumberField label="Starting equity" value={startingEquity} onChange={setStartingEquity} />
            <NumberField label="Leverage" value={assetClass === 'stock' || assetClass === 'options' ? 1 : leverage} step={0.5} onChange={setLeverage} />
            <NumberField label="Stop %" value={stopLossPct} step={0.1} onChange={setStopLossPct} />
            <NumberField label="Target %" value={takeProfitPct} step={0.1} onChange={setTakeProfitPct} />
            <NumberField label="Trailing %" value={trailingStopPct} step={0.1} onChange={setTrailingStopPct} />
            <label className="check-card">
              <input type="checkbox" checked={closeFinalPosition} onChange={(event) => setCloseFinalPosition(event.target.checked)} />
              <span>Close final position</span>
            </label>
          </div>
          <div className="assumption-row">
            <Badge tone="gold" label="Consumes FastAPI Archive routes" />
            <Badge tone={assetClass === 'stock' ? 'warn' : 'neutral'} label="Stock short support is intentionally hidden" />
            <Badge tone={assetClass === 'options' ? 'warn' : 'neutral'} label="Options replay uses explicit fills, not pricing" />
            <Badge tone={assetClass === 'crypto' ? 'warn' : 'neutral'} label="Crypto liquidation checks are simplified" />
          </div>
          {assetClass === 'options' ? (
            <div className="dual-editor">
              <label className="field editor-field">Option alerts CSV
                <textarea value={optionAlertsText} onChange={(event) => setOptionAlertsText(event.target.value)} spellCheck={false} />
              </label>
              <label className="field editor-field">Option quotes CSV
                <textarea value={optionQuotesText} onChange={(event) => setOptionQuotesText(event.target.value)} spellCheck={false} />
              </label>
            </div>
          ) : (
            <label className="field editor-field">Market bars CSV
              <div className="file-line">
                <span>timestamp,symbol,open,high,low,close,volume</span>
                <label className="mini-file-button"><Upload size={14} /> Load <input type="file" accept=".csv,text/csv" onChange={(event) => loadArchiveBarsFile(event.target.files?.[0] ?? null)} /></label>
              </div>
              <textarea value={barsCsv} onChange={(event) => setBarsCsv(event.target.value)} spellCheck={false} />
            </label>
          )}
        </section>

        <section className="glass-panel panel-card span-4">
          <PanelHeader icon={<Gauge size={18} />} title="Presets, Costs, Dataset" subtitle="Presets are served by /api/archive/presets." />
          <div className="mini-section">
            <h3>Brackets</h3>
            <div className="chip-stack">{(presets?.brackets ?? []).map((preset) => <button className="chip-btn" type="button" key={String(preset.id)} onClick={() => applyBracketPreset(preset)}>{String(preset.name)}</button>)}</div>
          </div>
          <div className="mini-section">
            <h3>Risk</h3>
            <div className="chip-stack">{(presets?.risk ?? []).map((preset) => <button className="chip-btn" type="button" key={String(preset.id)} onClick={() => applyRiskPreset(preset)}>{String(preset.name)}</button>)}</div>
          </div>
          <div className="mini-section">
            <h3>Cost models</h3>
            <div className="chip-stack">{(presets?.cost_models ?? []).map((preset) => <button className="chip-btn" type="button" key={String(preset.id)} onClick={() => applyCostPreset(preset)}>{String(preset.name)}</button>)}</div>
          </div>
          <div className="cost-grid">
            <NumberField label="Fee bps" value={costModel.fee_bps} step={0.1} onChange={(value) => updateCost('fee_bps', value)} />
            <NumberField label="Slippage bps" value={costModel.slippage_bps} step={0.1} onChange={(value) => updateCost('slippage_bps', value)} />
            <NumberField label="Funding bps/step" value={costModel.funding_bps_per_step} step={0.1} onChange={(value) => updateCost('funding_bps_per_step', value)} />
            <NumberField label="Commission" value={costModel.commission_per_trade} step={0.01} onChange={(value) => updateCost('commission_per_trade', value)} />
            <label className="field">Option fill
              <select value={costModel.option_fill_price} onChange={(event) => updateCost('option_fill_price', event.target.value as BacktestCostModel['option_fill_price'])}>
                <option value="mid">mid</option>
                <option value="last">last</option>
                <option value="bid">bid</option>
                <option value="ask">ask</option>
              </select>
            </label>
            <NumberField label="Multiplier" value={costModel.option_multiplier} step={1} onChange={(value) => updateCost('option_multiplier', value)} />
          </div>
          <div className="mini-section">
            <h3>Dataset</h3>
            <label className="field">Name
              <input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} />
            </label>
            <button className="primary-btn wide-button" type="button" onClick={() => archiveRun('Saving dataset', async () => {
              const request = buildBacktestRequest();
              await api.createArchiveDataset({
                name: datasetName,
                asset_class: request.asset_class,
                symbol: request.symbol,
                bars: request.bars,
                option_alerts: request.option_alerts,
                option_quotes: request.option_quotes,
                metadata: { source: 'archive-ui' },
              });
            })}>Save Dataset</button>
          </div>
        </section>

        <section className="glass-panel panel-card span-12">
          <PanelHeader icon={<ChartNoAxesCombined size={18} />} title="Composite Runs" subtitle="Composite responses are saved run records; details live under record.result.reports or record.result.windows." />
          <div className="composite-grid">
            <div className="composite-card">
              <h3>Parameter Sweep</h3>
              <label className="field">Stop loss % list <input value={sweepStops} onChange={(event) => setSweepStops(event.target.value)} /></label>
              <label className="field">Take profit % list <input value={sweepTargets} onChange={(event) => setSweepTargets(event.target.value)} /></label>
              <label className="field">Leverage list <input value={sweepLeverages} onChange={(event) => setSweepLeverages(event.target.value)} /></label>
              <button className="secondary-btn" type="button" onClick={() => archiveRun('Running sweep', async () => {
                const record = await api.runArchiveSweep({
                  base_request: buildBacktestRequest(),
                  stop_loss_pcts: parseNullableNumberList(sweepStops),
                  take_profit_pcts: parseNullableNumberList(sweepTargets),
                  leverage_values: parseNullableNumberList(sweepLeverages).filter((item): item is number => item !== null),
                });
                setSelectedArchiveRun(record);
                setWorkflow('compare');
              })}>Run Sweep</button>
            </div>
            <div className="composite-card">
              <h3>Walk-forward</h3>
              <NumberField label="Train bars" value={walkTrain} onChange={setWalkTrain} />
              <NumberField label="Test bars" value={walkTest} onChange={setWalkTest} />
              <NumberField label="Step bars" value={walkStep} onChange={setWalkStep} />
              <button className="secondary-btn" type="button" onClick={() => archiveRun('Running walk-forward', async () => {
                const record = await api.runArchiveWalkForward({ base_request: buildBacktestRequest(), train_size: walkTrain, test_size: walkTest, step_size: walkStep });
                setSelectedArchiveRun(record);
                setWorkflow('detail');
              })}>Run Walk-forward</button>
            </div>
            <div className="composite-card">
              <h3>Stress</h3>
              <label className="field">Scenario CSV: name, price_shock_pct, slippage_bps
                <textarea className="compact-textarea" value={stressScenarios} onChange={(event) => setStressScenarios(event.target.value)} spellCheck={false} />
              </label>
              <button className="secondary-btn" type="button" onClick={() => archiveRun('Running stress', async () => {
                const record = await api.runArchiveStress({ base_request: buildBacktestRequest(), scenarios: parseStressScenarios(stressScenarios) });
                setSelectedArchiveRun(record);
                setWorkflow('compare');
              })}>Run Stress</button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  function renderHistoryWorkflow() {
    const maxPage = Math.max(0, Math.ceil(historyTotal / historyPageSize) - 1);
    return (
      <div className="workflow-grid">
        <section className="glass-panel panel-card span-12">
          <PanelHeader icon={<History size={18} />} title="Run History" subtitle="Filters and pagination call GET /api/archive/backtest/runs." />
          <div className="filter-grid">
            <label className="field">Asset
              <select value={historyFilters.asset_class} onChange={(event) => { setHistoryPage(0); setHistoryFilters((current) => ({ ...current, asset_class: event.target.value })); }}>
                <option value="">all</option><option value="stock">stock</option><option value="crypto">crypto</option><option value="options">options</option>
              </select>
            </label>
            <label className="field">Symbol <input value={historyFilters.symbol} onChange={(event) => { setHistoryPage(0); setHistoryFilters((current) => ({ ...current, symbol: event.target.value })); }} /></label>
            <label className="field">Kind
              <select value={historyFilters.kind} onChange={(event) => { setHistoryPage(0); setHistoryFilters((current) => ({ ...current, kind: event.target.value })); }}>
                <option value="">all</option><option value="run">run</option><option value="sweep">sweep</option><option value="walk_forward">walk_forward</option><option value="stress">stress</option>
              </select>
            </label>
            <label className="field">Created from <input value={historyFilters.created_at_from} onChange={(event) => { setHistoryPage(0); setHistoryFilters((current) => ({ ...current, created_at_from: event.target.value })); }} placeholder="2026-07-01" /></label>
            <label className="field">Created to <input value={historyFilters.created_at_to} onChange={(event) => { setHistoryPage(0); setHistoryFilters((current) => ({ ...current, created_at_to: event.target.value })); }} placeholder="2026-07-31" /></label>
            <label className="field">Safety min <input value={historyFilters.safety_score_min} onChange={(event) => { setHistoryPage(0); setHistoryFilters((current) => ({ ...current, safety_score_min: event.target.value })); }} /></label>
            <label className="field">Safety max <input value={historyFilters.safety_score_max} onChange={(event) => { setHistoryPage(0); setHistoryFilters((current) => ({ ...current, safety_score_max: event.target.value })); }} /></label>
            <button className="secondary-btn" type="button" onClick={() => archiveRun('Refreshing history', refreshArchive)}>Apply</button>
          </div>
          <RunHistoryTable runs={archiveRuns} selectedRunId={selectedArchiveRun?.run_id} onSelect={(record) => { setSelectedArchiveRun(record); setWorkflow('detail'); }} />
          <div className="pager-row">
            <button className="secondary-btn" type="button" disabled={historyPage <= 0} onClick={() => setHistoryPage((page) => Math.max(0, page - 1))}>Previous</button>
            <span>Page {historyPage + 1} of {maxPage + 1} · {number(historyTotal, 0)} runs</span>
            <button className="secondary-btn" type="button" disabled={historyPage >= maxPage} onClick={() => setHistoryPage((page) => Math.min(maxPage, page + 1))}>Next</button>
          </div>
        </section>
      </div>
    );
  }

  function renderDetailWorkflow() {
    return (
      <div className="workflow-grid detail-layout">
        <section className="glass-panel panel-card span-8">
          <PanelHeader icon={<ClipboardList size={18} />} title="Report Detail" subtitle="Single run metrics, trades, warnings, assumptions, and composite payload awareness." />
          {selectedArchiveRun ? (
            <>
              <div className="detail-title-row">
                <div>
                  <h2>{selectedArchiveRun.symbol} · {selectedArchiveRun.kind}</h2>
                  <p>{selectedArchiveRun.run_id} · {formatWhen(selectedArchiveRun.created_at)}</p>
                </div>
                <div className="button-row shrink">
                  <a className="secondary-link" href={`/api/archive/backtest/runs/${selectedArchiveRun.run_id}/export.json`} target="_blank" rel="noreferrer"><FileJson size={15} /> JSON</a>
                  <a className="secondary-link" href={`/api/archive/backtest/runs/${selectedArchiveRun.run_id}/export.csv`} target="_blank" rel="noreferrer"><FileSpreadsheet size={15} /> CSV</a>
                </div>
              </div>
              <ReportKpis report={selectedArchiveRun.report} />
              <Warnings warnings={[...selectedArchiveRun.report.warnings, ...selectedArchiveRun.report.metrics.safety_flags]} />
              <TradeTable trades={selectedArchiveRun.report.trades} />
            </>
          ) : <EmptyState label="No run selected" />}
        </section>
        <section className="glass-panel panel-card span-4">
          <PanelHeader icon={<Boxes size={18} />} title="Composite Payload" subtitle="Sweeps/stress: reports. Walk-forward: windows." />
          {selectedArchiveRun ? (
            <div className="result-stack">
              {selectedReports.map((item, index) => (
                <button className="result-card" type="button" key={item.key} onClick={() => setWorkflow('compare')}>
                  <span>#{index + 1} {item.kind}</span>
                  <strong>{reportVariantLabel(item.report)}</strong>
                  <em>{money(item.report.metrics.total_pnl)} · safety {number(item.report.metrics.safety_score, 0)}</em>
                  {item.windowLabel ? <small>{item.windowLabel}</small> : null}
                </button>
              ))}
            </div>
          ) : <EmptyState label="Create or select a run to see payload entries." />}
          <pre className="json-preview large">{selectedArchiveRun ? JSON.stringify({ request: selectedArchiveRun.request, result: selectedArchiveRun.result }, null, 2) : 'No selected run.'}</pre>
        </section>
      </div>
    );
  }

  function renderCompareWorkflow() {
    return (
      <div className="workflow-grid">
        <section className="glass-panel panel-card span-12">
          <PanelHeader icon={<Trophy size={18} />} title="Compare / Ranks" subtitle="Ranks every report in the visible page plus the selected composite details by safety score, then PnL." />
          <div className="rank-table">
            <div className="rank-row head"><span>#</span><span>Source</span><span>Kind</span><span>Symbol</span><span>Variant</span><span>Safety</span><span>PnL</span><span>Return</span><span>Trades</span><span>Flags</span></div>
            {rankedReports.length ? rankedReports.map((item, index) => (
              <button className="rank-row" type="button" key={item.key} onClick={() => {
                const parent = archiveRuns.find((record) => record.run_id === item.source) || selectedArchiveRun;
                if (parent) setSelectedArchiveRun(parent);
                setWorkflow('detail');
              }}>
                <span>{index + 1}</span>
                <span>{item.source}</span>
                <span>{item.kind}</span>
                <span>{item.report.symbol}</span>
                <span>{item.windowLabel || reportVariantLabel(item.report)}</span>
                <span className={item.report.metrics.safety_score >= 70 ? 'good' : 'warn'}>{number(item.report.metrics.safety_score, 0)}</span>
                <span className={item.report.metrics.total_pnl >= 0 ? 'good' : 'bad'}>{money(item.report.metrics.total_pnl)}</span>
                <span>{pct(item.report.metrics.total_return_pct)}</span>
                <span>{number(item.report.metrics.trade_count, 0)}</span>
                <span>{item.report.metrics.safety_flags.join(', ') || 'clear'}</span>
              </button>
            )) : <EmptyState label="No reports to rank yet." />}
          </div>
        </section>
      </div>
    );
  }

  function renderExportsWorkflow() {
    return (
      <div className="workflow-grid exports-layout">
        <section className="glass-panel panel-card span-6">
          <PanelHeader icon={<Download size={18} />} title="Backtest Exports" subtitle="Export endpoints are served by the Archive backend." />
          {selectedArchiveRun ? (
            <div className="export-cards">
              <a className="export-card" href={`/api/archive/backtest/runs/${selectedArchiveRun.run_id}/export.json`} target="_blank" rel="noreferrer"><FileJson size={24} /><strong>Report JSON</strong><span>{selectedArchiveRun.run_id}</span></a>
              <a className="export-card" href={`/api/archive/backtest/runs/${selectedArchiveRun.run_id}/export.csv`} target="_blank" rel="noreferrer"><FileSpreadsheet size={24} /><strong>Trades CSV</strong><span>{selectedArchiveRun.report.trades.length} trades</span></a>
            </div>
          ) : <EmptyState label="Select a run before exporting." />}
          <div className="path-list">
            <p>/api/archive/backtest/runs</p>
            <p>/api/archive/backtest/runs/{'{run_id}'}/export.json</p>
            <p>/api/archive/backtest/runs/{'{run_id}'}/export.csv</p>
          </div>
        </section>
        <section className="glass-panel panel-card span-6">
          <PanelHeader icon={<Database size={18} />} title="Saved Datasets" subtitle="Use datasets as reusable inline bars/alerts without creating a parallel backend." />
          <div className="dataset-list">
            {datasets.length ? datasets.map((dataset) => (
              <button className="dataset-card" type="button" key={dataset.dataset_id} onClick={() => loadDataset(dataset)}>
                <strong>{dataset.name}</strong>
                <span>{dataset.asset_class} · {dataset.symbol} · {dataset.bars.length || dataset.option_alerts.length} rows</span>
                <em>{dataset.dataset_id}</em>
              </button>
            )) : <EmptyState label="No saved datasets yet." />}
          </div>
        </section>
        <section className="glass-panel panel-card span-12">
          <PanelHeader icon={<FileJson size={18} />} title="Suite Export" subtitle="Bot-suite run exports remain evidence-only until native adapter execution is added." />
          <div className="suite-export-row">
            {suiteRuns.slice(0, 6).map((run) => (
              <a className="secondary-link" href={`/api/archive/bot-suite/runs/${run.run_id}/export.json`} target="_blank" rel="noreferrer" key={run.run_id}>{run.run_id}</a>
            ))}
          </div>
        </section>
      </div>
    );
  }

  function renderBotsWorkflow() {
    const displayRun = selectedSuiteRun || suiteRuns[0] || null;
    return (
      <div className="workflow-grid bots-layout">
        <section className="glass-panel panel-card span-5">
          <PanelHeader icon={<Bot size={18} />} title="Bot-Suite Planner" subtitle="POST /api/archive/bot-suite/plans; then run selected plan." />
          <div className="mini-section">
            <h3>Suite profiles</h3>
            <div className="chip-stack">{(presets?.suite_profiles ?? []).map((preset) => <button className="chip-btn" type="button" key={String(preset.id)} onClick={() => applySuitePreset(preset)}>{String(preset.name)}</button>)}</div>
          </div>
          <div className="ticket-grid one-col">
            <label>Name <input value={suiteName} onChange={(event) => setSuiteName(event.target.value)} /></label>
            <label>Profile <input value={suiteProfile} onChange={(event) => setSuiteProfile(event.target.value)} placeholder="Blank for selected bots/families" /></label>
            <label>Bots <textarea className="compact-textarea" value={suiteBotsText} onChange={(event) => setSuiteBotsText(event.target.value)} /></label>
            <label>Test families <textarea className="compact-textarea" value={suiteFamiliesText} onChange={(event) => setSuiteFamiliesText(event.target.value)} /></label>
            <label>Assets <input value={suiteAssetsText} onChange={(event) => setSuiteAssetsText(event.target.value)} /></label>
            <NumberField label="Max jobs" value={suiteMaxJobs} onChange={setSuiteMaxJobs} />
            <label>Priority
              <select value={suitePriority} onChange={(event) => setSuitePriority(event.target.value as 'low' | 'normal' | 'high')}><option>low</option><option>normal</option><option>high</option></select>
            </label>
          </div>
          <div className="button-row">
            <button className="primary-btn" type="button" onClick={() => archiveRun('Creating suite plan', async () => {
              const plan = await api.createSuitePlan({
                name: suiteName,
                profile: suiteProfile || null,
                bots: suiteProfile ? [] : parseChannelIds(suiteBotsText),
                test_families: suiteProfile ? [] : parseChannelIds(suiteFamiliesText),
                assets: parseChannelIds(suiteAssetsText),
                compute_budget: { max_jobs: suiteMaxJobs, priority: suitePriority },
                allow_live_execution: false,
              });
              setSelectedSuitePlan(plan);
            })}>Create Plan</button>
            <button className="secondary-btn" type="button" disabled={!selectedSuitePlan} onClick={() => selectedSuitePlan && archiveRun('Running suite plan', async () => {
              const suiteRun = await api.runSuitePlan(selectedSuitePlan.plan_id);
              setSelectedSuiteRun(suiteRun);
            })}>Run Plan</button>
          </div>
        </section>
        <section className="glass-panel panel-card span-7">
          <PanelHeader icon={<ShieldAlert size={18} />} title="Bot Evidence" subtitle="Planner currently creates safe planned/passed/skipped records; it does not execute native repo commands yet." />
          <div className="suite-columns">
            <div>
              <h3>Plans</h3>
              <div className="suite-list">
                {suitePlans.map((plan) => (
                  <button className={`suite-card ${selectedSuitePlan?.plan_id === plan.plan_id ? 'selected' : ''}`} type="button" key={plan.plan_id} onClick={() => setSelectedSuitePlan(plan)}>
                    <strong>{plan.name}</strong><span>{plan.jobs.length} jobs · {plan.profile || 'custom'}</span><em>{plan.plan_id}</em>
                  </button>
                ))}
              </div>
            </div>
            <div>
              <h3>Runs</h3>
              <div className="suite-list">
                {suiteRuns.map((run) => (
                  <button className={`suite-card ${selectedSuiteRun?.run_id === run.run_id ? 'selected' : ''}`} type="button" key={run.run_id} onClick={() => setSelectedSuiteRun(run)}>
                    <strong>{run.status}</strong><span>{run.jobs.length} jobs · {formatWhen(run.created_at)}</span><em>{run.run_id}</em>
                  </button>
                ))}
              </div>
            </div>
          </div>
          <SuiteJobs jobs={displayRun?.jobs || selectedSuitePlan?.jobs || []} />
        </section>
      </div>
    );
  }

  function renderReplayWorkflow() {
    return (
      <div className="workflow-grid replay-layout">
        <section className="glass-panel panel-card span-4">
          <PanelHeader icon={<SlidersHorizontal size={18} />} title="Execution Model" subtitle="Legacy simulator control remains available for Edge/Pulse contract tests." />
          {configDraft ? (
            <div className="ticket-grid two-col">
              <NumberField label="Starting cash" value={configDraft.starting_cash} onChange={(value) => updateConfig('starting_cash', value)} />
              <NumberField label="Default qty" value={configDraft.default_quantity} onChange={(value) => updateConfig('default_quantity', value)} />
              <NumberField label="Max allocation %" value={configDraft.max_allocation_pct} onChange={(value) => updateConfig('max_allocation_pct', value)} />
              <NumberField label="Fill ratio" value={configDraft.fill_ratio} step={0.05} onChange={(value) => updateConfig('fill_ratio', value)} />
              <NumberField label="Slippage bps" value={configDraft.slippage_bps} onChange={(value) => updateConfig('slippage_bps', value)} />
              <NumberField label="Commission" value={configDraft.commission_per_order} onChange={(value) => updateConfig('commission_per_order', value)} />
              <NumberField label="Reject below" value={configDraft.reject_below_confidence} step={0.05} onChange={(value) => updateConfig('reject_below_confidence', value)} />
              <NumberField label="Trail %" value={configDraft.default_trailing_percent} onChange={(value) => updateConfig('default_trailing_percent', value)} />
              <button className="primary-btn wide-button" type="button" onClick={() => run('Saving config', () => api.updateConfig(configDraft))}><Save size={15} /> Save Model</button>
            </div>
          ) : <EmptyState label="Loading simulator config." />}
        </section>
        <section className="glass-panel panel-card span-4">
          <PanelHeader icon={<FileUp size={18} />} title="Market Day Replay" subtitle="CSV import into the in-memory simulator." />
          <div className="stack">
            <label className="field">Session name <input value={csvName} onChange={(event) => setCsvName(event.target.value)} /></label>
            <label className="file-button"><Upload size={15} /> Load CSV <input type="file" accept=".csv,text/csv" onChange={(event) => loadFile(event.target.files?.[0] ?? null)} /></label>
            <textarea value={csvText} onChange={(event) => setCsvText(event.target.value)} spellCheck={false} />
            <button className="primary-btn" type="button" onClick={() => run('Importing CSV', () => api.importCsv(csvName, csvText))}><Upload size={15} /> Import Bars</button>
            <div className="session-list">
              {(snapshot?.sessions ?? []).map((session) => (
                <button type="button" className={selectedSession === session.session_id ? 'selected' : ''} key={session.session_id} onClick={() => setSelectedSession(session.session_id)}>
                  <strong>{session.name}</strong><span>{session.symbols.join(', ')} / {session.bar_count} bars</span>
                </button>
              ))}
            </div>
          </div>
        </section>
        <section className="glass-panel panel-card span-4">
          <PanelHeader icon={<Play size={18} />} title="Playback / Handoff" subtitle="Simulation-only handoff composer." />
          <div className="ticket-grid two-col">
            <NumberField label="Speed" value={speed} onChange={setSpeed} />
            <label className="check-card"><input type="checkbox" checked={loop} onChange={(event) => setLoop(event.target.checked)} /><span>Loop</span></label>
            <button type="button" onClick={() => selectedSession && run('Starting replay', () => api.startReplay(selectedSession, speed, loop))}><Play size={15} /> Start</button>
            <button type="button" onClick={() => run('Stepping replay', api.stepReplay)}><SkipForward size={15} /> Step</button>
            <button type="button" onClick={() => run('Stopping replay', api.stopReplay)}><Pause size={15} /> Stop</button>
            <label>Symbol <input value={symbol} onChange={(event) => setSymbol(event.target.value)} /></label>
            <label>Action
              <select value={action} onChange={(event) => setAction(event.target.value)}>
                {['buy', 'sell', 'trailing_stop', 'opening_trailing_stop', 'tighten_trailing_stop', 'regular_stop', 'stop_all', 'emergency_exit', 'dca', 'stop_buying'].map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <NumberField label="Confidence" value={confidence} step={0.05} onChange={setConfidence} />
            <NumberField label="Trail %" value={trail} onChange={setTrail} />
            <button className="primary-btn wide-button" type="button" onClick={() => run('Sending handoff', () => api.handoff(handoffPayload()))}><ArrowRightLeft size={15} /> Send Handoff</button>
          </div>
        </section>
        <section className="glass-panel panel-card span-4">
          <PanelHeader icon={<MessageSquare size={18} />} title="Discord Recorder" subtitle="Recorder-only capture, parser preview, and drift checks." />
          {recorderSettings ? (
            <div className="stack">
              <div className="recorder-status"><Badge tone={recorderStatus?.discord_connected ? 'good' : recorderStatus?.discord_state === 'failed' ? 'bad' : 'neutral'} label={recorderStatus?.discord_state || 'stopped'} /><span>{number(recorderStatus?.messages_recorded, 0)} messages</span><span>{number(recorderStatus?.parsed_alerts, 0)} parsed</span></div>
              <label className="field">Bot token <input type="password" value={recorderSettings.discord_token} onChange={(event) => updateRecorder('discord_token', event.target.value)} /></label>
              <label className="field">Channel IDs <textarea className="compact-textarea" value={recorderSettings.discord_channel_ids.join('\n')} onChange={(event) => updateRecorder('discord_channel_ids', parseChannelIds(event.target.value))} spellCheck={false} /></label>
              <ChannelChips ids={recorderSettings.record_all_channels ? ['*'] : recorderSettings.discord_channel_ids} emptyLabel="No channel IDs configured" />
              <div className="ticket-grid two-col">
                <NumberField label="Drift $" value={recorderSettings.drift_amount_threshold} step={0.01} onChange={(value) => updateRecorder('drift_amount_threshold', value)} />
                <NumberField label="Drift %" value={recorderSettings.drift_percent_threshold} onChange={(value) => updateRecorder('drift_percent_threshold', value)} />
                <label className="check-card"><input type="checkbox" checked={recorderSettings.record_all_channels} onChange={(event) => updateRecorder('record_all_channels', event.target.checked)} /><span>All channels</span></label>
                <label className="check-card"><input type="checkbox" checked={recorderSettings.yfinance_enabled} onChange={(event) => updateRecorder('yfinance_enabled', event.target.checked)} /><span>Live quotes</span></label>
              </div>
              <div className="button-row"><button className="primary-btn" type="button" onClick={() => run('Saving recorder', () => saveRecorderSettings(recorderSettings))}><Save size={15} /> Save</button><button type="button" onClick={() => run('Testing recorder', async () => setDiscordTestResult(await api.testDiscordRecorder()))}><PlugZap size={15} /> Test</button><button type="button" onClick={() => run('Starting recorder', api.startDiscordRecorder)}><Play size={15} /> Start</button><button type="button" onClick={() => run('Stopping recorder', api.stopDiscordRecorder)}><Pause size={15} /> Stop</button></div>
              {discordTestResult ? <pre className="json-preview short">{JSON.stringify(discordTestResult, null, 2)}</pre> : null}
              <label className="field">Parse preview <textarea className="compact-textarea" value={previewText} onChange={(event) => setPreviewText(event.target.value)} spellCheck={false} /></label>
              <button type="button" onClick={() => run('Previewing parser', async () => setPreviewAlert(await api.parsePreview(previewText)))}><MessageSquare size={15} /> Preview</button>
              <pre className="json-preview short">{previewAlert ? JSON.stringify(previewAlert, null, 2) : 'No preview yet'}</pre>
            </div>
          ) : <EmptyState label="Recorder settings are loading." />}
        </section>
        <section className="glass-panel panel-card span-4">
          <PanelHeader icon={<Database size={18} />} title="Recorder Imports / Exports" subtitle="Discord alerts, options prices, stock prices, and joined exports." />
          <div className="stack">
            <label className="field">Discord alert CSV <textarea className="compact-textarea" value={discordCsvText} onChange={(event) => setDiscordCsvText(event.target.value)} spellCheck={false} /></label>
            <button type="button" onClick={() => run('Importing Discord CSV', () => api.importDiscordCsv(discordCsvText))}><Upload size={15} /> Import Alerts</button>
            <label className="field">Option price CSV <textarea className="compact-textarea" value={optionsCsvText} onChange={(event) => setOptionsCsvText(event.target.value)} spellCheck={false} /></label>
            <button type="button" onClick={() => run('Importing option prices', () => api.importOptionsCsv(optionsCsvText))}><Database size={15} /> Import Options</button>
            <label className="field">Stock price CSV <textarea className="compact-textarea" value={stocksCsvText} onChange={(event) => setStocksCsvText(event.target.value)} spellCheck={false} /></label>
            <button type="button" onClick={() => run('Importing stock prices', () => api.importStocksCsv(stocksCsvText))}><Database size={15} /> Import Stocks</button>
            <label className="field">Export channels <textarea className="compact-textarea channel-filter" value={exportChannelIdsText} onChange={(event) => setExportChannelIdsText(event.target.value)} placeholder="Blank exports all channels" spellCheck={false} /></label>
            <label className="field">Export type <select value={exportType} onChange={(event) => setExportType(event.target.value as 'alerts' | 'joined')}><option value="joined">joined</option><option value="alerts">alerts</option></select></label>
            <button className="primary-btn" type="button" onClick={() => run('Exporting alerts', () => api.exportRecordings(exportChannelIds, exportType))}><Download size={15} /> Export</button>
            <p className="path-readout">{latestExport ? latestExport.file_path : 'No exports yet'}</p>
          </div>
        </section>
        <section className="glass-panel panel-card span-4">
          <PanelHeader icon={<PlugZap size={18} />} title="Sentinel Echo Replay" subtitle="Replay event stream and JSONL test-run manifest." />
          <div className="stack">
            <label className="field">Replay channels <textarea className="compact-textarea channel-filter" value={sentinelEchoChannelIdsText} onChange={(event) => setSentinelEchoChannelIdsText(event.target.value)} placeholder="Blank replays all channels" spellCheck={false} /></label>
            <ChannelChips ids={sentinelEchoChannelIds} emptyLabel="Replay scope: all channels" />
            <label className="field">Since <input value={sentinelEchoSince} onChange={(event) => setSentinelEchoSince(event.target.value)} placeholder="2026-06-19T14:30:00+00:00" /></label>
            <div className="button-row"><button type="button" onClick={() => run('Loading Sentinel Echo replay', async () => setSentinelEchoReplay(await api.sentinelEchoReplayEvents(sentinelEchoChannelIds, sentinelEchoSince, 100)))}><RotateCcw size={15} /> Events</button><button className="primary-btn" type="button" onClick={() => run('Writing Sentinel Echo test run', async () => setSentinelEchoTestRun(await api.createSentinelEchoTestRun('Sentinel Echo UI test', sentinelEchoChannelIds, sentinelEchoSince, 1000)))}><Download size={15} /> JSONL</button></div>
            <div className="recorder-status"><Badge tone={sentinelEchoReplay?.event_count ? 'good' : 'neutral'} label={`${sentinelEchoReplay ? number(sentinelEchoReplay.event_count, 0) : '0'} events`} /><span>{sentinelEchoReplay?.contract_version || 'simulation.sentinel-echo.replay.v1'}</span></div>
            <p className="path-readout">{sentinelEchoReplayUrl}</p>
            <p className="path-readout">{sentinelEchoTestRun ? sentinelEchoTestRun.file_path : 'No test run yet'}</p>
            <pre className="json-preview">{sentinelEchoReplay?.events[0] ? JSON.stringify(sentinelEchoReplay.events[0], null, 2) : 'No replay event loaded'}</pre>
          </div>
        </section>
        <section className="glass-panel panel-card span-6">
          <PanelHeader icon={<Banknote size={18} />} title="Positions" subtitle="Current simulated account positions." />
          <PositionsTable positions={positions} />
        </section>
        <section className="glass-panel panel-card span-6">
          <PanelHeader icon={<MessageSquare size={18} />} title="Recorded Alerts" subtitle="Latest parser output and drift flags." />
          <AlertsTable alerts={recorderAlerts} driftByAlert={driftByAlert} />
        </section>
      </div>
    );
  }
}

function Badge({ tone, label }: { tone: Tone; label: string }) {
  return <span className={`badge ${tone}`}>{label}</span>;
}

function PanelHeader({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle?: string }) {
  return (
    <header className="panel-header">
      <div>{icon}<h2>{title}</h2></div>
      {subtitle ? <p>{subtitle}</p> : null}
    </header>
  );
}

function Ticker({ label, value, sub, tone = 'neutral' }: { label: string; value: string; sub: string; tone?: Tone }) {
  return <article className={`ticker ${tone}`}><b>{label}</b><strong>{value}</strong><span>{sub}</span></article>;
}

function ChannelChips({ ids, emptyLabel }: { ids: string[]; emptyLabel: string }) {
  const clean = ids.map((item) => item.trim()).filter(Boolean);
  return (
    <div className="channel-chip-row">
      {clean.length ? clean.map((id) => <span className="channel-chip" key={id}>{id === '*' ? 'all channels' : id}</span>) : <span className="channel-empty">{emptyLabel}</span>}
    </div>
  );
}

function NumberField({ label, value, step = 1, onChange }: { label: string; value: number; step?: number; onChange: (value: number) => void }) {
  return (
    <label className="field">
      {label}
      <input type="number" value={Number.isFinite(value) ? value : 0} step={step} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function EmptyState({ label }: { label: string }) {
  return <div className="empty-state">{label}</div>;
}

function ReportKpis({ report }: { report: BacktestReport }) {
  const metrics = report.metrics;
  return (
    <div className="kpi-ribbon">
      <article className={`kpi-card ${metrics.safety_score >= 70 ? 'good' : 'warn'}`}><span>Safety Score</span><strong>{number(metrics.safety_score, 0)}</strong><em>{metrics.safety_flags.join(', ') || 'clear'}</em></article>
      <article className={metrics.total_pnl >= 0 ? 'kpi-card good' : 'kpi-card bad'}><span>Total PnL</span><strong>{money(metrics.total_pnl)}</strong><em>{pct(metrics.total_return_pct)}</em></article>
      <article className="kpi-card purple"><span>Win Rate</span><strong>{pct(metrics.win_rate * 100, 0)}</strong><em>{number(metrics.trade_count, 0)} trades</em></article>
      <article className="kpi-card"><span>Drawdown</span><strong>{pct(metrics.max_drawdown_pct)}</strong><em>MAE {money(metrics.mae)}</em></article>
      <article className="kpi-card gold"><span>Costs</span><strong>{money(metrics.total_fees + metrics.slippage + metrics.funding)}</strong><em>fees/slip/funding</em></article>
    </div>
  );
}

function Warnings({ warnings }: { warnings: string[] }) {
  const unique = [...new Set(warnings.filter(Boolean))];
  if (!unique.length) return <div className="assumption-row"><Badge tone="good" label="No warnings or safety flags" /></div>;
  return <div className="assumption-row">{unique.map((warning) => <Badge tone="warn" label={warning} key={warning} />)}</div>;
}

function TradeTable({ trades }: { trades: BacktestTrade[] }) {
  return (
    <div className="trade-table">
      <div className="trade-row head"><span>Symbol</span><span>Side</span><span>Qty</span><span>Entry</span><span>Exit</span><span>PnL</span><span>MAE</span><span>MFE</span><span>Reason</span></div>
      {trades.length ? trades.map((trade, index) => (
        <div className="trade-row" key={`${trade.symbol}-${trade.entry_time}-${index}`}>
          <span>{trade.symbol}</span><span>{trade.side}</span><span>{number(trade.quantity)}</span><span>{money(trade.entry_price)}</span><span>{money(trade.exit_price)}</span><span className={trade.pnl >= 0 ? 'good' : 'bad'}>{money(trade.pnl)}</span><span>{money(trade.mae)}</span><span>{money(trade.mfe)}</span><span>{trade.exit_reason}</span>
        </div>
      )) : <EmptyState label="No trades were generated." />}
    </div>
  );
}

function RunHistoryTable({ runs, selectedRunId, onSelect }: { runs: BacktestRunRecord[]; selectedRunId?: string; onSelect: (record: BacktestRunRecord) => void }) {
  return (
    <div className="history-table">
      <div className="history-row head"><span>Created</span><span>Kind</span><span>Asset</span><span>Symbol</span><span>Safety</span><span>PnL</span><span>Trades</span><span>Run ID</span></div>
      {runs.length ? runs.map((run) => (
        <button className={`history-row ${run.run_id === selectedRunId ? 'selected' : ''}`} type="button" key={run.run_id} onClick={() => onSelect(run)}>
          <span>{formatWhen(run.created_at)}</span><span>{run.kind}</span><span>{run.asset_class}</span><span>{run.symbol}</span><span className={run.report.metrics.safety_score >= 70 ? 'good' : 'warn'}>{number(run.report.metrics.safety_score, 0)}</span><span className={run.report.metrics.total_pnl >= 0 ? 'good' : 'bad'}>{money(run.report.metrics.total_pnl)}</span><span>{number(run.report.metrics.trade_count, 0)}</span><span>{run.run_id}</span>
        </button>
      )) : <EmptyState label="No runs matched the filters." />}
    </div>
  );
}

function SuiteJobs({ jobs }: { jobs: SuiteJob[] }) {
  return (
    <div className="job-table">
      <div className="job-row head"><span>Bot</span><span>Family</span><span>Status</span><span>Repo / Evidence</span></div>
      {jobs.length ? jobs.map((job) => (
        <div className="job-row" key={job.job_id}>
          <span>{job.bot_id}</span><span>{job.test_family}</span><span className={job.status === 'passed' ? 'good' : job.status === 'skipped' ? 'warn' : ''}>{job.status}</span><span>{job.skipped_reason || String(job.evidence?.message ?? job.repo_path ?? 'planned')}</span>
        </div>
      )) : <EmptyState label="No jobs selected." />}
    </div>
  );
}

function PositionsTable({ positions }: { positions: Array<{ symbol: string; quantity: number; avg_entry: number; current_price: number; pnl: number; pnl_pct: number; trailing_enabled: boolean; trailing_percent?: number | null }> }) {
  return (
    <div className="positions-table">
      <div className="position-row head"><span>Symbol</span><span>Qty</span><span>Entry</span><span>Price</span><span>PnL</span><span>Trail</span></div>
      {positions.length ? positions.map((position) => (
        <div className="position-row" key={position.symbol}>
          <span>{position.symbol}</span><span>{number(position.quantity)}</span><span>{money(position.avg_entry)}</span><span>{money(position.current_price)}</span><span className={position.pnl >= 0 ? 'good' : 'bad'}>{money(position.pnl)} / {number(position.pnl_pct)}%</span><span>{position.trailing_enabled ? `${position.trailing_percent}%` : 'Off'}</span>
        </div>
      )) : <EmptyState label="No positions." />}
    </div>
  );
}

function AlertsTable({ alerts, driftByAlert }: { alerts: ParsedAlert[]; driftByAlert: Map<string, PriceDriftEvent> }) {
  return (
    <div className="alerts-table">
      <div className="alert-row head"><span>Status</span><span>Action</span><span>Contract</span><span>Alert</span><span>Market</span><span>Drift</span></div>
      {alerts.length ? alerts.slice(0, 12).map((alert) => {
        const drift = driftByAlert.get(alert.message_id);
        const contract = [alert.ticker, alert.expiration, alert.strike, alert.option_type].filter(Boolean).join(' ');
        return (
          <div className="alert-row" key={alert.message_id}>
            <span className={alert.parse_status === 'parsed' ? 'good' : 'bad'}>{alert.parse_status}</span><span>{alert.action || 'capture'}</span><span>{contract || 'Unparsed'}</span><span>{money(alert.alert_price)}</span><span>{money(drift?.market_price)}</span><span className={drift?.price_drift_alert ? 'bad' : 'good'}>{drift ? `${number(drift.price_drift_amount)} / ${number(drift.price_drift_pct)}%` : '—'}</span>
          </div>
        );
      }) : <EmptyState label="No recorded alerts." />}
    </div>
  );
}
