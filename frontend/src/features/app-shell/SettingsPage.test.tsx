import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/api";
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
  MarketUniversePair,
  StrategyConfig,
  StrategyConfigPatch,
  UserProfile,
  UserSettingsPatch,
  VirtualSimulationLevel
} from "@/features/server-state/types";
import type { RadarConfig } from "@/types";
import { SettingsPage } from "./SettingsPage";

vi.mock("@/api", () => ({
  api: {
    marketUniversePairs: vi.fn(),
    syncMarketUniverse: vi.fn()
  }
}));

beforeEach(() => {
  vi.mocked(api.marketUniversePairs).mockReset();
  vi.mocked(api.syncMarketUniverse).mockReset();
  vi.mocked(api.marketUniversePairs).mockResolvedValue([
    marketUniversePair({ id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaa1", symbol: "BTCUSDT", tier: "high", rank: 1 }),
    marketUniversePair({ id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaa2", symbol: "DOGEUSDT", tier: "low", rank: 2 })
  ]);
  vi.mocked(api.syncMarketUniverse).mockResolvedValue({
    category: "linear",
    exchange: "bybit",
    quote: "USDT",
    requested_limit: "top_100",
    skipped_count: 0,
    synced_at: "2026-06-04T00:00:00.000Z",
    synced_count: 2,
    total_available_count: 2,
    warnings: []
  });
});

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

    await user.click(screen.getByRole("button", { name: "Refresh balance" }));

    expect(onRefreshExchangeBalance).toHaveBeenCalledWith(EXCHANGE_CONNECTION_ID);
  });
});

describe("SettingsPage exchange connection delete UX", () => {
  it("opens a confirmation modal before deleting an exchange connection", async () => {
    const user = userEvent.setup();
    const onDeleteExchangeConnection = vi.fn<SettingsPagePropsForTest["onDeleteExchangeConnection"]>().mockResolvedValue(null);

    renderSettingsPage({
      exchangeConnections: [exchangeConnection()],
      onDeleteExchangeConnection
    });

    await user.click(screen.getByRole("button", { name: /Exchanges/u }));
    await user.click(screen.getByRole("button", { name: "Delete Main Bybit" }));

    expect(screen.getByRole("dialog", { name: /Delete exchange connection/u })).toBeInTheDocument();
    expect(onDeleteExchangeConnection).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Delete exchange connection?" }));

    expect(onDeleteExchangeConnection).toHaveBeenCalledWith(EXCHANGE_CONNECTION_ID);
  });

  it("shows a localized delete reason when the backend rejects deletion", async () => {
    const user = userEvent.setup();
    const onDeleteExchangeConnection = vi.fn<SettingsPagePropsForTest["onDeleteExchangeConnection"]>()
      .mockRejectedValue(new Error("Exchange connection not found: missing"));

    renderSettingsPage({
      exchangeConnections: [exchangeConnection()],
      onDeleteExchangeConnection
    });

    await user.click(screen.getByRole("button", { name: /Exchanges/u }));
    await user.click(screen.getByRole("button", { name: "Delete Main Bybit" }));
    await user.click(screen.getByRole("button", { name: "Delete exchange connection?" }));

    expect(await screen.findByText("Exchange connection is not found.")).toBeInTheDocument();
  });

  it("does not render deleted exchange connections in the active list", async () => {
    const user = userEvent.setup();

    renderSettingsPage({
      exchangeConnections: [exchangeConnection({ status: "deleted" })]
    });

    await user.click(screen.getByRole("button", { name: /Exchanges/u }));

    expect(screen.queryByText("Main Bybit")).not.toBeInTheDocument();
    expect(screen.getByText("No exchange connections")).toBeInTheDocument();
  });
});

