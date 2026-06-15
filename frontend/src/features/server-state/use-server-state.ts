import { type QueryClient, useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api";
import { isActivePendingEntryStatus } from "@/domain/pending-entry-status";
import { isExecutionCandidateStatus } from "@/domain/signal-status";
import type {
  StrategyTestActiveRunResponse,
  StrategyTestCalibrationResponse,
  StrategyTestEstimateResponse,
  StrategyTestFunnelResponse,
  StrategyTestReport,
  StrategyTestRunRequest,
  StrategyTestRunResponse,
  StrategyTestSignalEvent,
  StrategyTestTrade
} from "@/features/strategy-testing/types";
import type {
  AlertRuleDraft,
  AccountRiskSnapshot,
  ExchangeConnectionDraft,
  ExchangeWalletBalance,
  MarketUniversePairsQuery,
  MarketUniverseSyncRequest,
  NotificationDraft,
  RadarDisplayMode,
  StrategyConfigPatch,
  SubscriptionStatus,
  UserProfile
} from "@/features/server-state/types";
import type {
  HealthStatus,
  PendingEntryIntent,
  RadarResponse,
  RadarSignal,
  RadarStatus,
  RiskStateResponse,
  SignalActionMode,
  SignalActionRequest,
  SignalActionResponse,
  SignalActionState,
  TradeJournalResponse
} from "@/types";
import { isOpenFeedSignal } from "@/utils";
import { radarResponseWithSignals } from "./radar-cache";
import {
  queryKeys,
  serverStateKeys,
  type CandleFilters,
  type PendingEntryQueueScope,
  type SignalHistoryFilters,
  type StrategyTestReportFilters,
  type StrategyTestRunFilters,
  type TradeJournalFilters
} from "./query-keys";
import { serverStatePolicy } from "./query-policy";

type PlannedQueryOptions = {
  enabled?: boolean;
  refetchInterval?: number | false;
};

export function useHealthQuery() {
  return useQuery({
    queryKey: serverStateKeys.health(),
    queryFn: api.health,
    refetchInterval: serverStatePolicy.backgroundRefreshMs,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useRadarQuery(radarDisplayMode?: RadarDisplayMode | null, userId?: string | null) {
  return useQuery({
    queryKey: serverStateKeys.radar.dashboard(radarDisplayMode ?? undefined, userId ?? "me"),
    queryFn: () => api.radar({ radarDisplayMode, userId }),
    refetchInterval: serverStatePolicy.reconciliationIntervalMs,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useOpenSignalsQuery() {
  return useQuery({
    queryKey: serverStateKeys.signals.open(),
    queryFn: api.openSignals,
    refetchInterval: serverStatePolicy.reconciliationIntervalMs,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useActiveSignalsQuery() {
  return useQuery({
    queryKey: serverStateKeys.signals.active(),
    queryFn: api.activeSignals,
    refetchInterval: serverStatePolicy.reconciliationIntervalMs,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useSignalExecutionPreviewQuery(signalId: string | null, options: PlannedQueryOptions = {}) {
  return useQuery({
    queryKey: serverStateKeys.signals.executionPreview(signalId ?? "none"),
    queryFn: () => api.executionPreview(signalId as string),
    enabled: options.enabled ?? Boolean(signalId),
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useSignalRealExecutionPreviewQuery(
  signalId: string | null,
  connectionId: string | null,
  options: PlannedQueryOptions = {}
) {
  return useQuery({
    queryKey: serverStateKeys.signals.realExecutionPreview(signalId ?? "none", connectionId ?? "none"),
    queryFn: () => api.realExecutionPreview({
      signalId: signalId as string,
      connectionId: connectionId as string
    }),
    enabled: options.enabled ?? Boolean(signalId && connectionId),
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useSignalActionStateQuery(
  signalId: string | null,
  mode: SignalActionMode = "virtual",
  connectionId?: string | null,
  options: PlannedQueryOptions = {}
) {
  return useQuery<SignalActionState>({
    queryKey: serverStateKeys.signals.actionState(signalId ?? "none", mode, connectionId ?? "none"),
    queryFn: () => api.getSignalActionState(signalId as string, mode, connectionId),
    enabled: options.enabled ?? Boolean(signalId),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function usePendingEntryQuery(signalId: string | null, userId?: string | null, options: PlannedQueryOptions = {}) {
  return useQuery({
    queryKey: serverStateKeys.signals.pendingEntry(signalId ?? "none", userId ?? "me"),
    queryFn: () => api.pendingEntry(signalId as string, userId),
    enabled: options.enabled ?? Boolean(signalId),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function usePendingEntryHistoryQuery(signalId: string | null, userId?: string | null, options: PlannedQueryOptions = {}) {
  return useQuery({
    queryKey: serverStateKeys.signals.pendingEntryHistory(signalId ?? "none", userId ?? "me"),
    queryFn: () => api.pendingEntryHistory(signalId as string, userId),
    enabled: options.enabled ?? Boolean(signalId),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function usePendingEntriesQuery(
  userId?: string | null,
  scope: PendingEntryQueueScope = "active",
  options: PlannedQueryOptions & { limit?: number } = {}
) {
  return useQuery({
    queryKey: serverStateKeys.signals.pendingEntries(scope, userId ?? "me"),
    queryFn: () => api.pendingEntries({ userId, scope, limit: options.limit }),
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function usePendingEntryActionStatesQuery(
  pendingEntries: PendingEntryIntent[],
  options: PlannedQueryOptions = {}
) {
  const actionTargets = uniquePendingActionTargets(pendingEntries);
  const queries = useQueries({
    queries: actionTargets.map((target) => ({
      queryKey: serverStateKeys.signals.actionState(target.signalId, target.mode, target.connectionId ?? "none"),
      queryFn: () => api.getSignalActionState(target.signalId, target.mode, target.connectionId),
      enabled: options.enabled ?? true,
      refetchInterval: options.refetchInterval,
      staleTime: serverStatePolicy.realtimeStaleTimeMs
    }))
  });
  const targetIndexByKey = new Map(actionTargets.map((target, index) => [pendingActionTargetKey(target), index]));
  const dataByIntentId: Record<string, SignalActionState | null> = {};
  const pendingByIntentId: Record<string, boolean> = {};

  for (const intent of pendingEntries) {
    const targetKey = pendingActionTargetKey({
      signalId: intent.signal_id,
      mode: intent.mode,
      connectionId: pendingEntryConnectionId(intent)
    });
    const queryIndex = targetIndexByKey.get(targetKey);
    const query = queryIndex == null ? null : queries[queryIndex];
    dataByIntentId[intent.id] = query?.data ?? null;
    pendingByIntentId[intent.id] = Boolean(query?.isFetching || query?.isLoading || query?.isPending);
  }

  return { dataByIntentId, pendingByIntentId };
}

export function useRadarStatusQuery() {
  return useQuery({
    queryKey: serverStateKeys.radar.status(),
    queryFn: api.radarStatus,
    refetchInterval: serverStatePolicy.backgroundRefreshMs,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useCandlesQuery(filters: CandleFilters, options: PlannedQueryOptions = {}) {
  return useQuery({
    queryKey: serverStateKeys.candles.series(filters),
    queryFn: () => api.candles(filters),
    enabled: options.enabled ?? Boolean(filters.symbol && filters.timeframe),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useSignalsQuery(filters?: SignalHistoryFilters) {
  return useQuery({
    queryKey: serverStateKeys.signals.history(filters),
    queryFn: api.historicalSignals,
    select: (signals) => filterSignals(signals, filters),
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useHistoricalSignalsQuery(filters?: SignalHistoryFilters) {
  return useSignalsQuery(filters);
}

export function useTradesQuery(filters?: TradeJournalFilters, options: PlannedQueryOptions = {}) {
  return useQuery({
    queryKey: serverStateKeys.journal.history(filters),
    queryFn: () => api.journalHistory(filters),
    enabled: options.enabled ?? true,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useJournalHistoryQuery(filters?: TradeJournalFilters) {
  return useTradesQuery(filters);
}

export function useClosedTradesQuery() {
  return useQuery({
    queryKey: serverStateKeys.trades.closed(),
    queryFn: api.closedTrades,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useStrategyTestRuns(filters?: StrategyTestRunFilters, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestRunResponse[]>({
    queryKey: serverStateKeys.strategyTests.runs(filters),
    queryFn: () => api.strategyTests.listRuns(filters),
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useStrategyTestActiveRun(userId?: string | null, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestActiveRunResponse>({
    queryKey: serverStateKeys.strategyTests.active(userId ?? undefined),
    queryFn: () => api.strategyTests.activeRun(userId ?? undefined),
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useStrategyTestEstimate(request: StrategyTestRunRequest | null, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestEstimateResponse>({
    queryKey: serverStateKeys.strategyTests.estimate(request),
    queryFn: () => api.strategyTests.estimate(request as StrategyTestRunRequest),
    enabled: options.enabled ?? Boolean(request),
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useStrategyTestRun(runId: string | null, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestRunResponse>({
    queryKey: serverStateKeys.strategyTests.run(runId ?? "none"),
    queryFn: () => api.strategyTests.getRun(runId as string),
    enabled: options.enabled ?? Boolean(runId),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useRunStrategyTest() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: StrategyTestRunRequest) => api.strategyTests.run(request),
    onSuccess: async (response) => {
      queryClient.setQueryData(serverStateKeys.strategyTests.run(response.run_id), response);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.strategyTests.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.journal.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.trades.all() })
      ]);
    }
  });
}

export function useCancelStrategyTestRun() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (runId: string) => api.strategyTests.cancelRun(runId),
    onSuccess: async (response) => {
      queryClient.setQueryData(serverStateKeys.strategyTests.run(response.run_id), response);
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.strategyTests.all() });
    }
  });
}

export function usePublishStrategyTestCalibration() {
  const queryClient = useQueryClient();

  return useMutation<StrategyTestCalibrationResponse, Error, string>({
    mutationFn: (runId: string) => api.strategyTests.publishCalibration(runId),
    onSuccess: async (response) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.strategyTests.report(response.run_id) }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.strategyTests.reports() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.strategyTests.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() })
      ]);
    }
  });
}

export function useStrategyTestReport(runId: string | null, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestReport>({
    queryKey: serverStateKeys.strategyTests.report(runId ?? "none"),
    queryFn: () => api.strategyTests.getReport(runId as string),
    enabled: options.enabled ?? Boolean(runId),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useStrategyTestReports(filters?: StrategyTestReportFilters, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestReport[]>({
    queryKey: serverStateKeys.strategyTests.reports(filters),
    queryFn: () => api.strategyTests.listReports(filters),
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useStrategyTestTrades(runId: string | null, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestTrade[]>({
    queryKey: serverStateKeys.strategyTests.trades(runId ?? "none"),
    queryFn: () => api.strategyTests.getTrades(runId as string),
    enabled: options.enabled ?? Boolean(runId),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useStrategyTestSignals(runId: string | null, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestSignalEvent[]>({
    queryKey: serverStateKeys.strategyTests.signals(runId ?? "none"),
    queryFn: () => api.strategyTests.getSignals(runId as string),
    enabled: options.enabled ?? Boolean(runId),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useStrategyTestFunnel(runId: string | null, options: PlannedQueryOptions = {}) {
  return useQuery<StrategyTestFunnelResponse>({
    queryKey: serverStateKeys.strategyTests.funnel(runId ?? "none"),
    queryFn: () => api.strategyTests.getFunnel(runId as string),
    enabled: options.enabled ?? Boolean(runId),
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useCloseMarketTradeMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.closeMarketTrade,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.journal.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.trades.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.risk.all() })
      ]);
    }
  });
}

export function useTradeInvalidationQuery(tradeId: string | null, options: PlannedQueryOptions = {}) {
  return useQuery({
    queryKey: serverStateKeys.trades.invalidation(tradeId ?? "none"),
    queryFn: () => api.tradeInvalidation(tradeId as string),
    enabled: options.enabled ?? Boolean(tradeId),
    refetchInterval: options.refetchInterval ?? serverStatePolicy.reconciliationIntervalMs,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useTradeInvalidationActionMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.tradeInvalidationAction,
    onSuccess: async (response) => {
      queryClient.setQueryData(
        serverStateKeys.trades.invalidation(response.alert.trade_id),
        response.alert
      );
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.trades.all() });
    }
  });
}

export function useRadarConfigQuery() {
  return useQuery({
    queryKey: serverStateKeys.settings.radar(),
    queryFn: api.config,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useRiskStateQuery(options: PlannedQueryOptions = {}) {
  return useQuery<RiskStateResponse>({
    queryKey: serverStateKeys.risk.state(),
    queryFn: api.riskState,
    enabled: options.enabled ?? true,
    refetchInterval: options.refetchInterval,
    staleTime: serverStatePolicy.realtimeStaleTimeMs
  });
}

export function useSettingsQuery() {
  return useRadarConfigQuery();
}

export function useWatchlistQuery() {
  return useQuery({
    queryKey: serverStateKeys.watchlist.current(),
    queryFn: api.watchlist,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useMarketPairsQuery() {
  return useQuery({
    queryKey: serverStateKeys.watchlist.pairs(),
    queryFn: () => api.marketPairs(),
    staleTime: serverStatePolicy.staticStaleTimeMs
  });
}

export function useMarketUniversePairsQuery(params: MarketUniversePairsQuery = {}) {
  return useQuery({
    queryKey: serverStateKeys.marketUniverse.pairs(params),
    queryFn: () => api.marketUniversePairs(params),
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useSyncMarketUniverseMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: MarketUniverseSyncRequest) => api.syncMarketUniverse(request),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.marketUniverse.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.watchlist.pairs() })
      ]);
    }
  });
}

export function useStrategyConfigsQuery() {
  return useQuery({
    queryKey: serverStateKeys.settings.strategyConfigs(),
    queryFn: api.strategyConfigs,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useUpdateStrategyConfigMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ configId, patch }: { configId: string; patch: StrategyConfigPatch }) =>
      api.updateStrategyConfig(configId, patch),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.settings.strategyConfigs() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() })
      ]);
    }
  });
}

export function useAlertRulesQuery() {
  return useQuery({
    queryKey: serverStateKeys.alerts.rules(),
    queryFn: api.alertRules,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useAddWatchlistPairMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.addWatchlistPair,
    onSuccess: async (watchlist) => {
      queryClient.setQueryData(serverStateKeys.watchlist.current(), watchlist);
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.watchlist.all() });
    }
  });
}

export function useRemoveWatchlistPairMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.removeWatchlistPair,
    onSuccess: async (watchlist) => {
      queryClient.setQueryData(serverStateKeys.watchlist.current(), watchlist);
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.watchlist.all() });
    }
  });
}

export function useCreateAlertRuleMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (draft: AlertRuleDraft) => api.createAlertRule(draft),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.alerts.all() });
    }
  });
}

export function useUpdateAlertRuleMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ alertId, patch }: { alertId: string; patch: Partial<AlertRuleDraft> }) =>
      api.updateAlertRule(alertId, patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.alerts.all() });
    }
  });
}

export function useDeleteAlertRuleMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.deleteAlertRule,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.alerts.all() });
    }
  });
}

export function useTestAlertRuleMutation() {
  return useMutation({
    mutationFn: api.testAlertRule
  });
}

export function useNotificationsQuery() {
  return useQuery({
    queryKey: serverStateKeys.notifications.list(),
    queryFn: api.notifications,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useCreateNotificationMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (draft: NotificationDraft) => api.createNotification(draft),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.notifications.all() });
    }
  });
}

export function useCreateTestNotificationMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.createTestNotification,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.notifications.all() });
    }
  });
}

export function useMarkNotificationReadMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ notificationId, isRead = true }: { notificationId: string; isRead?: boolean }) =>
      api.markNotificationRead(notificationId, isRead),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.notifications.all() });
    }
  });
}

export function useMarkAllNotificationsReadMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.markAllNotificationsRead,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.notifications.all() });
    }
  });
}

export function useDeleteNotificationMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.deleteNotification,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.notifications.all() });
    }
  });
}

export function useExchangeConnectionsQuery() {
  return useQuery({
    queryKey: serverStateKeys.exchangeConnections.list(),
    queryFn: api.exchangeConnections,
    staleTime: serverStatePolicy.staticStaleTimeMs
  });
}

export function useExchangeConnectionWalletBalancesQuery(connectionIds: string[], userId?: string | null) {
  const uniqueConnectionIds = uniqueIds(connectionIds);
  const queries = useQueries({
    queries: uniqueConnectionIds.map((connectionId) => ({
      queryKey: serverStateKeys.exchangeConnections.walletBalance(connectionId, userId ?? "me"),
      queryFn: () => api.getConnectionWalletBalance(connectionId, userId ?? undefined),
      enabled: Boolean(connectionId),
      refetchInterval: serverStatePolicy.slowBackgroundRefreshMs,
      staleTime: serverStatePolicy.realtimeStaleTimeMs
    }))
  });

  return mapConnectionQueryResults<ExchangeWalletBalance>(uniqueConnectionIds, queries);
}

export function useExchangeConnectionAccountSnapshotsQuery(connectionIds: string[], userId?: string | null) {
  const uniqueConnectionIds = uniqueIds(connectionIds);
  const queries = useQueries({
    queries: uniqueConnectionIds.map((connectionId) => ({
      queryKey: serverStateKeys.exchangeConnections.accountSnapshot(connectionId, userId ?? "me"),
      queryFn: () => api.getConnectionAccountSnapshot(connectionId, userId ?? undefined),
      enabled: Boolean(connectionId),
      refetchInterval: serverStatePolicy.slowBackgroundRefreshMs,
      staleTime: serverStatePolicy.realtimeStaleTimeMs
    }))
  });

  return mapConnectionQueryResults<AccountRiskSnapshot>(uniqueConnectionIds, queries);
}

