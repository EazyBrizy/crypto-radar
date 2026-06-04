import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  RISK_PROFILE_PRESETS,
  cloneRiskManagementSettings,
  riskProfilePreset
} from "@/features/server-state/risk-management-contract";
import type {
  AccountRiskSnapshot,
  AlertRuleDraft,
  ExchangeConnection,
  ExchangeConnectionDraft,
  ExchangeWalletBalance,
  StrategyConfigPatch,
  UserProfile,
  UserSettingsPatch,
  VirtualSimulationLevel
} from "@/features/server-state/types";
import type { RadarConfig } from "@/types";
import { SettingsPage } from "./SettingsPage";

describe("SettingsPage risk profile UX", () => {
  it("switching risk mode changes required fields", async () => {
    const user = userEvent.setup();
    renderSettingsPage();

    await openRiskSettings(user);

    const percentRisk = screen.getByLabelText("Risk / trade");
    const fixedRisk = screen.getByLabelText("Fixed risk");

    expect(percentRisk).toBeRequired();
    expect(fixedRisk).not.toBeRequired();
    expect(fixedRisk).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Fixed" }));

    expect(percentRisk).not.toBeRequired();
    expect(fixedRisk).toBeRequired();
    expect(fixedRisk).toBeEnabled();
    expect(screen.getAllByText("Fixed amount is required when risk mode is Fixed.")).toHaveLength(2);
  });

  it("preset applies expected form values", async () => {
    const user = userEvent.setup();
    const { onUpdateRiskManagement } = renderSettingsPage();

    await openRiskSettings(user);
    await user.click(screen.getByRole("button", { name: /Aggressive/u }));

    expect(screen.getByLabelText("Risk / trade")).toHaveValue(
      RISK_PROFILE_PRESETS.aggressive.risk_per_trade_percent
    );
    expect(screen.getByLabelText("Daily Stop-Loss")).toHaveValue(
      RISK_PROFILE_PRESETS.aggressive.max_daily_loss_percent
    );
    expect(onUpdateRiskManagement).toHaveBeenCalledWith({ risk_profile: "aggressive" });
  });

  it("invalid fixed profile cannot submit", async () => {
    const user = userEvent.setup();
    const { onUpdateRiskManagement } = renderSettingsPage();

    await openRiskSettings(user);
    await user.click(screen.getByRole("button", { name: "Fixed" }));

    const saveButton = screen.getByRole("button", { name: "Save custom" });
    expect(saveButton).toBeDisabled();

    await user.click(saveButton);
    expect(onUpdateRiskManagement).not.toHaveBeenCalled();
  });
});

describe("SettingsPage exchange balance UX", () => {
  it("shows wallet balance, snapshot freshness, warnings, and refresh action", async () => {
    const user = userEvent.setup();
    const onRefreshExchangeBalance = vi.fn<SettingsPagePropsForTest["onRefreshExchangeBalance"]>().mockResolvedValue(null);

    renderSettingsPage({
      exchangeAccountSnapshots: {
        [EXCHANGE_CONNECTION_ID]: accountSnapshot()
      },
      exchangeConnections: [exchangeConnection()],
      exchangeWalletBalances: {
        [EXCHANGE_CONNECTION_ID]: walletBalance()
      },
      onRefreshExchangeBalance
    });

    await user.click(screen.getByRole("button", { name: /Exchanges/u }));

    expect(screen.getByText("$1,234.56")).toBeInTheDocument();
    expect(screen.getByText("$987.65")).toBeInTheDocument();
    expect(screen.getByText("$1,200.00")).toBeInTheDocument();
    expect(screen.getByText("fresh")).toBeInTheDocument();
    expect(screen.getByText(/Snapshot age just now/u)).toBeInTheDocument();
    expect(screen.getByText("Bybit positions are unavailable: timeout")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Обновить баланс" }));

    expect(onRefreshExchangeBalance).toHaveBeenCalledWith(EXCHANGE_CONNECTION_ID);
  });
});

async function openRiskSettings(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Risk management/u }));
}

const EXCHANGE_CONNECTION_ID = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb";

type RenderSettingsPageOptions = {
  exchangeAccountSnapshots?: Record<string, AccountRiskSnapshot | null>;
  exchangeBalanceLoading?: Record<string, boolean>;
  exchangeConnections?: ExchangeConnection[];
  exchangeWalletBalances?: Record<string, ExchangeWalletBalance | null>;
  onRefreshExchangeBalance?: SettingsPagePropsForTest["onRefreshExchangeBalance"];
};