describe("SettingsPage strategy pair selector", () => {
  it("renders pair selector for an opened strategy config", async () => {
    const user = userEvent.setup();
    renderSettingsPage({ strategyConfigs: [strategyConfig()] });

    await openStrategySettings(user);

    expect(screen.getByText("Strategy trading pairs")).toBeInTheDocument();
    expect(await screen.findByText("BTCUSDT")).toBeInTheDocument();
    expect(screen.getAllByText("All pairs from scanner universe").length).toBeGreaterThan(0);
  });

  it("sync button calls market universe sync mutation", async () => {
    const user = userEvent.setup();
    renderSettingsPage({ strategyConfigs: [strategyConfig()] });

    await openStrategySettings(user);
    await user.click(screen.getByRole("button", { name: "Sync pairs from exchange" }));

    await waitFor(() => {
      expect(api.syncMarketUniverse).toHaveBeenCalledWith({
        category: "linear",
        exchange: "bybit",
        limit: "top_100",
        persist: true,
        quote: "USDT",
        sort: "turnover_24h_desc"
      });
    });
  });

  it("selecting pairs updates the draft state and shows low-liquidity warning", async () => {
    const user = userEvent.setup();
    renderSettingsPage({ strategyConfigs: [strategyConfig()] });

    await openStrategySettings(user);
    await user.click(await screen.findByRole("checkbox", { name: "Select pair DOGEUSDT" }));

    expect(screen.getAllByText("1 pairs selected").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/DOGEUSDT/u).length).toBeGreaterThan(0);
    expect(screen.getByText(/low-liquidity/u)).toBeInTheDocument();
  });

  it("saving strategy sends selected pairs payload", async () => {
    const user = userEvent.setup();
    const onUpdateStrategyConfig = vi.fn<SettingsPagePropsForTest["onUpdateStrategyConfig"]>().mockResolvedValue(null);
    renderSettingsPage({ onUpdateStrategyConfig, strategyConfigs: [strategyConfig()] });

    await openStrategySettings(user);
    await user.click(await screen.findByRole("checkbox", { name: "Select pair BTCUSDT" }));
    await user.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      expect(onUpdateStrategyConfig).toHaveBeenCalledWith(
        STRATEGY_CONFIG_ID,
        expect.objectContaining({
          pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }]
        })
      );
    });
  });

  it("clearing selected pairs sends empty pairs array for scanner-universe semantics", async () => {
    const user = userEvent.setup();
    const onUpdateStrategyConfig = vi.fn<SettingsPagePropsForTest["onUpdateStrategyConfig"]>().mockResolvedValue(null);
    renderSettingsPage({
      onUpdateStrategyConfig,
      strategyConfigs: [
        strategyConfig({ pairs: [{ exchange: "bybit", symbol: "BTCUSDT" }] })
      ]
    });

    await openStrategySettings(user);
    await user.click(screen.getByRole("button", { name: "Clear" }));
    await user.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      expect(onUpdateStrategyConfig).toHaveBeenCalledWith(
        STRATEGY_CONFIG_ID,
        expect.objectContaining({ pairs: [] })
      );
    });
  });
});

async function openRiskSettings(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Risk management/u }));
}

async function openStrategySettings(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Strategies/u }));
  await user.click(screen.getByRole("button", { name: /Trend Pullback/u }));
}

const EXCHANGE_CONNECTION_ID = "bbbbbbbb-bbbb-4bbb-bbbb-bbbbbbbbbbbb";
const STRATEGY_CONFIG_ID = "cccccccc-cccc-4ccc-cccc-cccccccccccc";

type RenderSettingsPageOptions = {
  exchangeAccountSnapshots?: Record<string, AccountRiskSnapshot | null>;
  exchangeBalanceLoading?: Record<string, boolean>;
  exchangeConnections?: ExchangeConnection[];
  exchangeWalletBalances?: Record<string, ExchangeWalletBalance | null>;
  onDeleteExchangeConnection?: SettingsPagePropsForTest["onDeleteExchangeConnection"];
  onRefreshExchangeBalance?: SettingsPagePropsForTest["onRefreshExchangeBalance"];
  onUpdateStrategyConfig?: SettingsPagePropsForTest["onUpdateStrategyConfig"];
  strategyConfigs?: StrategyConfig[];
};

