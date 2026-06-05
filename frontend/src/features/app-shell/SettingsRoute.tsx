"use client";

import { SettingsPage } from "@/features/app-shell/SettingsPage";
import {
  useAlertRulesQuery,
  useCreateAlertRuleMutation,
  useCreateExchangeConnectionMutation,
  useDeleteAlertRuleMutation,
  useDeleteExchangeConnectionMutation,
  useExchangeConnectionAccountSnapshotsQuery,
  useExchangeConnectionWalletBalancesQuery,
  useExchangeConnectionsQuery,
  useMarketPairsQuery,
  useRadarConfigQuery,
  useRefreshExchangeConnectionBalanceMutation,
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
  const exchangeConnectionIds = (exchangeConnectionsQuery.data ?? [])
    .filter((connection) => connection.status !== "deleted" && connection.status !== "revoked")
    .map((connection) => connection.id);
  const exchangeWalletBalancesQuery = useExchangeConnectionWalletBalancesQuery(exchangeConnectionIds);
  const exchangeAccountSnapshotsQuery = useExchangeConnectionAccountSnapshotsQuery(exchangeConnectionIds);
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
  const refreshExchangeConnectionBalanceMutation = useRefreshExchangeConnectionBalanceMutation();
  const updateUserSettingsMutation = useUpdateUserSettingsMutation();
  const updateStrategyConfigMutation = useUpdateStrategyConfigMutation();

  return (
    <SettingsPage
      config={configQuery.data ?? null}
      availablePairs={marketPairsQuery.data ?? []}
      strategyConfigs={strategyConfigsQuery.data ?? []}
      alertRules={alertRulesQuery.data ?? []}
      exchangeConnections={exchangeConnectionsQuery.data ?? []}
      exchangeAccountSnapshots={exchangeAccountSnapshotsQuery.dataByConnectionId}
      exchangeBalanceLoading={mergePendingByConnectionId(
        exchangeWalletBalancesQuery.pendingByConnectionId,
        exchangeAccountSnapshotsQuery.pendingByConnectionId,
        refreshExchangeConnectionBalanceMutation.isPending
          ? refreshExchangeConnectionBalanceMutation.variables
          : null
      )}
      exchangeWalletBalances={exchangeWalletBalancesQuery.dataByConnectionId}
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
        refreshExchangeConnectionBalanceMutation.isPending ||
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
      onRefreshExchangeBalance={(connectionId) => refreshExchangeConnectionBalanceMutation.mutateAsync(connectionId)}
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

function mergePendingByConnectionId(
  walletPending: Record<string, boolean>,
  snapshotPending: Record<string, boolean>,
  refreshingConnectionId: string | null
): Record<string, boolean> {
  const connectionIds = new Set([
    ...Object.keys(walletPending),
    ...Object.keys(snapshotPending),
    ...(refreshingConnectionId ? [refreshingConnectionId] : [])
  ]);
  return Object.fromEntries(
    Array.from(connectionIds).map((connectionId) => [
      connectionId,
      Boolean(walletPending[connectionId] || snapshotPending[connectionId] || refreshingConnectionId === connectionId)
    ])
  );
}
