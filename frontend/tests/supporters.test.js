import test from 'node:test';
import assert from 'node:assert/strict';
import { createHttpApi } from '../src/app/httpApi.js';

const shared = [{ share_id: 1, alert_id: 'alert-1', owner_name: '체험 사용자', explanation: '함께 확인해 주세요.' }];

test('지원자는 공유 API만 조회하고 당사자의 계좌·생활비·거래 API를 호출하지 않음', async () => {
  const paths = [];
  const api = createHttpApi('http://test', { storage: { getItem: () => 'supporter-token' }, fetchImpl: async (url) => {
    const path = new URL(url).pathname;
    paths.push(path);
    if (path === '/demo/me') return Response.json({ user: { user_id: 'supporter1', role: 'SUPPORTER' } });
    if (path === '/shared-alerts') return Response.json(shared);
    throw new Error(`지원자에게 불필요한 요청: ${path}`);
  } });
  const data = await api.loadData();
  assert.deepEqual(paths, ['/demo/me', '/shared-alerts']);
  assert.deepEqual(data.sharedAlerts, shared);
  assert.deepEqual(data.transactions, []);
  assert.equal(data.forecast, null);
});

test('철회 후 다시 불러오면 이전에 표시한 공유를 제거', async () => {
  let revoked = false;
  const api = createHttpApi('http://test', { storage: { getItem: () => 'token' }, fetchImpl: async (url, options) => {
    const path = new URL(url).pathname;
    if (path === '/demo/me') return Response.json({ user: { user_id: 'supporter1', role: 'SUPPORTER' } });
    if (path === '/shared-alerts') return Response.json(revoked ? [] : shared);
    throw new Error(`예상하지 않은 요청: ${options.method} ${path}`);
  } });
  assert.equal((await api.loadData()).sharedAlerts.length, 1);
  revoked = true;
  assert.deepEqual((await api.loadData()).sharedAlerts, []);
});

test('철회 요청은 공유와 연결의 전용 API를 사용', async () => {
  const calls = [];
  const api = createHttpApi('http://test', { storage: { getItem: () => 'token' }, fetchImpl: async (url, options) => {
    calls.push([new URL(url).pathname, options.method]);
    return Response.json({ status: 'REVOKED' });
  } });
  await api.revokeShare(3);
  await api.setLink(2, false);
  assert.deepEqual(calls, [['/alert-shares/3/revoke', 'POST'], ['/supporter-links/2/revoke', 'POST']]);
});
