"use client";

import { SettingsPage } from "@/features/app-shell/SettingsPage";
import {
  useAlertRulesQuery,
  useCreateAlertRuleMutation,
  useCreateExchangeConnectionMutation,
  useDeleteAlertRuleMutation,
  useDeleteExchangeConnectionMutation,
  useExchangeConnectionsQuery,
  useMarketPairsQuery,
  useRadarConfigQuery,
  useRiskStateQuery,
  useStrategyConfigsQuery,
  useSyncExchangeConnectionMutation,
  useTestAlertRuleMutation,
  useTestExchangeConnectionMutation,
  useUpdateExchangeConnectionMutation,
  useUpdateStrategyConfigMutation,
  useUpdateAlertRuleMutation,
  useUpdateUserSettingsMutation,
  useUserProfileQuery
} from "@/hooks/use-radar-queries";
import type {
  AlertRuleDraft,
  ExchangeConnectionDraft,
  UserSettingsPatch,
  StrategyConfigPatch,
  VirtualSimulationLevel
} from "@/features/server-state/types";

export function SettingsRoute() {
  const configQuery = useRadarConfigQuery();
  const marketPairsQuery = useMarketPairsQuery();
  const strategyConfigsQuery = useStrategyConfigsQuery();
  const alertRulesQuery = useAlertRulesQuery();
  const exchangeConnectionsQuery = useExchangeConnectionsQuery();
  const userProfileQuery = useUserProfileQuery({ enabled: true });
  const riskStateQuery = useRiskStateQuery();
  const createAlertRuleMutation = useCreateAlertRuleMutation();
  const updateAlertRuleMutation = useUpdateAlertRuleMutation();
  const deleteAlertRuleMutation = useDeleteAlertRuleMutation();
  const testAlertRuleMutation = useTestAlertRuleMutation();
  const createExchangeConnectionMutation = useCreateExchangeConnectionMutation();
  const updateExchangeConnectionMutation = useUpdateExchangeConnectionMutation();
  const deleteExchangeConnectionMutation = useDeleteExchangeConnectionMutation();
  const testExchangeConnectionMutation = useTestExchangeConnectionMutation();
  const syncExchangeConnectionMutation = useSyncExchangeConnectionMutation();
  const updateUserSettingsMutation = useUpdateUserSettingsMutation();
  const updateStrategyConfigMutation = useUpdateStrategyConfigMutation();

  return (
    <SettingsPage
      config={configQuery.data ?? null}
      availablePairs={marketPairsQuery.data ?? []}
      strategyConfigs={strategyConfigsQuery.data ?? []}
      alertRules={alertRulesQuery.data ?? []}
      exchangeConnections={exchangeConnectionsQuery.data ?? []}
      userProfile={userProfileQuery.data ?? null}
      riskState={riskStateQuery.data ?? null}
      busy={
        createAlertRuleMutation.isPending ||
        updateAlertRuleMutation.isPending ||
        deleteAlertRuleMutation.isPending ||
        testAlertRuleMutation.isPending ||
        createExchangeConnectionMutation.isPending ||
        updateExchangeConnectionMutation.isPending ||
        deleteExchangeConnectionMutation.isPending ||
        testExchangeConnectionMutation.isPending ||
        syncExchangeConnectionMutation.isPending ||
        updateUserSettingsMutation.isPending ||
        updateStrategyConfigMutation.isPending
      }
      onCreateAlert={(draft: AlertRuleDraft) => createAlertRuleMutation.mutateAsync(draft)}
      onToggleAlert={(alertId, isEnabled) =>
        updateAlertRuleMutation.mutateAsync({ alertId, patch: { is_enabled: isEnabled } })
      }
      onDeleteAlert={(alertId) => deleteAlertRuleMutation.mutateAsync(alertId)}
      onTestAlert={(alertId) => testAlertRuleMutation.mutateAsync(alertId)}
      onCreateExchangeConnection={(draft: ExchangeConnectionDraft) => createExchangeConnectionMutation.mutateAsync(draft)}
      onToggleExchangeConnection={(connectionId, isActive) =>
        updateExchangeConnectionMutation.mutateAsync({
          connectionId,
          patch: { status: isActive ? "active" : "disabled" }
        })
      }
      onDeleteExchangeConnection={(connectionId) => deleteExchangeConnectionMutation.mutateAsync(connectionId)}
      onTestExchangeConnection={(connectionId) => testExchangeConnectionMutation.mutateAsync(connectionId)}
      onSyncExchangeConnection={(connectionId) => syncExchangeConnectionMutation.mutateAsync(connectionId)}
      onSelectSimulationLevel={(simulationLevel: VirtualSimulationLevel) =>
        updateUserSettingsMutation.mutateAsync({ virtual_simulation_level: simulationLevel })
      }
      onUpdateRiskManagement={(patch: UserSettingsPatch) =>
        updateUserSettingsMutation.mutateAsync(patch)
      }
      onUpdateStrategyConfig={(configId: string, patch: StrategyConfigPatch) =>
        updateStrategyConfigMutation.mutateAsync({ configId, patch })
      }
    />
  );
}