export function useRefreshExchangeConnectionBalanceMutation(userId?: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (connectionId: string) => {
      const snapshot = await api.getConnectionAccountSnapshot(connectionId, userId ?? undefined, true);
      const wallet = await api.getConnectionWalletBalance(connectionId, userId ?? undefined, false);
      return { connectionId, snapshot, wallet };
    },
    onSuccess: async ({ connectionId, snapshot, wallet }) => {
      queryClient.setQueryData(
        serverStateKeys.exchangeConnections.accountSnapshot(connectionId, userId ?? "me"),
        snapshot
      );
      queryClient.setQueryData(
        serverStateKeys.exchangeConnections.walletBalance(connectionId, userId ?? "me"),
        wallet
      );
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.exchangeConnections.all() });
    }
  });
}

export function useCreateExchangeConnectionMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (draft: ExchangeConnectionDraft) => api.createExchangeConnection(draft),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.exchangeConnections.all() });
    }
  });
}

export function useUpdateExchangeConnectionMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ connectionId, patch }: { connectionId: string; patch: Partial<ExchangeConnectionDraft> & { status?: string } }) =>
      api.updateExchangeConnection(connectionId, patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.exchangeConnections.all() });
    }
  });
}

export function useDeleteExchangeConnectionMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.deleteExchangeConnection,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.exchangeConnections.all() });
    }
  });
}

