import test from 'node:test';
import assert from 'node:assert/strict';
import { createAuthSessions } from '../src/features/auth/session.js';
import { TOKEN_KEY } from '../src/shared/lib/storageKeys.js';
import { AppError } from '../src/shared/lib/errors.js';

function storage() { const data = new Map(); return { getItem: (k) => data.get(k) ?? null, setItem: (k,v) => data.set(k,v), removeItem: (k) => data.delete(k) }; }
const success = { access_token: 'signed-token', user: { user_id: 'user1', role: 'OWNER' } };

test('아이디 비밀번호를 보내고 토큰만 저장하며 새로고침은 기존 세션을 조회', async () => {
  const store = storage(), calls = [];
  const client = createAuthSessions({ storage: store, request: async (path, options) => { calls.push([path, options]); return path === '/auth/login' ? success : {user: success.user}; } });
  assert.deepEqual(await client.login('user1','demo1234!'), success.user);
  assert.deepEqual(calls[0], ['/auth/login',{method:'POST',body:{username:'user1',password:'demo1234!'}}]);
  assert.equal(store.getItem(TOKEN_KEY), success.access_token);
  assert.deepEqual(await client.restore(), success.user);
  assert.equal(calls[1][0], '/auth/me');
});

test('잘못된 비밀번호는 토큰을 저장하지 않음', async () => {
  const store = storage();
  const client = createAuthSessions({ storage: store, request: async () => {throw new AppError('잘못된 비밀번호',401);} });
  await assert.rejects(client.login('user1','wrong'));
  assert.equal(store.getItem(TOKEN_KEY),null);
});

test('연속 로그인은 요청 하나만 보내고 비밀번호를 저장하지 않음', async () => {
  let resolve, calls=0;
  const store=storage();
  const client=createAuthSessions({storage:store,request:async()=>{calls++;return new Promise(r=>{resolve=r;});}});
  const first=client.login('user1','demo1234!');
  await assert.rejects(client.login('user1','demo1234!'),e=>e.status===409);
  resolve(success); await first;
  assert.equal(calls,1); assert.equal(store.getItem('password'),null);
});

test('만료는 로컬 토큰을 지우고 일시 오류는 기존 토큰을 유지', async () => {
  const store=storage();store.setItem(TOKEN_KEY,'existing');
  const temporary=createAuthSessions({storage:store,request:async()=>{throw new AppError('일시 오류',503);}});
  await assert.rejects(temporary.restore());assert.equal(store.getItem(TOKEN_KEY),'existing');
  const expired=createAuthSessions({storage:store,request:async()=>{throw new AppError('만료',401);}});
  assert.equal(await expired.restore(),null);assert.equal(store.getItem(TOKEN_KEY),null);
});

test('로그아웃은 현재 세션만 폐기하고 토큰을 지움', async () => {
  const store=storage();store.setItem(TOKEN_KEY,'existing');const calls=[];
  const client=createAuthSessions({storage:store,request:async(path,options)=>{calls.push([path,options]);}});
  await client.logout();assert.deepEqual(calls,[['/auth/logout',{method:'POST'}]]);assert.equal(store.getItem(TOKEN_KEY),null);
});

test('로그아웃 통신 실패는 재시도할 토큰을 유지하고 만료 응답은 정리', async () => {
  const store=storage();store.setItem(TOKEN_KEY,'existing');
  const temporary=createAuthSessions({storage:store,request:async()=>{throw new AppError('일시 오류',503);}});
  await assert.rejects(temporary.logout());assert.equal(store.getItem(TOKEN_KEY),'existing');
  const expired=createAuthSessions({storage:store,request:async()=>{throw new AppError('만료',401);}});
  await expired.logout();assert.equal(store.getItem(TOKEN_KEY),null);
});

test('기존 체험 생성 요청이 남아 있어도 사용자 생성이나 자동 로그인을 하지 않음', async () => {
  const store=storage();store.setItem('moneycare.api.demo.creation','old request');
  const client=createAuthSessions({storage:store,request:async()=>{throw new Error('호출되면 안 됨');}});
  assert.equal(await client.restore(),null);assert.equal(store.getItem('moneycare.api.demo.creation'),null);
});
