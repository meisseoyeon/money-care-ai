import test from 'node:test';
import assert from 'node:assert/strict';
import { createReloadController } from '../src/app/reload.js';
import { isPreparationReady, seoulDate, visibleForecast } from '../src/features/preparation/state.js';

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function fixture(load) {
  const date = seoulDate();
  const ready = { status: 'READY', source: 'api', baselineDate: date, forecastDate: date };
  const state = { preparation: ready, data: { forecast: { id: 'old', available_amount: 250000 } }, starts: 0, failures: [] };
  const controller = createReloadController({ load,
    onChecking: () => { state.starts += 1; state.preparation = { status: 'CHECKING' }; },
    onSuccess: (data) => { state.data = data; state.preparation = data.preparation ?? ready; },
    onError: (error) => { state.failures.push(error); state.preparation = { status: 'ERROR' }; },
  });
  return { controller, state, ready };
}

test('자동 갱신 중 마지막 정상 생활비와 송금 준비 상태를 유지', async () => {
  const request = deferred();
  const { controller, state } = fixture(() => request.promise);
  const pending = controller.reload({ background: true });
  await Promise.resolve();
  assert.equal(state.starts, 0);
  assert.equal(isPreparationReady(state.preparation), true);
  assert.equal(visibleForecast(state.data, state.preparation).available_amount, 250000);
  request.resolve({ forecast: { id: 'new', available_amount: 200000 } });
  await pending;
  assert.equal(state.data.forecast.id, 'new');
});

test('느린 자동 조회 중 주기·포커스 이벤트가 반복돼도 요청 하나로 끝남', async () => {
  const request = deferred();
  let calls = 0;
  const { controller, state } = fixture(() => { calls += 1; return request.promise; });
  const requests = Array.from({ length: 10 }, () => controller.reload({ background: true }));
  assert.ok(requests.every((promise) => promise === requests[0]));
  await Promise.resolve();
  assert.equal(calls, 1);
  request.resolve({ forecast: { id: 'latest' } });
  await Promise.all(requests);
  assert.equal(state.data.forecast.id, 'latest');
  assert.equal(state.starts, 0);
});

test('최초·명시적 조회는 확인 중 상태와 송금 차단을 유지', async () => {
  const request = deferred();
  const { controller, state } = fixture(() => request.promise);
  const pending = controller.reload();
  assert.equal(state.preparation.status, 'CHECKING');
  assert.equal(isPreparationReady(state.preparation), false);
  assert.equal(visibleForecast(state.data, state.preparation), null);
  request.resolve({ forecast: { id: 'ready' } });
  await pending;
  assert.equal(state.preparation.status, 'READY');
});

test('송금 시작 후 예전 자동 조회는 반영하지 않고 변경 후 새 조회를 사용', async () => {
  const old = deferred(), fresh = deferred();
  let count = 0;
  const { controller, state } = fixture(() => (++count === 1 ? old.promise : fresh.promise));
  const oldRead = controller.reload({ background: true });
  await Promise.resolve();
  controller.invalidate();
  const freshRead = controller.reload();
  await Promise.resolve();
  fresh.resolve({ forecast: { id: 'after-transfer', current_balance: 500000 } });
  await freshRead;
  old.resolve({ forecast: { id: 'before-transfer', current_balance: 800000 } });
  await oldRead;
  assert.equal(state.data.forecast.id, 'after-transfer');
  assert.equal(state.starts, 1);
});

test('송금 저장 중에는 자동 조회를 건너뛰고 완료 후 조회 가능', async () => {
  let busy = true, calls = 0;
  const controller = createReloadController({ load: async () => { calls += 1; return {}; },
    canBackground: () => !busy, onChecking() {}, onSuccess() {}, onError() {},
  });
  assert.equal(await controller.reload({ background: true }), null);
  assert.equal(calls, 0);
  busy = false;
  await controller.reload({ background: true });
  assert.equal(calls, 1);
});

test('실제 조회 오류는 숨기지 않으며 실패 후 재시도 가능', async () => {
  let calls = 0;
  const { controller, state } = fixture(() => {
    if (++calls === 1) throw new Error('connection failed');
    return { forecast: { id: 'recovered' } };
  });
  await assert.rejects(controller.reload({ background: true }), /connection failed/);
  assert.equal(state.preparation.status, 'ERROR');
  assert.equal(visibleForecast(state.data, state.preparation), null);
  await controller.reload({ background: true });
  assert.equal(state.preparation.status, 'READY');
  assert.equal(state.data.forecast.id, 'recovered');
});

test('세션 변경 후 예전 조회의 인증 오류가 새 세션을 종료하지 않음', async () => {
  const request = deferred();
  const { controller, state } = fixture(() => request.promise);
  const pending = controller.reload({ background: true });
  await Promise.resolve();
  controller.invalidate();
  request.reject(Object.assign(new Error('old session'), { status: 401 }));
  await assert.rejects(pending);
  assert.equal(state.failures.length, 0);
  assert.equal(state.preparation.status, 'READY');
});
