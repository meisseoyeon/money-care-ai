import { calculateForecast } from '../budgets/forecast.js';
import { validateMoney } from '../../shared/lib/money.js';

export const TRANSFER_REVIEW_THRESHOLD = 100000;

// 송금 전 미리보기만 계산합니다. 잔액이나 거래 내역을 변경하지 않습니다.
export function reviewTransfer(data, amount, now = new Date()) {
  validateMoney(amount);
  const projectedBalance = data.account.current_balance - amount;
  const forecast = data.preparation?.source === 'api' && data.forecast
    ? { ...data.forecast, current_balance: projectedBalance,
      available_amount: data.forecast.available_amount - amount,
      shortage_amount: Math.max(0, amount - data.forecast.available_amount) }
    : data.settings
    ? calculateForecast(
      { ...data.account, current_balance: projectedBalance },
      data.settings,
      data.expenses ?? [],
      now,
    )
    : null;
  return { requiresReview: amount > TRANSFER_REVIEW_THRESHOLD, projectedBalance, forecast };
}

export function reviewSource(data) {
  return JSON.stringify([data.account?.current_balance, data.account?.balance_as_of,
    data.preparation?.source === 'api' ? data.forecast?.id : null,
    data.forecast?.expected_living_cost, data.forecast?.scheduled_expense_total]);
}
