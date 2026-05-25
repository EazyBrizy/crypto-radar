import { Bell, Radio, Shield } from "lucide-react";

import { Badge } from "../components/Badge";
import type { RadarConfig } from "../types";

interface SettingsPageProps {
  config: RadarConfig | null;
}

export function SettingsPage({ config }: SettingsPageProps) {
  return (
    <section className="wide-panel">
      <div className="page-head">
        <div>
          <span className="muted">Settings</span>
          <h1>Настройки радара</h1>
        </div>
      </div>

      <div className="settings-grid">
        <div className="settings-section">
          <div className="section-title"><Radio size={18} /><h3>Exchanges</h3></div>
          <div className="chip-cloud">
            {(config?.exchanges ?? ["bybit"]).map((exchange) => <Badge tone="blue" key={exchange}>{exchange}</Badge>)}
            <Badge>Binance later</Badge>
            <Badge>OKX later</Badge>
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
          <div className="section-title"><Bell size={18} /><h3>Notifications</h3></div>
          <label className="toggle-row"><input type="checkbox" defaultChecked /><span>High confidence signals</span></label>
          <label className="toggle-row"><input type="checkbox" defaultChecked /><span>Risk warnings</span></label>
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
