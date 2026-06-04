import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  RISK_PROFILE_PRESETS,
  cloneRiskManagementSettings,
  riskProfilePreset
} from "@/features/server-state/risk-management-contract";
import type {
  AlertRuleDraft,
  ExchangeConnectionDraft,
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

async function openRiskSettings(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: /Risk management/u }));
}

function renderSettingsPage() {
  const onUpdateRiskManagement = vi.fn<SettingsPagePropsForTest["onUpdateRiskManagement"]>().mockResolvedValue(null);

  render(
    <SettingsPage
      alertRules={[]}
      availablePairs={[]}
      busy={false}
      config={radarConfig()}
      exchangeConnections={[]}
      riskState={null}
      strategyConfigs={[]}
      userProfile={userProfile()}
      onCreateAlert={vi.fn<SettingsPagePropsForTest["onCreateAlert"]>().mockResolvedValue(null)}
      onCreateExchangeConnection={vi.fn<SettingsPagePropsForTest["onCreateExchangeConnection"]>().mockResolvedValue(null)}
      onDeleteAlert={vi.fn<SettingsPagePropsForTest["onDeleteAlert"]>().mockResolvedValue(null)}
      onDeleteExchangeConnection={vi.fn<SettingsPagePropsForTest["onDeleteExchangeConnection"]>().mockResolvedValue(null)}
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
