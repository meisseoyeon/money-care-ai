import { addDays, localDate } from '../shared/lib/dates.js';
import { percentile } from '../shared/lib/statistics.js';

export const TEST_PASSWORD = 'moneycare123!';
export const TEST_ACCOUNTS = [
  { email: 'user-a@example.test', name: '당사자 A', description: '서연 · 송금과 도움 요청' },
  { email: 'user-b@example.test', name: '당사자 B', description: '민지 · 다른 사용자 데이터 확인' },
  { email: 'supporter@example.test', name: '지원자', description: '이지원 · 공유받은 알림 확인' },
];
export function seedDatabase(now = new Date()) {
  const iso = now.toISOString();
  const users = [
    { user_id: 'user-a', email: TEST_ACCOUNTS[0].email, display_name: '서연', role: 'OWNER', status: 'ACTIVE', monitoring_consented_at: iso, monitoring_revoked_at: null },
    { user_id: 'user-b', email: TEST_ACCOUNTS[1].email, display_name: '민지', role: 'OWNER', status: 'ACTIVE', monitoring_consented_at: iso, monitoring_revoked_at: null },
    { user_id: 'supporter-s', email: TEST_ACCOUNTS[2].email, display_name: '이지원', role: 'SUPPORTER', status: 'ACTIVE' },
  ];
  const recipients = [
    { id: 'payee-1', name: '박민수', bank: '가상 은행', account_hint: '••• 1024', initial: '민' },
    { id: 'payee-2', name: '김지연', bank: '가상 은행', account_hint: '••• 2840', initial: '지' },
    { id: 'payee-3', name: '이도윤', bank: '가상 은행', account_hint: '••• 3912', initial: '도' },
    { id: 'payee-4', name: '정유나', bank: '가상 은행', account_hint: '••• 5023', initial: '유' },
    { id: 'payee-5', name: '김하늘', bank: '가상 은행', account_hint: '••• 7768', initial: '하' },
    { id: 'payee-6', name: '최새봄', bank: '가상 은행', account_hint: '••• 9401', initial: '새' },
  ];
  const accounts = [], transactions = [], settings = [], expenses = [], baselines = [];
  for (const user of users.filter((u) => u.role === 'OWNER')) {
    const account_id = `account-${user.user_id}`;
    const history = [];
    for (let day = 30; day >= 1; day--) {
      for (let slot = 0; slot < 3; slot++) {
        const index = (30 - day) * 3 + slot;
        const income = index === 0 || index === 45;
        const time = addDays(now, -day); time.setHours(9 + slot * 4, 10, 0, 0);
        const p = recipients[index % 4];
        history.push({ id: `seed-${user.user_id}-${index}`, account_id, user_id: user.user_id, occurred_at: time.toISOString(), received_at: time.toISOString(), direction: income ? 'IN' : 'OUT', amount: income ? 500000 : [4500, 8000, 12000, 20000, 15000, 30000, 6000][index % 7], tx_type: income ? 'INCOME' : (slot === 0 ? 'PURCHASE' : 'TRANSFER'), counterparty_id: income ? null : p.id, description: income ? '정기 수입' : (slot === 0 ? '식비·교통비' : `${p.name}에게 보냄`), source: 'SYNTHETIC', detection_status: 'COMPLETED' });
      }
    }
    let balance = 800000 - history.reduce((sum, t) => sum + (t.direction === 'IN' ? t.amount : -t.amount), 0);
    for (const t of history) { balance += t.direction === 'IN' ? t.amount : -t.amount; t.balance_after = balance; }
    transactions.push(...history);
    accounts.push({ account_id, user_id: user.user_id, display_name: '생활비 통장', current_balance: balance, balance_as_of: iso });
    settings.push({ user_id: user.user_id, next_income_date: localDate(addDays(now, 20)), expected_income_amount: 1000000, daily_living_budget: 20000 });
    expenses.push({ id: `rent-${user.user_id}`, user_id: user.user_id, title: '월세', amount: 100000, due_date: localDate(addDays(now, 5)), status: 'PLANNED' }, { id: `phone-${user.user_id}`, user_id: user.user_id, title: '통신비', amount: 50000, due_date: localDate(addDays(now, 10)), status: 'PLANNED' });
    const out = history.filter((t) => t.direction === 'OUT').map((t) => t.amount);
    baselines.push({ user_id: user.user_id, p95_out_amount: Math.round(percentile(out, .95)), out_count_30d: out.length, as_of: iso });
  }
  return { version: 1, users, accounts, transactions, settings, expenses, recipients, baselines, alerts: [], guides: [], shares: [], requests: {}, links: [{ id: 'link-a-s', owner_user_id: 'user-a', supporter_user_id: 'supporter-s', supporter_name: '이지원', status: 'ACTIVE' }] };
}
