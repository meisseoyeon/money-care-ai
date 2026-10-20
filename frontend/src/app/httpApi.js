import { AppError } from '../shared/lib/errors.js';
import { createHttpClient } from '../shared/api/httpClient.js';
import { createAuthSessions } from '../features/auth/session.js';
import { createTransferApi } from '../features/transfers/api.js';
import { createTransactionApi } from '../features/transactions/api.js';
import { createAlertApi } from '../features/alerts/api.js';
import { createBudgetApi } from '../features/budgets/api.js';
import { createSettingsApi } from '../features/settings/api.js';
import { createSupporterApi } from '../features/supporters/api.js';

// 기능별 API를 기존 AppProvider가 사용하는 인터페이스로 조합합니다.
export function createHttpApi(baseUrl, { storage = sessionStorage, fetchImpl = fetch } = {}) {
  const request = createHttpClient(baseUrl, { storage, fetchImpl });
  const auth = createAuthSessions({ request, storage });
  const transfers = createTransferApi(request);
  const transactions = createTransactionApi(request);
  return {
    mode: 'api',
    restoreSession: auth.restore,
    logout: auth.logout,
    clearSession: auth.clear,
    login: auth.login,
    ...transfers,
    ...transactions,
    ...createAlertApi(request),
    ...createBudgetApi(request),
    ...createSettingsApi(request),
    ...createSupporterApi(request),
    async loadData() {
      const [context, recipients, history] = await Promise.all([
        request('/demo/me'), transfers.loadRecipients(), transactions.loadTransactions(),
      ]);
      // 탐지·알림 API는 담당 기능 병합 시 연결합니다.
      return { ...context, recipients, forecast: null, baseline: null, transactions: history, alerts: [], guides: [], links: [], shares: [] };
    },
    async resetData() { throw new AppError('실제 API 모드에서는 프런트엔드에서 데이터를 초기화하지 않아요.'); },
  };
}
