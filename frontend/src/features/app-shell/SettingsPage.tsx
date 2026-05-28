import { Bell, Gauge, KeyRound, Radio, RefreshCw, Send, Shield, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/Badge";
import type {
  AlertRule,
  AlertRuleDraft,
  ExchangeConnection,
  ExchangeConnectionDraft,
  MarketPairOption,
  UserProfile,
  VirtualSimulationLevel
} from "@/features/server-state/types";
import type { RadarConfig } from "@/types";

interface SettingsPageProps {
  config: RadarConfig | null;
  availablePairs: MarketPairOption[];
  alertRules: AlertRule[];
  exchangeConnections: ExchangeConnection[];
  userProfile: UserProfile | null;
  busy: boolean;
  onCreateAlert: (draft: AlertRuleDraft) => Promise<unknown>;
  onToggleAlert: (alertId: string, isEnabled: boolean) => Promise<unknown>;
  onDeleteAlert: (alertId: string) => Promise<unknown>;
  onTestAlert: (alertId: string) => Promise<unknown>;
  onCreateExchangeConnection: (draft: ExchangeConnectionDraft) => Promise<unknown>;
  onToggleExchangeConnection: (connectionId: string, isActive: boolean) => Promise<unknown>;
  onDeleteExchangeConnection: (connectionId: string) => Promise<unknown>;
  onTestExchangeConnection: (connectionId: string) => Promise<unknown>;
  onSyncExchangeConnection: (connectionId: string) => Promise<unknown>;
  onSelectSimulationLevel: (simulationLevel: VirtualSimulationLevel) => Promise<unknown>;
}

const SIMULATION_LEVELS: Array<{
  value: VirtualSimulationLevel;
  label: string;
  caption: string;
  status: "active" | "stub";
}> = [
  {
    value: "mvp",
    label: "MVP",
    caption: "Depth, spread, slippage",
    status: "active"
  },
  {
    value: "advanced",
    label: "Advanced",
    caption: "Queue, fees, liquidity",
    status: "stub"
  },
  {
    value: "pro",
    label: "Pro",
    caption: "Replay, Monte Carlo",
    status: "stub"
  }
];

export function SettingsPage({
  config,
  availablePairs,
  alertRules,
  exchangeConnections,
  userProfile,
  busy,
  onCreateAlert,
  onToggleAlert,
  onDeleteAlert,
  onTestAlert,
  onCreateExchangeConnection,
  onToggleExchangeConnection,
  onDeleteExchangeConnection,
  onTestExchangeConnection,
  onSyncExchangeConnection,
  onSelectSimulationLevel
}: SettingsPageProps) {
  const [pairId, setPairId] = useState("");
  const [conditionType, setConditionType] = useState("price_above");
  const [targetPrice, setTargetPrice] = useState("");
  const supportedExchanges = config?.exchanges?.length ? config.exchanges : ["bybit"];
  const [exchangeCode, setExchangeCode] = useState(supportedExchanges[0] ?? "bybit");
  const [connectionLabel, setConnectionLabel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [apiPassphrase, setApiPassphrase] = useState("");
  const selectedPair = useMemo(
    () => availablePairs.find((pair) => pair.id === pairId) ?? availablePairs[0] ?? null,
    [availablePairs, pairId]
  );
  const simulationLevel = userProfile?.settings.virtual_trading.simulation_level ?? "mvp";

  async function handleCreateAlert() {
    if (!selectedPair || !targetPrice) return;
    await onCreateAlert({
      pair_id: selectedPair.id,
      condition_type: conditionType,
      condition_body: { price: Number(targetPrice) },
      channels: ["websocket"],
      is_enabled: true
    });
    setTargetPrice("");
  }

  async function handleCreateExchangeConnection() {
    if (!exchangeCode || !connectionLabel || !apiKey || !apiSecret) return;
    await onCreateExchangeConnection({
      exchange_code: exchangeCode,
      label: connectionLabel,
      account_type: "spot",
      api_key: apiKey,
      api_secret: apiSecret,
      api_passphrase: apiPassphrase || null,
      permissions: { read: true, trade: false }
    });
    setConnectionLabel("");
    setApiKey("");
    setApiSecret("");
    setApiPassphrase("");
  }

  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">Settings</span>
          <h1>Radar settings</h1>
        </div>
      </div>

      <div className="settings-grid">
        <div className="settings-section">
          <div className="section-title"><Radio size={18} /><h3>Exchanges</h3></div>
          <div className="inline-form stacked">
            <select
              aria-label="Exchange"
              disabled={busy}
              onChange={(event) => setExchangeCode(event.target.value)}
              value={exchangeCode}
            >
              {supportedExchanges.map((exchange) => (
                <option key={exchange} value={exchange}>{exchange}</option>
              ))}
            </select>
            <input
              aria-label="Connection label"
              disabled={busy}
              onChange={(event) => setConnectionLabel(event.target.value)}
              placeholder="Label"
              value={connectionLabel}
            />
            <input
              aria-label="API key"
              disabled={busy}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="API key"
              value={apiKey}
            />
            <input
              aria-label="API secret"
              disabled={busy}
              onChange={(event) => setApiSecret(event.target.value)}
              placeholder="API secret"
              type="password"
              value={apiSecret}
            />
            <input
              aria-label="API passphrase"
              disabled={busy}
              onChange={(event) => setApiPassphrase(event.target.value)}
              placeholder="Passphrase"
              type="password"
              value={apiPassphrase}
            />
            <button
              className="primary-action"
              disabled={busy || !connectionLabel || !apiKey || !apiSecret}
              onClick={handleCreateExchangeConnection}
              type="button"
            >
              <KeyRound size={16} />
              Connect
            </button>
          </div>
          <div className="connection-list">
            {exchangeConnections.length === 0 ? <div className="empty-state compact-empty">No exchange connections</div> : null}
            {exchangeConnections.map((connection) => (
              <div className="connection-row" key={connection.id}>
                <div>
                  <strong>{connection.label}</strong>
                  <span>{connection.exchange_code}:{connection.account_type}</span>
                  <code>{shortKeyRef(connection.key_ref)}</code>
                </div>
                <Badge tone={connection.status === "active" ? "green" : "red"}>{connection.status}</Badge>
                <label className="toggle-row compact-toggle">
                  <input
                    checked={connection.status === "active"}
                    disabled={busy}
                    onChange={(event) => onToggleExchangeConnection(connection.id, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{connection.status === "active" ? "On" : "Off"}</span>
                </label>
                <button className="icon-button compact" disabled={busy} onClick={() => onTestExchangeConnection(connection.id)} title="Test" type="button">
                  <Send size={15} />
                </button>
                <button className="icon-button compact" disabled={busy} onClick={() => onSyncExchangeConnection(connection.id)} title="Sync" type="button">
                  <RefreshCw size={15} />
                </button>
                <button className="icon-button compact" disabled={busy} onClick={() => onDeleteExchangeConnection(connection.id)} title="Delete" type="button">
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="settings-section">
          <div className="section-title"><Shield size={18} /><h3>Risk Profile</h3></div>
          <div className="segmented">
            <button type="button">Conservative</button>
            <button className="active" type="button">Balanced</button>
            <button type="button">Aggressive</button>
          </div>
        </div>

        <div className="settings-section">
          <div className="section-title"><Gauge size={18} /><h3>Simulation</h3></div>
          <div className="simulation-mode-grid">
            {SIMULATION_LEVELS.map((level) => (
              <button
                className={`simulation-mode-option ${simulationLevel === level.value ? "active" : ""}`}
                disabled={busy}
                key={level.value}
                onClick={() => onSelectSimulationLevel(level.value)}
                type="button"
              >
                <span>
                  <strong>{level.label}</strong>
                  <small>{level.caption}</small>
                </span>
                <Badge tone={level.status === "active" ? "green" : "yellow"}>{level.status}</Badge>
              </button>
            ))}
          </div>
        </div>

        <div className="settings-section alerts-section">
          <div className="section-title"><Bell size={18} /><h3>Alerts</h3></div>
          <div className="inline-form stacked">
            <select
              aria-label="Alert pair"
              disabled={busy || availablePairs.length === 0}
              onChange={(event) => setPairId(event.target.value)}
              value={pairId}
            >
              <option value="">{availablePairs.length ? "Select pair" : "No pairs"}</option>
              {availablePairs.map((pair) => (
                <option key={pair.id} value={pair.id}>{pair.exchange}:{pair.symbol}</option>
              ))}
            </select>
            <select
              aria-label="Alert condition"
              disabled={busy}
              onChange={(event) => setConditionType(event.target.value)}
              value={conditionType}
            >
              <option value="price_above">Price above</option>
              <option value="price_below">Price below</option>
              <option value="signal_generated">Signal generated</option>
            </select>
            <input
              aria-label="Alert price"
              disabled={busy}
              inputMode="decimal"
              onChange={(event) => setTargetPrice(event.target.value)}
              placeholder="Price"
              type="number"
              value={targetPrice}
            />
            <button className="primary-action" disabled={busy || !selectedPair || !targetPrice} onClick={handleCreateAlert} type="button">
              <Bell size={16} />
              Add
            </button>
          </div>

          <div className="alert-list">
            {alertRules.length === 0 ? <div className="empty-state compact-empty">No alert rules</div> : null}
            {alertRules.map((alert) => (
              <div className="alert-row" key={alert.id}>
                <div>
                  <strong>{alert.pair?.symbol ?? "Global"}</strong>
                  <span>{alert.condition_type} {formatCondition(alert.condition_body)}</span>
                </div>
                <label className="toggle-row compact-toggle">
                  <input
                    checked={alert.is_enabled}
                    disabled={busy}
                    onChange={(event) => onToggleAlert(alert.id, event.target.checked)}
                    type="checkbox"
                  />
                  <span>{alert.is_enabled ? "On" : "Off"}</span>
                </label>
                <button className="icon-button compact" disabled={busy} onClick={() => onTestAlert(alert.id)} title="Test" type="button">
                  <Send size={15} />
                </button>
                <button className="icon-button compact" disabled={busy} onClick={() => onDeleteAlert(alert.id)} title="Delete" type="button">
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="settings-section">
          <h3>Timeframes</h3>
          <div className="chip-cloud">
            {(config?.timeframes ?? ["1m", "5m", "15m", "1h", "4h", "1d"]).map((timeframe) => (
              <Badge tone="purple" key={timeframe}>{timeframe}</Badge>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function formatCondition(condition: Record<string, unknown>): string {
  const price = condition.price;
  if (typeof price === "number" || typeof price === "string") return String(price);
  return "";
}

function shortKeyRef(keyRef: string): string {
  const parts = keyRef.split("/");
  const suffix = parts[parts.length - 1] ?? keyRef;
  return `key_ref:${suffix.slice(0, 8)}`;
}
