import { calculateForecast, validateMoney } from './domain.js';

export const TRANSFER_REVIEW_THRESHOLD = 100000;

// 송금 전 미리보기만 계산합니다. 잔액이나 거래 내역을 변경하지 않습니다.
export function reviewTransfer(data, amount, now = new Date()) {
  validateMoney(amount);
  const projectedBalance = data.account.current_balance - amount;
  const forecast = data.settings
    ? calculateForecast(
      { ...data.account, current_balance: projectedBalance },
      data.settings,
      data.expenses ?? [],
      now,
    )
    : null;
  return { requiresReview: amount > TRANSFER_REVIEW_THRESHOLD, projectedBalance, forecast };
}
