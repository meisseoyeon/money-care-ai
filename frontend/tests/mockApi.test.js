import test from 'node:test';
import assert from 'node:assert/strict';
import { createMockApi } from '../src/services/mockApi.js';
import { seedDatabase, TEST_PASSWORD } from '../src/services/fixtures.js';
import { calculateForecast, localDate, addDays } from '../src/lib/domain.js';

const fixed = new Date('2026-10-16T10:00:00.000Z');
function memoryStorage() { const data = new Map(); return { getItem: (k) => data.get(k) ?? null, setItem: (k,v) => data.set(k,v), removeItem: (k) => data.delete(k) }; }
function setup() { const storage = memoryStorage(), sessionStorage = memoryStorage(); return createMockApi({ storage, sessionStorage, clock: () => new Date(fixed), delay: 0 }); }
const loginA = (api) => api.login('user-a@example.test', TEST_PASSWORD);

test('초기 30일 거래의 잔액 연속성과 마지막 잔액 80만 원', () => {
  const db = seedDatabase(fixed);
  for (const account of db.accounts) {
    const history = db.transactions.filter((t) => t.account_id === account.account_id);
    assert.equal(history.length, 90);
    for (let i=1; i<history.length; i++) assert.equal(history[i].balance_after, history[i-1].balance_after + (history[i].direction === 'IN' ? history[i].amount : -history[i].amount));
    assert.equal(history.at(-1).balance_after, 800000); assert.equal(account.current_balance, 800000);
  }
});
test('틀린 비밀번호는 로그인 불가', async () => { const api=setup(); await assert.rejects(api.login('user-a@example.test','wrong'), { status:401 }); });
test('초기 여유 금액 25만 원, 납부 완료 지출 제외', async () => {
  const api=setup(); await loginA(api); let d=await api.loadData(); assert.equal(d.forecast.available_amount,250000);
  await api.saveExpense({ ...d.expenses[0], status:'PAID' }); d=await api.loadData(); assert.equal(d.forecast.scheduled_expense_total,50000); assert.equal(d.forecast.available_amount,350000);
});
test('같은 요청 재전송은 한 번만 차감하고 다른 payload 충돌', async () => {
  const api=setup(); await loginA(api); const p={request_id:'same',counterparty_id:'payee-5',amount:300000};
  const [a,b]=await Promise.all([api.transfer(p),api.transfer(p)]); assert.equal(a.transaction.id,b.transaction.id);
  const d=await api.loadData(); assert.equal(d.account.current_balance,500000); assert.equal(d.transactions.length,91); assert.equal(d.forecast.shortage_amount,50000);
  assert.equal(d.alerts.filter((x)=>x.transaction_id===a.transaction.id).length,1);
  await assert.rejects(api.transfer({...p,amount:400000}),{status:409});
});
test('동시 송금의 합계가 잔액을 넘으면 한 건만 성공', async () => {
  const api=setup(); await loginA(api); const r=await Promise.allSettled([api.transfer({request_id:'x',counterparty_id:'payee-1',amount:500000}),api.transfer({request_id:'y',counterparty_id:'payee-2',amount:500000})]);
  assert.equal(r.filter((x)=>x.status==='fulfilled').length,1); assert.equal((await api.loadData()).account.current_balance,300000);
});
test('평소 상대 소액 송금은 알림이 생기지 않음', async () => { const api=setup(); await loginA(api); const r=await api.transfer({request_id:'normal',counterparty_id:'payee-1',amount:10000}); assert.deepEqual(r.alert_ids,[]); assert.equal((await api.loadData()).alerts.length,0); });
test('처음 보내는 상대는 첫 송금만 신규로 판단', async () => { const api=setup(); await loginA(api); await api.transfer({request_id:'new1',counterparty_id:'payee-5',amount:10000}); const r=await api.transfer({request_id:'new2',counterparty_id:'payee-5',amount:10000}); assert.equal(r.alert_ids.length,0); });
test('당사자 B는 A 알림에 응답할 수 없음', async () => { const api=setup(); await loginA(api); const r=await api.transfer({request_id:'risk',counterparty_id:'payee-5',amount:300000}); await api.login('user-b@example.test',TEST_PASSWORD); assert.equal((await api.loadData()).alerts.length,0); await assert.rejects(api.respond(r.alert_ids[0],'PLANNED'),{status:404}); });
test('도움 요청 반복에도 공유 한 건, 지원자에게 공유 알림만 노출', async () => {
  const api=setup(); await loginA(api); const r=await api.transfer({request_id:'risk',counterparty_id:'payee-5',amount:300000}); const id=r.alert_ids[0];
  await api.respond(id,'HELP_REQUESTED'); await api.respond(id,'HELP_REQUESTED'); await api.generateGuide(id); assert.equal((await api.loadData()).shares.length,1);
  await api.login('supporter@example.test',TEST_PASSWORD); const d=await api.loadData(); assert.equal(d.sharedAlerts.length,1); assert.equal(d.transactions,undefined); assert.equal(d.sharedAlerts[0].guide.method,'FALLBACK'); await assert.rejects(api.transfer({request_id:'bad',counterparty_id:'payee-1',amount:1}),{status:403});
});
test('연결 철회 후 재연결해도 과거 공유는 부활하지 않음', async () => {
  const api=setup(); await loginA(api); const r=await api.transfer({request_id:'risk',counterparty_id:'payee-5',amount:300000}); await api.respond(r.alert_ids[0],'HELP_REQUESTED');
  await api.setLink('link-a-s',false); await api.setLink('link-a-s',true); await api.login('supporter@example.test',TEST_PASSWORD); assert.equal((await api.loadData()).sharedAlerts.length,0);
});
test('모니터링 철회 후 송금 차단, 반복 철회는 시각 유지', async () => { const api=setup(); await loginA(api); const a=await api.setMonitoring(false),b=await api.setMonitoring(false); assert.equal(a.monitoring_revoked_at,b.monitoring_revoked_at); await assert.rejects(api.transfer({request_id:'off',counterparty_id:'payee-1',amount:1}),{status:403}); });
test('다음 수입일 당일 지출은 계산 기간에서 제외', () => { const account={user_id:'x',current_balance:100000};const next=localDate(addDays(fixed,2));const f=calculateForecast(account,{next_income_date:next,daily_living_budget:10000},[{status:'PLANNED',amount:50000,due_date:next}],fixed);assert.equal(f.expected_living_cost,20000);assert.equal(f.scheduled_expense_total,0); });
