import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/api";
import { isExecutionCandidateStatus } from "@/domain/signal-status";
import type {
  StrategyTestReport,
  StrategyTestRunRequest,
  StrategyTestRunResponse,
  StrategyTestTrade
} from "@/features/strategy-testing/types";
import type {
  AlertRuleDraft,
  ExchangeConnectionDraft,
  NotificationDraft,
  RadarDisplayMode,
  StrategyConfigPatch,
  SubscriptionStatus,
  UserProfile
} from "@/features/server-state/types";
import type { HealthStatus, RadarResponse, RadarSignal, RadarStatus, RiskStateResponse, TradeJournalResponse } from "@/types";
import { isOpenFeedSignal } from "@/utils";
import {
  queryKeys,
  serverStateKeys,
  type CandleFilters,
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

export function useRadarQuery(radarDisplayMode?: RadarDisplayMode | null, userId = "demo_user") {
  return useQuery({
    queryKey: serverStateKeys.radar.dashboard(radarDisplayMode ?? undefined, userId),
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
    queryFn: api.marketPairs,
    staleTime: serverStatePolicy.staticStaleTimeMs
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

export function applySignalSnapshot(queryClient: QueryClient, signals: RadarSignal[]) {
  const openSignals = signals.filter(isOpenFeedSignal);
  queryClient.setQueryData(queryKeys.signals, openSignals);
  queryClient.setQueryData(serverStateKeys.signals.open(), openSignals);
  queryClient.setQueryData(
    serverStateKeys.signals.active(),
    openSignals.filter((signal) => isExecutionCandidateStatus(signal.status))
  );
  queryClient.setQueryData(serverStateKeys.signals.history(), signals);
  queryClient.setQueryData<RadarResponse>(queryKeys.radar, { signals: openSignals });
}

export function applyTradeSnapshot(queryClient: QueryClient, trades: TradeJournalResponse) {
  queryClient.setQueryData(queryKeys.trades, trades);
}

function applyScannerRunning(queryClient: QueryClient, scannerRunning: boolean) {
  const patch = { scanner_running: scannerRunning };
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