export function useTestExchangeConnectionMutation() {
  return useMutation({
    mutationFn: api.testExchangeConnection
  });
}

export function useSyncExchangeConnectionMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.syncExchangeConnection,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: serverStateKeys.exchangeConnections.all() });
    }
  });
}

export function useUserProfileQuery(options: PlannedQueryOptions = {}) {
  return useQuery<UserProfile>({
    queryKey: serverStateKeys.user.profile(),
    queryFn: api.userProfile,
    enabled: options.enabled ?? false,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useUpdateUserSettingsMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.updateUserSettings,
    onSuccess: async (profile) => {
      queryClient.setQueryData(serverStateKeys.user.profile(), profile);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.user.profile() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.risk.all() })
      ]);
    }
  });
}

export function useSubscriptionStatusQuery(options: PlannedQueryOptions = {}) {
  return useQuery<SubscriptionStatus>({
    queryKey: serverStateKeys.subscription.status(),
    queryFn: api.subscriptionStatus,
    enabled: options.enabled ?? false,
    staleTime: serverStatePolicy.defaultStaleTimeMs
  });
}

export function useConfirmVirtualMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.confirmVirtual,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.signals.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.journal.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.trades.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.risk.all() })
      ]);
    }
  });
}

export function useSendSignalActionMutation() {
  const queryClient = useQueryClient();

  return useMutation<SignalActionResponse, Error, SignalActionRequest>({
    mutationFn: ({ signalId, kind, mode, connectionId }) =>
      api.sendSignalAction(signalId, { kind, mode, connectionId }),
    onSuccess: async (response, variables) => {
      queryClient.setQueryData(
        serverStateKeys.signals.actionState(
          variables.signalId,
          variables.mode,
          variables.connectionId ?? "none"
        ),
        response.state
      );
      if (response.pending_entry_intent) {
        queryClient.setQueryData(
          serverStateKeys.signals.pendingEntry(
            response.pending_entry_intent.signal_id,
            response.pending_entry_intent.user_id
          ),
          response.pending_entry_intent
        );
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.signals.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.journal.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.trades.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.risk.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.exchangeConnections.all() })
      ]);
    }
  });
}

