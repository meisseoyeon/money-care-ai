import { AppError } from '../shared/lib/errors.js';
import { createHttpClient } from '../shared/api/httpClient.js';
import { createAuthSessions } from '../features/auth/session.js';
import { createTransferApi } from '../features/transfers/api.js';
import { createTransactionApi } from '../features/transactions/api.js';
import { createAlertApi } from '../features/alerts/api.js';
import { createBudgetApi } from '../features/budgets/api.js';
import { createSettingsApi } from '../features/settings/api.js';
import { createSupporterApi } from '../features/supporters/api.js';
import { createPreparationApi } from '../features/preparation/api.js';

// 기능별 API를 AppProvider가 사용하는 인터페이스로 조합합니다.
export function createHttpApi(
  baseUrl,
  { storage = sessionStorage, fetchImpl = fetch } = {},
) {
  const request = createHttpClient(baseUrl, { storage, fetchImpl });
  const auth = createAuthSessions({ request, storage });
  const transfers = createTransferApi(request);
  const transactions = createTransactionApi(request);
  const preparation = createPreparationApi(request);
  const alerts = createAlertApi(request);
  const supporters = createSupporterApi(request);

  return {
    mode: 'api',
    restoreSession: auth.restore,
    logout: auth.logout,
    clearSession: auth.clear,
    login: auth.login,
    ...transfers,
    ...transactions,
    ...alerts,
    ...createBudgetApi(request),
    ...createSettingsApi(request),
    ...supporters,

    async loadData() {
      const context = await request('/demo/me');
      if (context.user?.role === 'SUPPORTER') {
        return { user: context.user, sharedAlerts: await supporters.loadSharedAlerts(),
          alerts: [], links: [], shares: [], transactions: [], recipients: [],
          forecast: null, baseline: null, guides: [] };
      }
      const [recipients, history, prepared, alertItems, links, shares] =
        await Promise.all([
          transfers.loadRecipients(),
          transactions.loadTransactions(),
          preparation.loadPreparation(),
          alerts.loadAlerts(),
          supporters.loadLinks(),
          supporters.loadShares(),
        ]);

      const wrongUser = [prepared.baseline, prepared.forecast].some(
        (result) => result && result.user_id !== context.user?.user_id,
      );

      if (wrongUser) {
        prepared.preparation = {
          status: 'ERROR',
          source: 'api',
          message:
            '로그인 사용자와 준비 결과를 확인하지 못했어요. 다시 로그인해 주세요.',
        };
        prepared.forecast = null;
        prepared.baseline = null;
      } else if (
        prepared.forecast &&
        (
          context.account?.current_balance !==
            prepared.forecast.current_balance ||
          (
            context.settings &&
            (
              context.settings.daily_living_budget !==
                prepared.forecast.daily_living_budget ||
              context.settings.next_income_date !==
                prepared.forecast.next_income_date
            )
          )
        )
      ) {
        prepared.preparation = {
          status: 'STALE',
          source: 'api',
          message:
            '잔액이나 생활비 계획이 바뀌었어요. 다시 조회하고 최신 결과를 확인해 주세요.',
        };
        prepared.forecast = null;
      }

      return {
        ...context,
        recipients,
        ...prepared,
        transactions: history,
        alerts: alertItems,
        guides: alertItems.filter((a) => a.guide).map((a) => a.guide),
        links,
        shares,
      };
    },

    async resetData() {
      throw new AppError(
        '실제 API 모드에서는 프런트엔드에서 데이터를 초기화하지 않아요.',
      );
    },
  };
}