function renderSettingsPage(options: RenderSettingsPageOptions = {}) {
  const onUpdateRiskManagement = vi.fn<SettingsPagePropsForTest["onUpdateRiskManagement"]>().mockResolvedValue(null);

  render(
    <SettingsPage
      alertRules={[]}
      availablePairs={[]}
      busy={false}
      config={radarConfig()}
      exchangeAccountSnapshots={options.exchangeAccountSnapshots ?? {}}
      exchangeBalanceLoading={options.exchangeBalanceLoading ?? {}}
      exchangeConnections={options.exchangeConnections ?? []}
      exchangeWalletBalances={options.exchangeWalletBalances ?? {}}
      riskState={null}
      strategyConfigs={[]}
      userProfile={userProfile()}
      onCreateAlert={vi.fn<SettingsPagePropsForTest["onCreateAlert"]>().mockResolvedValue(null)}
      onCreateExchangeConnection={vi.fn<SettingsPagePropsForTest["onCreateExchangeConnection"]>().mockResolvedValue(null)}
      onDeleteAlert={vi.fn<SettingsPagePropsForTest["onDeleteAlert"]>().mockResolvedValue(null)}
      onDeleteExchangeConnection={vi.fn<SettingsPagePropsForTest["onDeleteExchangeConnection"]>().mockResolvedValue(null)}
      onRefreshExchangeBalance={options.onRefreshExchangeBalance ?? vi.fn<SettingsPagePropsForTest["onRefreshExchangeBalance"]>().mockResolvedValue(null)}
      onSelectSimulationLevel={vi.fn<SettingsPagePropsForTest["onSelectSimulationLevel"]>().mockResolvedValue(null)}
      onSyncExchangeConnection={vi.fn<SettingsPagePropsForTest["onSyncExchangeConnection"]>().mockResolvedValue(null)}
      onTestAlert={vi.fn<SettingsPagePropsForTest["onTestAlert"]>().mockResolvedValue(null)}
      onTestExchangeConnection={vi.fn<SettingsPagePropsForTest["onTestExchangeConnection"]>().mockResolvedValue(null)}
      onToggleAlert={vi.fn<SettingsPagePropsForTest["onToggleAlert"]>().mockResolvedValue(null)}
      onToggleExchangeConnection={vi.fn<SettingsPagePropsForTest["onToggleExchangeConnection"]>().mockResolvedValue(null)}
      onUpdateRiskManagement={onUpdateRiskManagement}
      onUpdateStrategyConfig={vi.fn<SettingsPagePropsForTest["onUpdateStrategyConfig"]>().mockResolvedValue(null)}
    />
  );

  return { onUpdateRiskManagement };
}

type SettingsPagePropsForTest = {
  onCreateAlert: (draft: AlertRuleDraft) => Promise<unknown>;
  onCreateExchangeConnection: (draft: ExchangeConnectionDraft) => Promise<unknown>;
  onDeleteAlert: (alertId: string) => Promise<unknown>;
  onDeleteExchangeConnection: (connectionId: string) => Promise<unknown>;
  onRefreshExchangeBalance: (connectionId: string) => Promise<unknown>;
  onSelectSimulationLevel: (simulationLevel: VirtualSimulationLevel) => Promise<unknown>;
  onSyncExchangeConnection: (connectionId: string) => Promise<unknown>;
  onTestAlert: (alertId: string) => Promise<unknown>;
  onTestExchangeConnection: (connectionId: string) => Promise<unknown>;
  onToggleAlert: (alertId: string, isEnabled: boolean) => Promise<unknown>;
  onToggleExchangeConnection: (connectionId: string, isActive: boolean) => Promise<unknown>;
  onUpdateRiskManagement: (patch: UserSettingsPatch) => Promise<unknown>;
  onUpdateStrategyConfig: (configId: string, patch: StrategyConfigPatch) => Promise<unknown>;
};

function radarConfig(): RadarConfig {
  return {
    exchanges: ["bybit"],
    symbols: [],
    timeframes: ["15m"],
    use_all_symbols: true
  };
}

function exchangeConnection(): ExchangeConnection {
  return {
    account_type: "linear",
    created_at: "2026-06-04T00:00:00.000Z",
    exchange_code: "bybit",
    exchange_id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
    exchange_name: "Bybit",
    id: EXCHANGE_CONNECTION_ID,
    key_ref: "vault://stub/exchange/demo/bybit/main/abcdef123456",
    label: "Main Bybit",
    last_sync_at: null,
    metadata: {},
    permissions: { read: true, trade: false },
    status: "active",
    user_id: "demo_user"
  };
}

function walletBalance(): ExchangeWalletBalance {
  return {
    account_type: "UNIFIED",
    coins: [
      {
        accrued_interest: 0,
        available_to_withdraw: 987.65,
        borrow_amount: 0,
        coin: "USDT",
        equity: 1234.56,
        locked: 0,
        total_order_im: 0,
        total_position_im: 25,
        total_position_mm: 10,
        unrealised_pnl: 12.34,
        usd_value: 1234.56,
        wallet_balance: 1200
      }
    ],
    connection_id: EXCHANGE_CONNECTION_ID,
    exchange: "bybit",
    fetched_at: new Date().toISOString(),
    status: "fresh",
    total_available_balance: 987.65,
    total_equity: 1234.56,
    total_wallet_balance: 1200,
    warnings: []
  };
}

function accountSnapshot(): AccountRiskSnapshot {
  return {
    account_equity: 1234.56,
    available_balance: 987.65,
    fetched_at: new Date().toISOString(),
    maintenance_margin_rate: null,
    margin_mode: "cross",
    open_risk_amount: 0,
    positions: [],
    source: "exchange",
    status: "fresh",
    total_initial_margin: 25,
    total_maintenance_margin: 10,
    wallet_balance: 1200,
    warnings: ["Bybit positions are unavailable: timeout"]
  };
}

function userProfile(): UserProfile {
  return {
    created_at: "2026-06-04T00:00:00.000Z",
    email: "demo@crypto-radar.local",
    id: "demo_user",
    name: "Demo Trader",
    risk_profile: "custom",
    settings: {
      risk_management: cloneRiskManagementSettings(riskProfilePreset("custom")),
      virtual_trading: {
        effective_simulation_level: "mvp",
        simulation_level: "mvp",
        simulation_level_status: "active"
      }
    }
  };
}