export function useConfirmRealMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.confirmReal,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.signals.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.journal.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.trades.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.risk.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.exchangeConnections.all() })
      ]);
    }
  });
}

export function useArmPendingEntryMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.armPendingEntry,
    onSuccess: async (intent) => {
      queryClient.setQueryData(
        serverStateKeys.signals.pendingEntry(intent.signal_id, intent.user_id),
        intent
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.signals.all() })
      ]);
    }
  });
}

export function useCancelPendingEntryMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.cancelPendingEntry,
    onSuccess: async (intent) => {
      queryClient.setQueryData<PendingEntryIntent | null>(
        serverStateKeys.signals.pendingEntry(intent.signal_id, intent.user_id),
        (current) => pendingEntryAfterCancel(current, intent)
      );
      queryClient.setQueryData<PendingEntryIntent[]>(
        serverStateKeys.signals.pendingEntryHistory(intent.signal_id, intent.user_id),
        (current) => upsertPendingEntryHistory(current, intent)
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.signals.all() })
      ]);
    }
  });
}

export function useReconfirmPendingEntryMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.reconfirmPendingEntry,
    onSuccess: async (intent) => {
      queryClient.setQueryData(
        serverStateKeys.signals.pendingEntry(intent.signal_id, intent.user_id),
        intent
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.signals.all() })
      ]);
    }
  });
}

