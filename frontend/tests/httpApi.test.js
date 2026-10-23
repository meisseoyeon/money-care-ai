import test from 'node:test';
import assert from 'node:assert/strict';
import { createHttpApi } from '../src/app/httpApi.js';
import { TOKEN_KEY } from '../src/shared/lib/storageKeys.js';
import { seoulDate } from '../src/features/preparation/state.js';

function storage() {
  const data = new Map();
  return { getItem: (key) => data.get(key) ?? null, setItem: (key, value) => data.set(key, value), removeItem: (key) => data.delete(key) };
}

for (const status of [200, 401]) {
  test(`이전 토큰의 늦은 ${status} 응답은 새 체험에 반영하지 않음`, async () => {
    const store = storage(); store.setItem(TOKEN_KEY, 'old');
    let respond;
    const api = createHttpApi('http://test', { storage: store, fetchImpl: async (url, options) => {
      assert.equal(options.headers.Authorization, 'Bearer old');
      return new Promise((resolve) => { respond = resolve; });
    } });
    const pending = api.saveBudget({ daily_living_budget: 20000 });
    store.setItem(TOKEN_KEY, 'new');
    respond(new Response(JSON.stringify(status === 401 ? { detail: '만료' } : { user_id: 'old-user' }), { status }));
    await assert.rejects(pending, (error) => error.status === 409);
    assert.equal(store.getItem(TOKEN_KEY), 'new');
  });
}

test('401 처리용 로컬 정리는 생성 복구나 서버 로그아웃을 호출하지 않음', () => {
  const store = storage();
  store.setItem(TOKEN_KEY, 'expired'); store.setItem('moneycare.api.demo.creation', 'pending');
  const api = createHttpApi('http://test', { storage: store, fetchImpl: () => { throw new Error('호출되면 안 됨'); } });
  api.clearSession();
  assert.equal(store.getItem(TOKEN_KEY), null);
  assert.equal(store.getItem('moneycare.api.demo.creation'), null);
});

test('성공 상태의 잘못된 JSON은 정상 데이터로 취급하지 않음', async () => {
  const api = createHttpApi('http://test', { storage: storage(), fetchImpl: async () => new Response('<html>proxy error</html>') });
  await assert.rejects(api.saveBudget({}), (error) => error.status === 502);
});

test('송금 후 잔액과 서버 거래내역을 다시 읽고 다음 페이지까지 표시', async () => {
  const store = storage(); store.setItem(TOKEN_KEY, 'valid');
  const transactions = [];
  let balance = 800000;
  const api = createHttpApi('http://test', { storage: store, fetchImpl: async (url, options) => {
    const path = new URL(url).pathname, cursor = new URL(url).searchParams.get('cursor');
    assert.equal(options.headers.Authorization, 'Bearer valid');
    let body;
    if (path === '/transfers') {
      const payload = JSON.parse(options.body);
      balance -= payload.amount;
      transactions.unshift({ id: String(transactions.length + 1), amount: payload.amount, balance_after: balance });
      body = { transaction: transactions[0], alert_ids: [] };
    } else if (path === '/demo/me') body = { user: { user_id: 'a' }, account: { current_balance: balance } };
    else if (path === '/supporter-links' || path === '/alert-shares') body = [];
    else if (path === '/demo/recipients') body = [];
    else if (path === '/alerts') body = [{ id: 'alert-1', alert_type: 'NEW_COUNTERPARTY', status: 'NEW' }];
    else if (path === '/transactions') body = { items: cursor ? transactions.slice(1) : transactions.slice(0, 1), next_cursor: !cursor && transactions.length > 1 ? transactions[0].id : null };
    else if (path === '/baselines/current') body = { user_id: 'a', out_count_30d: 0, as_of: new Date().toISOString(), base_date: seoulDate(), calculation_version: 'baseline-v1' };
    else if (path === '/budget-forecasts/latest') body = { id: '1', snapshot_id: '1', user_id: 'a', as_of: new Date().toISOString(), remaining_days: 20, current_balance: balance, scheduled_expense_total: 150000, daily_living_budget: 20000, expected_living_cost: 400000, available_amount: balance - 550000, shortage_amount: Math.max(0, 550000 - balance), calculation_version: 'budget-v1' };
    else throw new Error(`예상하지 않은 경로: ${path}`);
    return new Response(JSON.stringify(body));
  } });
  await api.transfer({ request_id: 'first', counterparty_id: 'demo-payee-1', amount: 120000 });
  await api.transfer({ request_id: 'second', counterparty_id: 'demo-payee-1', amount: 1000 });
  const data = await api.loadData();
  assert.equal(data.account.current_balance, 679000);
  assert.deepEqual(data.transactions, transactions);
  assert.deepEqual(data.alerts.map((a) => a.id), ['alert-1']);
});
