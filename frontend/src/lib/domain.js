export class AppError extends Error {
  constructor(message, status = 400) { super(message); this.name = 'AppError'; this.status = status; }
}

export const won = (amount) => `${new Intl.NumberFormat('ko-KR').format(amount)}원`;
export function localDate(value = new Date()) {
  const d = new Date(value);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export function addDays(value, count) { const d = new Date(value); d.setDate(d.getDate() + count); return d; }
export function daysBetween(start, end) {
  const utc = (s) => { const [y, m, d] = s.split('-').map(Number); return Date.UTC(y, m - 1, d); };
  return Math.round((utc(end) - utc(start)) / 86400000);
}
export function formatTime(value) {
  return new Intl.DateTimeFormat('ko-KR', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value));
}
export function percentile(values, p) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b), i = (sorted.length - 1) * p;
  return sorted[Math.floor(i)] + (sorted[Math.ceil(i)] - sorted[Math.floor(i)]) * (i % 1);
}
export function validateMoney(value, { allowZero = false } = {}) {
  if (!Number.isSafeInteger(value) || value < (allowZero ? 0 : 1) || value > 1000000000) {
    throw new AppError(allowZero ? '금액은 0원 이상 10억 원 이하의 정수로 입력해 주세요.' : '금액은 1원 이상 10억 원 이하의 정수로 입력해 주세요.');
  }
  return value;
}
export function calculateForecast(account, settings, expenses, now = new Date()) {
  const days = daysBetween(localDate(now), settings.next_income_date);
  if (days < 0) throw new AppError('다음 수입일을 오늘 이후로 바꿔 주세요.');
  const fixed = expenses.filter((e) => e.status === 'PLANNED' && e.due_date >= localDate(now) && e.due_date < settings.next_income_date).reduce((a, e) => a + e.amount, 0);
  const living = days * settings.daily_living_budget;
  const available = account.current_balance - fixed - living;
  return { user_id: account.user_id, as_of: new Date(now).toISOString(), next_income_date: settings.next_income_date, remaining_days: days, current_balance: account.current_balance, scheduled_expense_total: fixed, daily_living_budget: settings.daily_living_budget, expected_living_cost: living, available_amount: available, shortage_amount: Math.max(0, -available), calculation_version: 'mock-v1' };
}
export const RESPONSE_LABELS = { PLANNED: '계획한 거예요', UNSURE: '잘 모르겠어요', HELP_REQUESTED: '도와주세요' };
export const ALERT_LABELS = { LARGE_OUTFLOW: '평소보다 큰 송금', NEW_COUNTERPARTY: '처음 보내는 상대', BUDGET_SHORTAGE: '생활비 확인' };