export function useRejectSignalMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.rejectSignal,
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.all() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.signals.all() })
      ]);
    }
  });
}

export function useStartScannerMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.startScanner,
    onMutate: () => {
      applyScannerRunning(queryClient, true);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.health() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.status() })
      ]);
    },
    onError: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.health() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.status() })
      ]);
    }
  });
}

export function useStopScannerMutation() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: api.stopScanner,
    onMutate: () => {
      applyScannerRunning(queryClient, false);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.health() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.status() })
      ]);
    },
    onError: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: serverStateKeys.health() }),
        queryClient.invalidateQueries({ queryKey: serverStateKeys.radar.status() })
      ]);
    }
  });
}

function uniqueIds(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}

function uniquePendingActionTargets(pendingEntries: PendingEntryIntent[]) {
  const targets = pendingEntries.map((intent) => ({
    signalId: intent.signal_id,
    mode: intent.mode,
    connectionId: pendingEntryConnectionId(intent)
  }));
  const seen = new Set<string>();
  return targets.filter((target) => {
    const key = pendingActionTargetKey(target);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function pendingActionTargetKey(target: { signalId: string; mode: SignalActionMode; connectionId?: string | null }): string {
  return `${target.signalId}:${target.mode}:${target.connectionId ?? "none"}`;
}

function pendingEntryConnectionId(intent: PendingEntryIntent): string | null {
  const snapshot = intent.request_snapshot;
  const metadata = isRecord(snapshot.metadata) ? snapshot.metadata : {};
  for (const value of [snapshot.connection_id, snapshot.connectionId, metadata.connection_id, metadata.connectionId]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function mapConnectionQueryResults<T>(
  connectionIds: string[],
  queries: Array<{
    data?: T;
    error: unknown;
    isFetching: boolean;
    isLoading: boolean;
    isPending?: boolean;
  }>
) {
  const dataByConnectionId: Record<string, T | null> = {};
  const pendingByConnectionId: Record<string, boolean> = {};
  const errorByConnectionId: Record<string, unknown> = {};

  connectionIds.forEach((connectionId, index) => {
    const query = queries[index];
    dataByConnectionId[connectionId] = query?.data ?? null;
    pendingByConnectionId[connectionId] = Boolean(query?.isLoading || query?.isFetching || query?.isPending);
    if (query?.error) {
      errorByConnectionId[connectionId] = query.error;
    }
  });

  return { dataByConnectionId, pendingByConnectionId, errorByConnectionId };
}

export function applySignalSnapshot(queryClient: QueryClient, signals: RadarSignal[]) {
  const openSignals = signals.filter(isOpenFeedSignal);
  queryClient.setQueryData(queryKeys.signals, openSignals);
  queryClient.setQueryData(serverStateKeys.signals.open(), openSignals);
  queryClient.setQueryData(
    serverStateKeys.signals.active(),
    openSignals.filter((signal) => isExecutionCandidateStatus(signal.status))
  );
  queryClient.setQueryData(serverStateKeys.signals.history(), signals);
  queryClient.setQueryData<RadarResponse>(queryKeys.radar, radarResponseWithSignals(openSignals));
}

export function applyTradeSnapshot(queryClient: QueryClient, trades: TradeJournalResponse) {
  queryClient.setQueryData(queryKeys.trades, trades);
}

function applyScannerRunning(queryClient: QueryClient, scannerRunning: boolean) {
  const patch: Partial<HealthStatus> = scannerRunning
    ? {
        scanner_running: true,
        scanner_stopping: false,
        stage: "starting",
        market_data_status: "waiting"
      }
    : {
        scanner_running: false,
        scanner_stopping: false,
        stage: "stopped",
        market_data_status: "offline",
        market_stream_connected: false,
        ws_connected: false
      };
  queryClient.setQueryData<HealthStatus>(serverStateKeys.health(), (current) =>
    current ? { ...current, ...patch } : current
  );
  queryClient.setQueryData<RadarStatus>(serverStateKeys.radar.status(), (current) =>
    current ? { ...current, ...patch } : current
  );
}

function filterSignals(signals: RadarSignal[], filters?: SignalHistoryFilters): RadarSignal[] {
  return signals.filter((signal) => {
    const statusMatches = !filters?.status || signal.status === filters.status;
    const symbolMatches = !filters?.symbol || signal.symbol === filters.symbol;
    return statusMatches && symbolMatches;
  });
}

function isActivePendingEntryIntent(intent: PendingEntryIntent): boolean {
  return isActivePendingEntryStatus(intent.status);
}

function pendingEntryAfterCancel(current: PendingEntryIntent | null | undefined, cancelled: PendingEntryIntent): PendingEntryIntent | null {
  if (!current) return null;
  if (current.id === cancelled.id) return null;
  return isActivePendingEntryIntent(current) ? current : null;
}

function upsertPendingEntryHistory(current: PendingEntryIntent[] | undefined, intent: PendingEntryIntent): PendingEntryIntent[] {
  return [intent, ...(current ?? []).filter((item) => item.id !== intent.id)]
    .sort((left, right) => pendingEntryUpdatedAt(right) - pendingEntryUpdatedAt(left));
}

function pendingEntryUpdatedAt(intent: PendingEntryIntent): number {
  const updatedAt = Date.parse(intent.updated_at);
  if (Number.isFinite(updatedAt)) return updatedAt;
  const createdAt = Date.parse(intent.created_at);
  return Number.isFinite(createdAt) ? createdAt : 0;
}
