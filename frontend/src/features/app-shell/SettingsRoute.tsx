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
  useSyncExchangeConnectionMutation,
  useTestAlertRuleMutation,
  useTestExchangeConnectionMutation,
  useUpdateExchangeConnectionMutation,
  useUpdateAlertRuleMutation
} from "@/hooks/use-radar-queries";
import type { AlertRuleDraft, ExchangeConnectionDraft } from "@/features/server-state/types";

export function SettingsRoute() {
  const configQuery = useRadarConfigQuery();
  const marketPairsQuery = useMarketPairsQuery();
  const alertRulesQuery = useAlertRulesQuery();
  const exchangeConnectionsQuery = useExchangeConnectionsQuery();
  const createAlertRuleMutation = useCreateAlertRuleMutation();
  const updateAlertRuleMutation = useUpdateAlertRuleMutation();
  const deleteAlertRuleMutation = useDeleteAlertRuleMutation();
  const testAlertRuleMutation = useTestAlertRuleMutation();
  const createExchangeConnectionMutation = useCreateExchangeConnectionMutation();
  const updateExchangeConnectionMutation = useUpdateExchangeConnectionMutation();
  const deleteExchangeConnectionMutation = useDeleteExchangeConnectionMutation();
  const testExchangeConnectionMutation = useTestExchangeConnectionMutation();
  const syncExchangeConnectionMutation = useSyncExchangeConnectionMutation();

  return (
    <SettingsPage
      config={configQuery.data ?? null}
      availablePairs={marketPairsQuery.data ?? []}
      alertRules={alertRulesQuery.data ?? []}
      exchangeConnections={exchangeConnectionsQuery.data ?? []}
      busy={
        createAlertRuleMutation.isPending ||
        updateAlertRuleMutation.isPending ||
        deleteAlertRuleMutation.isPending ||
        testAlertRuleMutation.isPending ||
        createExchangeConnectionMutation.isPending ||
        updateExchangeConnectionMutation.isPending ||
        deleteExchangeConnectionMutation.isPending ||
        testExchangeConnectionMutation.isPending ||
        syncExchangeConnectionMutation.isPending
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
    />
  );
}
