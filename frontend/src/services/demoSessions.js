import { AppError } from '../lib/domain.js';

export const DEMO_TOKEN_KEY = 'moneycare.api.token';
export const DEMO_CREATION_KEY = 'moneycare.api.demo.creation';

export function createDemoSessions({ request, storage, uuid = () => crypto.randomUUID() }) {
  let inFlight = null, flightFingerprint = null;
  const clear = () => { storage.removeItem(DEMO_TOKEN_KEY); storage.removeItem(DEMO_CREATION_KEY); };
  const start = (input) => {
    const body = { acknowledged: input.acknowledged, monitoring_consented: input.monitoring_consented, restart: Boolean(input.restart) };
    const fingerprint = JSON.stringify(body);
    if (inFlight) return fingerprint === flightFingerprint ? inFlight : Promise.reject(new AppError('현재 체험 시작 요청이 끝난 뒤 다시 시도해 주세요.', 409));
    let pending;
    try { pending = JSON.parse(storage.getItem(DEMO_CREATION_KEY)); } catch { /* 손상된 임시 키 재생성 */ }
    if (!pending || typeof pending.key !== 'string' || pending.fingerprint !== fingerprint) pending = { key: uuid(), fingerprint };
    storage.setItem(DEMO_CREATION_KEY, JSON.stringify(pending));
    flightFingerprint = fingerprint;
    inFlight = (async () => {
      try {
        const result = await request('/demo/sessions', { method: 'POST', body, headers: { 'Idempotency-Key': pending.key } });
        if (!result?.access_token || !result?.user) throw new AppError('체험 세션 응답을 확인해 주세요.', 502);
        storage.setItem(DEMO_TOKEN_KEY, result.access_token);
        storage.removeItem(DEMO_CREATION_KEY);
        return result.user;
      } catch (error) {
        // 통신 실패는 같은 키로 재시도합니다. 검증 실패는 새 시도로 다시 입력받습니다.
        if (error.status >= 400 && error.status < 500) storage.removeItem(DEMO_CREATION_KEY);
        if (error.status === 401) storage.removeItem(DEMO_TOKEN_KEY);
        throw error;
      } finally { inFlight = null; flightFingerprint = null; }
    })();
    return inFlight;
  };
  const recover = async () => {
    const raw = storage.getItem(DEMO_CREATION_KEY);
    if (!raw) return;
    let body;
    try { body = JSON.parse(JSON.parse(raw).fingerprint); }
    catch { storage.removeItem(DEMO_CREATION_KEY); return; }
    if (!body || body.acknowledged !== true || typeof body.monitoring_consented !== 'boolean' || typeof body.restart !== 'boolean') {
      storage.removeItem(DEMO_CREATION_KEY); return;
    }
    // 응답 유실 뒤 재접속도 같은 생성 요청 키로 복구합니다.
    return start(body);
  };
  return {
    start, clear, recover,
    async restore() {
      try {
        await recover();
        if (!storage.getItem(DEMO_TOKEN_KEY)) return null;
        return (await request('/demo/me')).user;
      }
      catch (error) { if (error.status === 401) { clear(); return null; } throw error; }
    },
    async logout() {
      await recover();
      if (storage.getItem(DEMO_TOKEN_KEY)) {
        try { await request('/demo/sessions/current', { method: 'DELETE' }); }
        catch (error) { if (error.status !== 401) throw error; }
      }
      clear();
    },
  };
}
