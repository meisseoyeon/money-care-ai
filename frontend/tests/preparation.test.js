import test from 'node:test';
import assert from 'node:assert/strict';
import { createPreparationApi } from '../src/features/preparation/api.js';
import { effectivePreparation, isPreparationReady, seoulDate, visibleForecast } from '../src/features/preparation/state.js';
import { createHttpApi } from '../src/app/httpApi.js';
import { reviewSource, reviewTransfer } from '../src/features/transfers/review.js';

const now = new Date('2026-10-21T06:00:00Z');
const baseline = { user_id: 'user1', base_date: '2026-10-21', as_of: now.toISOString(), calculation_version: 'baseline-v1', out_count_30d: 29 };
const forecast = { id: '12', snapshot_id: '11', user_id: 'user1', as_of: now.toISOString(), remaining_days: 20, current_balance: 800000, scheduled_expense_total: 150000, daily_living_budget: 20000, expected_living_cost: 400000, available_amount: 250000, shortage_amount: 0, calculation_version: 'budget-v1' };
const httpError = (status) => Object.assign(new Error('test error'), { status });
const load = (a = baseline, b = forecast) => createPreparationApi(async (path) => {
  const value = path === '/baselines/current' ? a : b;
  if (value instanceof Error) throw value;
  return value;
}).loadPreparation();

test('서버 결과 두 개가 유효해야 준비 완료이며 서버 금액을 보존', async () => {
  const result = await load();
  assert.equal(result.preparation.status, 'READY');
  assert.equal(result.forecast, forecast);
  assert.equal(isPreparationReady(result.preparation, now), true);
});

for (const [status, expected] of [[404, 'MISSING'], [409, 'STALE'], [503, 'ERROR']]) {
  test(`생활비 조회 ${status}면 ${expected} 상태이고 송금을 허용하지 않음`, async () => {
    const result = await load(baseline, httpError(status));
    assert.equal(result.preparation.status, expected);
    assert.equal(result.forecast, null);
    assert.equal(isPreparationReady(result.preparation, now), false);
  });
}

test('통계만 없으면 송금은 막지만 유효한 서버 생활비 결과를 보존', async () => {
  const result = await load(httpError(404), forecast);
  assert.equal(result.preparation.status, 'MISSING');
  assert.equal(visibleForecast(result, result.preparation, now), forecast);
  assert.equal(isPreparationReady(result.preparation, now), false);
});

test('다른 조회가 404여도 인증 만료 401을 숨기지 않음', async () => {
  await assert.rejects(load(httpError(404), httpError(401)), (error) => error.status === 401);
});

test('잘못된 형식·금액·계산값을 준비 완료로 취급하지 않음', async () => {
  for (const update of [{ remaining_days: -1 }, { current_balance: '800000' }, { available_amount: 1 }, { shortage_amount: -1 }, { as_of: 'invalid' }, { id: null }]) {
    const result = await load(baseline, { ...forecast, ...update });
    assert.equal(result.preparation.status, 'ERROR', JSON.stringify(update));
    assert.equal(result.forecast, null);
  }
});

test('한국 날짜가 바뀌면 마지막 READY 상태도 송금을 허용하지 않음', async () => {
  const { preparation } = await load();
  assert.equal(seoulDate('2026-10-21T15:00:00Z'), '2026-10-22');
  assert.equal(isPreparationReady(preparation, new Date('2026-10-21T14:59:59Z')), true);
  assert.equal(effectivePreparation(preparation, new Date('2026-10-21T15:00:00Z')).status, 'STALE');
  assert.equal(isPreparationReady(preparation, new Date('2026-10-21T15:00:00Z')), false);
});

test('조회 중·실패·오래된 상태에서는 이전 생활비 금액을 숨김', async () => {
  const result = await load();
  for (const status of ['CHECKING', 'STALE', 'ERROR']) assert.equal(visibleForecast(result, { status }, now), null);
  assert.equal(visibleForecast(result, result.preparation, now), forecast);
});

test('mock 모드의 준비 완료와 기존 시연을 유지', () => {
  const preparation = { status: 'READY', source: 'mock' };
  assert.equal(isPreparationReady(preparation, now), true);
  assert.equal(visibleForecast({ forecast }, preparation, now), forecast);
});

test('계좌와 결과가 다른 시점이면 재계산 없이 송금을 차단', async () => {
  const store = { getItem: () => 'token' };
  const api = createHttpApi('http://test', { storage: store, fetchImpl: async (url) => {
    const path = new URL(url).pathname;
    const data = { '/demo/me': { user: { user_id: 'user1' }, account: { current_balance: 700000 } }, '/demo/recipients': [], '/transactions': { items: [] }, '/baselines/current': baseline, '/budget-forecasts/latest': forecast }[path];
    return new Response(JSON.stringify(data));
  } });
  const data = await api.loadData();
  assert.equal(data.preparation.status, 'STALE');
  assert.equal(data.forecast, null);
});

test('API 송금 미리보기는 서버 생활비 입력을 기준으로 하고 원본 결과를 변경하지 않음', () => {
  const data = { account: { current_balance: 800000 }, forecast, preparation: { source: 'api' }, settings: { next_income_date: 'invalid' } };
  const source = reviewSource(data);
  const result = reviewTransfer(data, 300000, now);
  assert.equal(result.forecast.shortage_amount, 50000);
  assert.equal(result.forecast.expected_living_cost, 400000);
  assert.equal(forecast.available_amount, 250000);
  assert.equal(reviewSource(data), source);
  assert.notEqual(reviewSource({ ...data, forecast: { ...forecast, id: '13' } }), source);
});

test('다른 사용자 결과나 다른 시점의 생활비 설정을 표시하지 않음', async () => {
  for (const kind of ['owner', 'settings']) {
    const api = createHttpApi('http://test', { storage: { getItem: () => 'token' }, fetchImpl: async (url) => {
      const path = new URL(url).pathname;
      const context = { user: { user_id: kind === 'owner' ? 'other-user' : 'user1' }, account: { current_balance: 800000 },
        ...(kind === 'settings' ? { settings: { daily_living_budget: 30000, next_income_date: '2026-11-10' } } : {}) };
      const body = { '/demo/me': context, '/demo/recipients': [], '/transactions': { items: [] }, '/baselines/current': baseline, '/budget-forecasts/latest': forecast }[path];
      return new Response(JSON.stringify(body));
    } });
    const data = await api.loadData();
    assert.equal(data.preparation.status, kind === 'owner' ? 'ERROR' : 'STALE');
    assert.equal(data.forecast, null);
  }
});
