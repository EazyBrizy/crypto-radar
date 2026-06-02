import { authApi } from "./auth.api";
import { billingApi } from "./billing.api";
import { candlesApi } from "./candles.api";
import { exchangesApi } from "./exchanges.api";
import { journalApi } from "./journal.api";
import { notificationsApi } from "./notifications.api";
import { settingsApi } from "./settings.api";
import { signalsApi } from "./signals.api";
import { strategyTestsApi } from "./strategy-tests.api";
import { tradesApi } from "./trades.api";

export { API_BASE, API_ORIGIN_LABEL, openApiClient } from "./client";
export { authApi } from "./auth.api";
export { billingApi } from "./billing.api";
export { candlesApi } from "./candles.api";
export { exchangesApi } from "./exchanges.api";
export { journalApi } from "./journal.api";
export { notificationsApi } from "./notifications.api";
export { settingsApi } from "./settings.api";
export { signalsApi } from "./signals.api";
export { strategyTestsApi } from "./strategy-tests.api";
export { tradesApi } from "./trades.api";

export const api = {
  auth: authApi,
  billing: billingApi,
  health: settingsApi.health,
  radar: signalsApi.radar,
  radarStatus: settingsApi.radarStatus,
  candles: candlesApi.list,
  signals: signalsApi.list,
  activeSignals: signalsApi.active,
  openSignals: signalsApi.open,
  historicalSignals: signalsApi.historical,
  confirmVirtual: signalsApi.confirmVirtual,
  executionPreview: signalsApi.executionPreview,
  rejectSignal: signalsApi.reject,
  strategyTests: strategyTestsApi,
  trades: tradesApi.list,
  closedTrades: tradesApi.closed,
  closeMarketTrade: tradesApi.closeMarket,
  tradeInvalidation: tradesApi.invalidation,
  tradeInvalidationAction: tradesApi.invalidationAction,
  journalHistory: journalApi.history,
  notifications: notificationsApi.list,
  createNotification: notificationsApi.create,
  createTestNotification: notificationsApi.createTest,
  markNotificationRead: notificationsApi.markRead,
  markAllNotificationsRead: notificationsApi.markAllRead,
  deleteNotification: notificationsApi.delete,
  config: settingsApi.config,
  settings: settingsApi.settings,
  watchlist: settingsApi.watchlist,
  marketPairs: settingsApi.marketPairs,
  strategyConfigs: settingsApi.strategyConfigs,
  updateStrategyConfig: settingsApi.updateStrategyConfig,
  addWatchlistPair: settingsApi.addWatchlistPair,
  removeWatchlistPair: settingsApi.removeWatchlistPair,
  alertRules: settingsApi.alertRules,
  createAlertRule: settingsApi.createAlertRule,
  updateAlertRule: settingsApi.updateAlertRule,
  deleteAlertRule: settingsApi.deleteAlertRule,
  testAlertRule: settingsApi.testAlertRule,
  exchangeCatalog: exchangesApi.catalog,
  exchangeConnections: exchangesApi.connections,
  createExchangeConnection: exchangesApi.createConnection,
  updateExchangeConnection: exchangesApi.updateConnection,
  deleteExchangeConnection: exchangesApi.deleteConnection,
  testExchangeConnection: exchangesApi.testConnection,
  syncExchangeConnection: exchangesApi.syncConnection,
  userProfile: settingsApi.userProfile,
  updateUserSettings: settingsApi.updateUserSettings,
  riskState: settingsApi.riskState,
  subscriptionStatus: settingsApi.subscriptionStatus,
  billingPlans: billingApi.plans,
  billingSubscription: billingApi.subscription,
  createBillingCheckout: billingApi.checkout,
  createBillingCustomerPortal: billingApi.customerPortal,
  startScanner: settingsApi.startScanner,
  stopScanner: settingsApi.stopScanner
};
