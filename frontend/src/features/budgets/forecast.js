import { AppError } from '../../shared/lib/errors.js';
import { daysBetween, localDate } from '../../shared/lib/dates.js';

export function calculateForecast(account, settings, expenses, now = new Date()) {
  const days = daysBetween(localDate(now), settings.next_income_date);
  if (days < 0) throw new AppError('다음 수입일을 오늘 이후로 바꿔 주세요.');
  const fixed = expenses.filter((e) => e.status === 'PLANNED' && e.due_date >= localDate(now) && e.due_date < settings.next_income_date).reduce((a, e) => a + e.amount, 0);
  const living = days * settings.daily_living_budget;
  const available = account.current_balance - fixed - living;
  return { user_id: account.user_id, as_of: new Date(now).toISOString(), next_income_date: settings.next_income_date, remaining_days: days, current_balance: account.current_balance, scheduled_expense_total: fixed, daily_living_budget: settings.daily_living_budget, expected_living_cost: living, available_amount: available, shortage_amount: Math.max(0, -available), calculation_version: 'mock-v1' };
}
