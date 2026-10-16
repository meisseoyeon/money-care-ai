import { AppError, calculateForecast, localDate, validateMoney, won } from '../lib/domain.js';
import { seedDatabase, TEST_PASSWORD } from './fixtures.js';
import { reviewTransfer } from '../lib/transferReview.js';

export const DB_KEY = 'moneycare.frontend.v1.database';
export const SESSION_KEY = 'moneycare.frontend.v1.session';

// 브라우저 시연용입니다. 실제 인증/권한/트랜잭션은 FastAPI에서 보장해야 합니다.
export function createMockApi({ storage, sessionStorage, clock = () => new Date(), delay = 120 }) {
  let queue = Promise.resolve();
  const id = () => globalThis.crypto.randomUUID();
  const read = () => { const raw = storage.getItem(DB_KEY); if (raw) { try { const db = JSON.parse(raw); if (db.version === 1) return db; } catch { /* 재생성 */ } } const db = seedDatabase(clock()); storage.setItem(DB_KEY, JSON.stringify(db)); return db; };
  const pause = () => new Promise((resolve) => setTimeout(resolve, delay));
  const session = () => { try { return JSON.parse(sessionStorage.getItem(SESSION_KEY)); } catch { return null; } };
  const current = (db) => { const s = session(); const u = db.users.find((x) => x.user_id === s?.user_id); if (!u || s.expires_at <= clock().getTime()) throw new AppError('로그인이 필요해요. 다시 로그인해 주세요.', 401); return u; };
  const owner = (db) => { const u = current(db); if (u.role !== 'OWNER') throw new AppError('당사자 계정에서 사용할 수 있어요.', 403); return u; };
  const alertFor = (db, user, alertId) => { const a = db.alerts.find((x) => x.id === alertId && x.user_id === user.user_id); if (!a) throw new AppError('알림을 찾을 수 없어요.', 404); return a; };
  const mutate = (fn) => {
    const run = async () => { await pause(); const perform = () => { const db = read(); const result = fn(db); storage.setItem(DB_KEY, JSON.stringify(db)); return result; }; return typeof window !== 'undefined' && globalThis.navigator?.locks ? globalThis.navigator.locks.request(DB_KEY, perform) : perform(); };
    const result = queue.then(run, run); queue = result.catch(() => {}); return result;
  };
  const addAlert = (db, userId, data) => {
    const old = db.alerts.find((a) => a.user_id === userId && a.dedupe_key === data.dedupe_key);
    if (old) return old;
    const a = { id: id(), user_id: userId, status: 'NEW', user_response: null, created_at: clock().toISOString(), explanation_method: 'FALLBACK', ...data };
    db.alerts.unshift(a); return a;
  };
  const forecastFor = (db, userId) => calculateForecast(db.accounts.find((a) => a.user_id === userId), db.settings.find((s) => s.user_id === userId), db.expenses.filter((e) => e.user_id === userId), clock());
  const budgetAlert = (db, u) => { const f = forecastFor(db, u.user_id); if (f.shortage_amount > 0 && u.monitoring_consented_at && !u.monitoring_revoked_at) addAlert(db, u.user_id, { alert_type: 'BUDGET_SHORTAGE', title: '다음 수입일까지 생활비가 부족할 수 있어요', explanation: `예정된 지출과 생활비를 생각하면 ${won(f.shortage_amount)} 정도 더 필요해요. 나갈 돈을 함께 확인해봐요.`, evidence: f, dedupe_key: `budget:${localDate(clock())}` }); return f; };
  const fallbackGuide = (db, a) => {
    let g = db.guides.find((x) => x.alert_id === a.id);
    if (!g) { g = { id: id(), alert_id: a.id, method: 'FALLBACK', steps: a.alert_type === 'BUDGET_SHORTAGE' ? ['다음 수입일과 나갈 돈을 다시 확인해요.', '지금 꼭 필요한 지출부터 골라봐요.', '어렵다면 도움받을 사람과 함께 살펴봐요.'] : ['추가로 돈을 보내기 전에 잠시 멈춰요.', '원래 알고 있던 연락처로 상대에게 확인해요.', '걱정되면 도움받을 사람에게 이 알림을 보여줘요.'], citations: [], generated_at: clock().toISOString() }; db.guides.push(g); } return g;
  };
  return {
    mode: 'mock',
    async restoreSession() { const db = read(); try { return current(db); } catch { sessionStorage.removeItem(SESSION_KEY); return null; } },
    async login(email, password) { await pause(); const db = read(); const u = db.users.find((x) => x.email.toLowerCase() === email.trim().toLowerCase()); if (!u || password !== TEST_PASSWORD) throw new AppError('이메일과 비밀번호를 확인해 주세요.', 401); sessionStorage.setItem(SESSION_KEY, JSON.stringify({ user_id: u.user_id, expires_at: clock().getTime() + 86400000 })); return u; },
    async logout() { sessionStorage.removeItem(SESSION_KEY); },
    async loadData() {
      await pause(); const db = read(), u = current(db);
      if (u.role === 'SUPPORTER') {
        const shares = db.shares.filter((s) => s.status === 'ACTIVE' && db.links.some((l) => l.id === s.supporter_link_id && l.supporter_user_id === u.user_id && l.status === 'ACTIVE'));
        return { user: u, sharedAlerts: shares.map((s) => { const a = db.alerts.find((x) => x.id === s.alert_id); return { ...a, share_id: s.id, shared_at: s.shared_at, owner_name: db.users.find((x) => x.user_id === a.user_id).display_name, guide: db.guides.find((g) => g.alert_id === a.id) || null }; }) };
      }
      const previousIds = new Set(db.transactions.filter((t) => t.user_id === u.user_id && t.tx_type === 'TRANSFER').map((t) => t.counterparty_id));
      return { user: u, account: db.accounts.find((a) => a.user_id === u.user_id), settings: db.settings.find((s) => s.user_id === u.user_id), expenses: db.expenses.filter((e) => e.user_id === u.user_id), forecast: forecastFor(db, u.user_id), baseline: db.baselines.find((b) => b.user_id === u.user_id), recipients: db.recipients.map((p) => ({ ...p, familiar: previousIds.has(p.id) })), transactions: db.transactions.filter((t) => t.user_id === u.user_id).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at)), alerts: db.alerts.filter((a) => a.user_id === u.user_id), guides: db.guides.filter((g) => db.alerts.some((a) => a.id === g.alert_id && a.user_id === u.user_id)), links: db.links.filter((l) => l.owner_user_id === u.user_id), shares: db.shares.filter((s) => s.owner_user_id === u.user_id) };
    },
    requestTransferHelp(payload) { return mutate((db) => {
      const u = owner(db);
      if (!u.monitoring_consented_at || u.monitoring_revoked_at) throw new AppError('설정에서 모니터링을 켠 뒤 도움을 요청해 주세요.', 403);
      const { request_id, counterparty_id, amount } = payload;
      validateMoney(amount);
      if (!request_id) throw new AppError('요청 식별자가 없어요. 다시 시도해 주세요.');
      const link = db.links.find((l) => l.owner_user_id === u.user_id && l.status === 'ACTIVE');
      if (!link) throw new AppError('연결된 지원자가 없어요. 설정에서 확인해 주세요.', 409);
      const recipient = db.recipients.find((r) => r.id === counterparty_id);
      if (!recipient) throw new AppError('받는 사람을 다시 선택해 주세요.');
      const account = db.accounts.find((a) => a.user_id === u.user_id);
      if (amount > account.current_balance) throw new AppError('통장에 있는 돈보다 많이 보낼 수 없어요.', 409);
      const key = `transfer-help:${u.user_id}:${request_id}`;
      const fingerprint = JSON.stringify({ counterparty_id, amount });
      if (db.requests[key]) {
        if (db.requests[key].fingerprint !== fingerprint) throw new AppError('같은 요청 번호에 다른 송금 정보가 들어왔어요.', 409);
        return db.requests[key].result;
      }
      const review = reviewTransfer({ account, settings: db.settings.find((s) => s.user_id === u.user_id), expenses: db.expenses.filter((e) => e.user_id === u.user_id) }, amount, clock());
      const shortage = review.forecast?.shortage_amount ?? 0;
      const alert = addAlert(db, u.user_id, {
        alert_type: 'LARGE_OUTFLOW', title: '송금 전에 함께 확인해 주세요',
        explanation: `${recipient.name}님에게 ${won(amount)}을 보내기 전에 도움을 요청했어요. 도움 요청 당시의 송금 예정 내용이에요.${shortage > 0 ? ` 이 돈을 보내면 다음 수입일까지 생활비가 ${won(shortage)} 부족할 수 있어요.` : ''}`,
        evidence: { stage: 'BEFORE_TRANSFER', amount, counterparty_name: recipient.name, shortage_amount: shortage },
        dedupe_key: key, status: 'ANSWERED', user_response: 'HELP_REQUESTED', responded_at: clock().toISOString(),
      });
      const share = { id: id(), alert_id: alert.id, supporter_link_id: link.id, owner_user_id: u.user_id, status: 'ACTIVE', shared_at: clock().toISOString(), revoked_at: null };
      db.shares.push(share);
      const result = { alert_id: alert.id, share_id: share.id };
      db.requests[key] = { fingerprint, result };
      return result;
    }); },
    transfer(payload) { return mutate((db) => {
      const u = owner(db); if (!u.monitoring_consented_at || u.monitoring_revoked_at) throw new AppError('설정에서 모니터링을 켠 뒤 가상 송금을 이용해 주세요.', 403);
      const { request_id, counterparty_id, amount } = payload; validateMoney(amount);
      if (!request_id) throw new AppError('요청 식별자가 없어요. 다시 시도해 주세요.');
      const key = `${u.user_id}:${request_id}`, fingerprint = JSON.stringify({ counterparty_id, amount });
      if (db.requests[key]) { if (db.requests[key].fingerprint !== fingerprint) throw new AppError('같은 요청 번호에 다른 송금 정보가 들어왔어요.', 409); return db.requests[key].result; }
      const account = db.accounts.find((a) => a.user_id === u.user_id), p = db.recipients.find((r) => r.id === counterparty_id);
      if (!p) throw new AppError('받는 사람을 다시 선택해 주세요.');
      if (amount > account.current_balance) throw new AppError('통장에 있는 돈보다 많이 보낼 수 없어요.', 409);
      const newRecipient = !db.transactions.some((t) => t.user_id === u.user_id && t.tx_type === 'TRANSFER' && t.counterparty_id === counterparty_id);
      const baseline = db.baselines.find((b) => b.user_id === u.user_id), large = amount > baseline.p95_out_amount;
      account.current_balance -= amount; account.balance_as_of = clock().toISOString();
      const t = { id: id(), user_id: u.user_id, account_id: account.account_id, occurred_at: clock().toISOString(), received_at: clock().toISOString(), direction: 'OUT', amount, balance_after: account.current_balance, tx_type: 'TRANSFER', counterparty_id, description: `${p.name}에게 보냄`, source: 'SYNTHETIC', detection_status: 'COMPLETED' };
      db.transactions.push(t); const alertIds = [];
      if (newRecipient || large) { const a = addAlert(db, u.user_id, { alert_type: large ? 'LARGE_OUTFLOW' : 'NEW_COUNTERPARTY', title: newRecipient && large ? '처음 보내는 상대에게 큰돈을 보냈어요' : large ? '평소보다 큰 금액을 보냈어요' : '처음 보내는 상대에게 돈을 보냈어요', transaction_id: t.id, explanation: `${p.name}님에게 ${won(amount)}을 보냈어요. ${newRecipient ? '이 상대에게는 처음 보내요. ' : ''}${large ? `평소 금액 기준 ${won(baseline.p95_out_amount)}보다 커요. ` : ''}계획한 송금인지 한 번 확인해봐요.`, evidence: { amount, counterparty_name: p.name, is_new_counterparty: newRecipient, p95_out_amount: baseline.p95_out_amount, triggered_rules: [newRecipient && 'NEW_COUNTERPARTY', large && 'LARGE_OUTFLOW'].filter(Boolean) }, dedupe_key: `transaction:${t.id}` }); alertIds.push(a.id); }
      const f = budgetAlert(db, u); const result = { transaction: t, alert_ids: alertIds, forecast: f }; db.requests[key] = { fingerprint, result }; return result;
    }); },
    markSeen(alertId) { return mutate((db) => { const u = owner(db), a = alertFor(db, u, alertId); if (a.status === 'NEW') { a.status = 'SEEN'; a.seen_at = clock().toISOString(); } return a; }); },
    respond(alertId, response) { return mutate((db) => {
      const u = owner(db), a = alertFor(db, u, alertId);
      if (!['PLANNED','UNSURE','HELP_REQUESTED'].includes(response)) throw new AppError('응답을 다시 선택해 주세요.');
      if (response === 'HELP_REQUESTED') {
        const l = db.links.find((x) => x.owner_user_id === u.user_id && x.status === 'ACTIVE'); if (!l) throw new AppError('연결된 지원자가 없어요. 설정에서 확인해 주세요.', 409);
        let share = db.shares.find((x) => x.alert_id === a.id && x.supporter_link_id === l.id);
        if (!share) db.shares.push({ id: id(), alert_id: a.id, supporter_link_id: l.id, owner_user_id: u.user_id, status: 'ACTIVE', shared_at: clock().toISOString(), revoked_at: null });
        else if (share.status !== 'ACTIVE') { share.status = 'ACTIVE'; share.shared_at = clock().toISOString(); share.revoked_at = null; }
      }
      a.status = 'ANSWERED'; a.user_response = response; a.seen_at ||= clock().toISOString(); a.responded_at = clock().toISOString();
      return a;
    }); },
    generateGuide(alertId) { return mutate((db) => { const u = owner(db), a = alertFor(db, u, alertId); return fallbackGuide(db, a); }); },
    saveBudget(settings) { return mutate((db) => {
      const u = owner(db); validateMoney(settings.daily_living_budget, { allowZero: true }); validateMoney(settings.expected_income_amount, { allowZero: true });
      if (!/^\d{4}-\d{2}-\d{2}$/.test(settings.next_income_date) || settings.next_income_date < localDate(clock())) throw new AppError('다음 수입일은 오늘 이후로 선택해 주세요.');
      Object.assign(db.settings.find((s) => s.user_id === u.user_id), { next_income_date: settings.next_income_date, expected_income_amount: settings.expected_income_amount, daily_living_budget: settings.daily_living_budget }); return budgetAlert(db, u);
    }); },
    saveExpense(payload) { return mutate((db) => { const u = owner(db); validateMoney(payload.amount); if (!payload.title?.trim() || payload.title.trim().length > 100 || !/^\d{4}-\d{2}-\d{2}$/.test(payload.due_date) || !['PLANNED','PAID','CANCELLED'].includes(payload.status)) throw new AppError('이름·금액·예정일·상태를 확인해 주세요.'); const old = payload.id ? db.expenses.find((e) => e.id === payload.id && e.user_id === u.user_id) : null; if (payload.id && !old) throw new AppError('지출을 찾을 수 없어요.', 404); const data = { title: payload.title.trim(), amount: payload.amount, due_date: payload.due_date, status: payload.status }; if (old) Object.assign(old, data); else db.expenses.push({ id: id(), user_id: u.user_id, ...data }); budgetAlert(db, u); }); },
    setMonitoring(enabled) { return mutate((db) => { const u = owner(db); if (enabled && (!u.monitoring_consented_at || u.monitoring_revoked_at)) { u.monitoring_consented_at = clock().toISOString(); u.monitoring_revoked_at = null; } else if (!enabled && u.monitoring_consented_at && !u.monitoring_revoked_at) u.monitoring_revoked_at = clock().toISOString(); return u; }); },
    revokeShare(shareId) { return mutate((db) => { const u = owner(db), s = db.shares.find((x) => x.id === shareId && x.owner_user_id === u.user_id); if (!s) throw new AppError('공유 내역을 찾을 수 없어요.', 404); s.status = 'REVOKED'; s.revoked_at = clock().toISOString(); }); },
    setLink(linkId, active) { return mutate((db) => { const u = owner(db), l = db.links.find((x) => x.id === linkId && x.owner_user_id === u.user_id); if (!l) throw new AppError('연결을 찾을 수 없어요.', 404); l.status = active ? 'ACTIVE' : 'REVOKED'; if (!active) for (const s of db.shares.filter((s) => s.supporter_link_id === l.id && s.status === 'ACTIVE')) { s.status = 'REVOKED'; s.revoked_at = clock().toISOString(); } }); },
    async resetData() { await queue; storage.setItem(DB_KEY, JSON.stringify(seedDatabase(clock()))); sessionStorage.removeItem(SESSION_KEY); },
  };
}
