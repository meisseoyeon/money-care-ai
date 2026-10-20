import test from 'node:test';
import assert from 'node:assert/strict';
import { createDemoSessions, DEMO_CREATION_KEY, DEMO_TOKEN_KEY } from '../src/services/demoSessions.js';
import { AppError } from '../src/lib/domain.js';

const payload = { acknowledged: true, monitoring_consented: true };
function storage() { const data = new Map(); return { getItem: (k) => data.get(k) ?? null, setItem: (k,v) => data.set(k,v), removeItem: (k) => data.delete(k) }; }
const success = { access_token: 'signed-demo-token', user: { user_id: 'demo-a', role: 'OWNER' } };

test('연속 클릭은 한 생성 요청으로 합치고 토큰을 저장', async () => {
  let calls = 0;
  const store = storage();
  const client = createDemoSessions({ storage: store, request: async () => { calls++; await new Promise((r) => setTimeout(r, 5)); return success; } });
  const [a,b] = await Promise.all([client.start(payload), client.start(payload)]);
  assert.equal(calls, 1); assert.deepEqual(a,b);
  assert.equal(store.getItem(DEMO_TOKEN_KEY), success.access_token);
  assert.equal(store.getItem(DEMO_CREATION_KEY), null);
});

test('응답 유실 뒤 새로고침하여 재시도해도 같은 생성 키 사용', async () => {
  const store = storage(), keys = [];
  const first = createDemoSessions({ storage: store, request: async (path, options) => { keys.push(options.headers['Idempotency-Key']); throw new AppError('통신 실패', 503); } });
  await assert.rejects(first.start(payload));
  const afterRefresh = createDemoSessions({ storage: store, request: async (path, options) => { keys.push(options.headers['Idempotency-Key']); return success; } });
  await afterRefresh.start(payload);
  assert.equal(keys[0], keys[1]);
});

test('새로고침 복원은 생성 API를 호출하지 않고 기존 토큰으로 내 정보 조회', async () => {
  const store = storage(); store.setItem(DEMO_TOKEN_KEY, 'existing');
  const paths = [];
  const client = createDemoSessions({ storage: store, request: async (path) => { paths.push(path); return { user: success.user }; } });
  assert.deepEqual(await client.restore(), success.user);
  assert.deepEqual(paths, ['/demo/me']);
});

test('만료된 토큰을 지우지만 일시적인 서버 오류로는 토큰을 지우지 않음', async () => {
  const store = storage(); store.setItem(DEMO_TOKEN_KEY, 'existing');
  const temporary = createDemoSessions({ storage: store, request: async () => { throw new AppError('일시 오류',503); } });
  await assert.rejects(temporary.restore()); assert.equal(store.getItem(DEMO_TOKEN_KEY), 'existing');
  const expired = createDemoSessions({ storage: store, request: async () => { throw new AppError('만료',401); } });
  assert.equal(await expired.restore(), null); assert.equal(store.getItem(DEMO_TOKEN_KEY), null);
});

test('재시작은 별도 생성 키와 restart 플래그로 새 토큰을 교체', async () => {
  const store = storage(), calls = [];
  let count = 0;
  const client = createDemoSessions({ storage: store, request: async (path, options) => { calls.push(options); return { ...success, access_token: `token-${++count}` }; } });
  await client.start(payload); await client.start({ ...payload, restart: true });
  assert.notEqual(calls[0].headers['Idempotency-Key'], calls[1].headers['Idempotency-Key']);
  assert.equal(calls[1].body.restart, true); assert.equal(store.getItem(DEMO_TOKEN_KEY), 'token-2');
});

test('서로 다른 브라우저 저장소는 토큰과 생성 키를 공유하지 않음', async () => {
  const a = storage(), b = storage();
  await createDemoSessions({ storage:a, request:async () => success }).start(payload);
  const other = createDemoSessions({ storage:b, request:async () => { throw new Error('호출되면 안 됨'); } });
  assert.equal(await other.restore(), null); assert.equal(b.getItem(DEMO_TOKEN_KEY), null);
});

test('재시작 응답 유실 뒤 복원은 기존 토큰 조회보다 같은 생성 요청을 먼저 복구', async () => {
  const store = storage(); store.setItem(DEMO_TOKEN_KEY, 'old-token');
  let originalKey;
  const first = createDemoSessions({ storage: store, request: async (path, options) => { originalKey = options.headers['Idempotency-Key']; throw new AppError('응답 유실', 503); } });
  await assert.rejects(first.start({ ...payload, restart: true }));
  const paths = [];
  const reloaded = createDemoSessions({ storage: store, request: async (path, options) => {
    paths.push(path);
    if (path === '/demo/sessions') { assert.equal(options.headers['Idempotency-Key'], originalKey); return success; }
    assert.equal(store.getItem(DEMO_TOKEN_KEY), success.access_token);
    return { user: success.user };
  } });
  assert.deepEqual(await reloaded.restore(), success.user);
  assert.deepEqual(paths, ['/demo/sessions','/demo/me']);
});

test('첫 생성 응답 유실도 저장된 요청으로 복구하며 새로운 키를 만들지 않음', async () => {
  const store = storage();
  const first = createDemoSessions({ storage: store, request: async () => { throw new AppError('응답 유실',503); } });
  await assert.rejects(first.start(payload));
  const pending = JSON.parse(store.getItem(DEMO_CREATION_KEY));
  const reloaded = createDemoSessions({ storage: store, request: async (path, options) => {
    if (path === '/demo/sessions') { assert.equal(options.headers['Idempotency-Key'], pending.key); return success; }
    return { user: success.user };
  } });
  assert.deepEqual(await reloaded.restore(), success.user);
});

test('손상된 복구 데이터는 사용자 생성 없이 제거', async () => {
  for (const bad of ['broken', JSON.stringify({fingerprint:'null'}), JSON.stringify({fingerprint:'{}'})]) {
    const store = storage(); store.setItem(DEMO_CREATION_KEY, bad);
    const client = createDemoSessions({ storage: store, request: async () => { throw new Error('사용자를 생성하면 안 됨'); } });
    assert.equal(await client.restore(), null);
    assert.equal(store.getItem(DEMO_CREATION_KEY), null);
  }
});