function renderSettingsPage(options: RenderSettingsPageOptions = {}) {
  const onUpdateRiskManagement = vi.fn<SettingsPagePropsForTest["onUpdateRiskManagement"]>().mockResolvedValue(null);
  const onUpdateStrategyConfig =
    options.onUpdateStrategyConfig ??
    vi.fn<SettingsPagePropsForTest["onUpdateStrategyConfig"]>().mockResolvedValue(null);
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false }
    }
  });

  render(
    <QueryClientProvider client={queryClient}>
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
        strategyConfigs={options.strategyConfigs ?? []}
        userProfile={userProfile()}
        onCreateAlert={vi.fn<SettingsPagePropsForTest["onCreateAlert"]>().mockResolvedValue(null)}
        onCreateExchangeConnection={vi.fn<SettingsPagePropsForTest["onCreateExchangeConnection"]>().mockResolvedValue(null)}
        onDeleteAlert={vi.fn<SettingsPagePropsForTest["onDeleteAlert"]>().mockResolvedValue(null)}
        onDeleteExchangeConnection={options.onDeleteExchangeConnection ?? vi.fn<SettingsPagePropsForTest["onDeleteExchangeConnection"]>().mockResolvedValue(null)}
        onRefreshExchangeBalance={options.onRefreshExchangeBalance ?? vi.fn<SettingsPagePropsForTest["onRefreshExchangeBalance"]>().mockResolvedValue(null)}
        onSelectSimulationLevel={vi.fn<SettingsPagePropsForTest["onSelectSimulationLevel"]>().mockResolvedValue(null)}
        onSyncExchangeConnection={vi.fn<SettingsPagePropsForTest["onSyncExchangeConnection"]>().mockResolvedValue(null)}
        onTestAlert={vi.fn<SettingsPagePropsForTest["onTestAlert"]>().mockResolvedValue(null)}
        onTestExchangeConnection={vi.fn<SettingsPagePropsForTest["onTestExchangeConnection"]>().mockResolvedValue(null)}
        onToggleAlert={vi.fn<SettingsPagePropsForTest["onToggleAlert"]>().mockResolvedValue(null)}
        onToggleExchangeConnection={vi.fn<SettingsPagePropsForTest["onToggleExchangeConnection"]>().mockResolvedValue(null)}
        onUpdateExchangeConnection={vi.fn<SettingsPagePropsForTest["onUpdateExchangeConnection"]>().mockResolvedValue(null)}
        onUpdateRiskManagement={onUpdateRiskManagement}
        onUpdateStrategyConfig={onUpdateStrategyConfig}
      />
    </QueryClientProvider>
  );

  return { onUpdateRiskManagement, onUpdateStrategyConfig };
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
  onUpdateExchangeConnection: (connectionId: string, patch: Partial<ExchangeConnectionDraft> & { status?: string }) => Promise<unknown>;
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

function strategyConfig(overrides: Partial<Pick<StrategyConfig, "pairs">> = {}): StrategyConfig {
  return {
    created_at: "2026-06-04T00:00:00.000Z",
    exchanges: ["bybit"],
    id: STRATEGY_CONFIG_ID,
    is_enabled: true,
    name: "Trend Pullback",
    pairs: overrides.pairs ?? [],
    params: {
      max_spread_bps: 25,
      min_24h_volume_quote: 10_000_000,
      min_history: 50
    },
    risk_settings: {
      fixed_risk_currency: "USDT",
      radar_display_mode: "all_market_opportunities",
      risk_mode: "percent",
      risk_percent: 1,
      rr_guard_mode: "soft"
    },
    strategy_code: "trend_pullback_continuation",
    strategy_name: "Trend Pullback",
    strategy_version: "1.0",
    strategy_version_id: "dddddddd-dddd-4ddd-dddd-dddddddddddd",
    timeframes: ["15m"],
    updated_at: "2026-06-04T00:00:00.000Z",
    user_id: "demo_user"
  };
}

function marketUniversePair({
  id,
  rank,
  symbol,
  tier
}: {
  id: string;
  rank: number;
  symbol: string;
  tier: string;
}): MarketUniversePair {
  return {
    ask_price: "100.1",
    base_asset: symbol.replace(/USDT$/u, ""),
    bid_price: "99.9",
    category: "linear",
    exchange: "bybit",
    funding_rate: "0.0001",
    id,
    last_price: "100",
    liquidity_rank: rank,
    liquidity_tier: tier,
    market_type: "perpetual",
    mark_price: "100",
    quote_asset: "USDT",
    spread_bps: tier === "low" ? "35" : "5",
    status: "active",
    symbol,
    synced_at: "2026-06-04T00:00:00.000Z",
    turnover_24h: tier === "low" ? "1000000" : "150000000",
    volume_24h: "1000"
  };
}

function exchangeConnection(overrides: Partial<ExchangeConnection> = {}): ExchangeConnection {
  return {
    account_type: "linear",
    created_at: "2026-06-04T00:00:00.000Z",
    deleted_at: null,
    deletion_reason: null,
    exchange_code: "bybit",
    exchange_id: "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa",
    exchange_name: "Bybit",
    id: EXCHANGE_CONNECTION_ID,
    key_ref: "vault://stub/exchange/demo/bybit/main/abcdef123456",
    label: "Main Bybit",
    last_sync_at: null,
    last_account_snapshot_at: null,
    metadata: {},
    environment: "testnet",
    order_placement_mode: "dry_run",
    can_place_orders: false,
    safety_blockers: ["ORDER_PLACEMENT_DRY_RUN"],
    mainnet_explicitly_enabled: false,
    account_snapshot_status: "missing",
    permissions: { read: true, trade: false },
    revoked_at: null,
    status: "active",
    user_id: "demo_user",
    ...overrides
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
