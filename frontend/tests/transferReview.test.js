import test from 'node:test';
import assert from 'node:assert/strict';
import { reviewTransfer } from '../src/lib/transferReview.js';
import { createMockApi } from '../src/services/mockApi.js';
import { TEST_PASSWORD } from '../src/services/fixtures.js';

const now = new Date('2026-10-16T10:00:00.000Z');
function memoryStorage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
}
function setup() {
  return createMockApi({ storage: memoryStorage(), sessionStorage: memoryStorage(), clock: () => new Date(now), delay: 0 });
}

test('10만 원 초과만 사전 확인 대상이고 미리보기는 잔액과 거래를 변경하지 않음', async () => {
  const api = setup();
  await api.login('user-a@example.test', TEST_PASSWORD);
  const data = await api.loadData(), before = structuredClone(data);
  assert.equal(reviewTransfer(data, 100000, now).requiresReview, false);
  assert.equal(reviewTransfer(data, 100001, now).requiresReview, true);
  assert.deepEqual(data, before);
  const after = await api.loadData();
  assert.equal(after.account.current_balance, 800000);
  assert.equal(after.transactions.length, 90);
  assert.equal(after.alerts.length, 0);
});

test('송금 후 예상 잔액으로 생활비 부족 여부 계산', async () => {
  const api = setup();
  await api.login('user-a@example.test', TEST_PASSWORD);
  const data = await api.loadData();
  assert.equal(reviewTransfer(data, 150000, now).forecast.shortage_amount, 0);
  const review = reviewTransfer(data, 300000, now);
  assert.equal(review.projectedBalance, 500000);
  assert.equal(review.forecast.shortage_amount, 50000);
});

test('사전 도움 요청은 중복 공유나 송금 없이 지원자에게 예정 내용만 공유', async () => {
  const api = setup();
  await api.login('user-a@example.test', TEST_PASSWORD);
  const payload = { request_id: 'review-1', counterparty_id: 'payee-5', amount: 300000 };
  const first = await api.requestTransferHelp(payload);
  assert.deepEqual(await api.requestTransferHelp(payload), first);
  const data = await api.loadData();
  assert.equal(data.account.current_balance, 800000);
  assert.equal(data.transactions.length, 90);
  assert.equal(data.shares.length, 1);
  assert.equal(data.alerts[0].evidence.stage, 'BEFORE_TRANSFER');
  assert.equal(data.alerts[0].transaction_id, undefined);
  assert.equal(data.alerts[0].evidence.shortage_amount, 50000);
  await api.login('supporter@example.test', TEST_PASSWORD);
  const shared = await api.loadData();
  assert.equal(shared.sharedAlerts.length, 1);
  assert.equal(shared.transactions, undefined);
  assert.equal(shared.sharedAlerts[0].evidence.amount, 300000);
  await api.login('user-a@example.test', TEST_PASSWORD);
  await api.transfer(payload);
  assert.equal((await api.loadData()).account.current_balance, 500000);
});

test('연결된 지원자가 없으면 공유를 생성하거나 잔액을 변경하지 않음', async () => {
  const api = setup();
  await api.login('user-b@example.test', TEST_PASSWORD);
  await assert.rejects(api.requestTransferHelp({ request_id: 'no-link', counterparty_id: 'payee-1', amount: 300000 }), { status: 409 });
  const data = await api.loadData();
  assert.equal(data.account.current_balance, 800000);
  assert.equal(data.shares.length, 0);
  assert.equal(data.alerts.length, 0);
});
