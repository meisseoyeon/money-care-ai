import { AppError } from '../lib/domain.js';
import { createDemoSessions, DEMO_TOKEN_KEY } from './demoSessions.js';

// 이 파일에서 팀의 실제 FastAPI 경로/응답 DTO에 맞춰 변환하세요. 저장소 루트 docs/API_CONTRACT.md 참고.
export function createHttpApi(baseUrl, { storage = sessionStorage, fetchImpl = fetch } = {}) {
  async function request(path, { method = 'GET', body, headers = {} } = {}) {
    const token = storage.getItem(DEMO_TOKEN_KEY), controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const res = await fetchImpl(`${baseUrl.replace(/\/$/, '')}${path}`, { method, headers: { ...headers, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}), signal: controller.signal });
      const json = res.status === 204 ? null : await res.json().catch(() => null);
      // 이전 체험의 늦은 응답이 새 체험의 화면이나 인증 상태를 바꾸지 않게 합니다.
      if (token !== storage.getItem(DEMO_TOKEN_KEY)) throw new AppError('체험이 변경되었어요. 다시 시도해 주세요.', 409);
      if (!res.ok) { const detail = typeof json?.detail === 'string' ? json.detail : json?.message; throw new AppError(detail || `요청을 처리하지 못했어요. (${res.status})`, res.status); }
      if (res.status !== 204 && json === null) throw new AppError('서버 응답 형식을 확인해 주세요.', 502);
      return json;
    } catch (e) { if (e instanceof AppError) throw e; throw new AppError(e.name === 'AbortError' ? '응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요.' : '서버에 연결할 수 없어요. 네트워크를 확인해 주세요.', 503); }
    finally { clearTimeout(timeout); }
  }
  const demo = createDemoSessions({ request, storage });
  return {
    mode: 'api',
    startDemo: demo.start,
    restoreSession: demo.restore,
    logout: demo.logout,
    clearSession: demo.clear,
    async login() { throw new AppError('이메일 로그인 대신 체험 시작을 이용해 주세요.'); },
    async loadData() {
      await demo.recover();
      const history = async () => {
        const items = [];
        let cursor = null;
        do {
          const page = await request(`/transactions${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
          items.push(...page.items);
          cursor = page.next_cursor;
        } while (cursor);
        return items;
      };
      const [context, recipients, transactions] = await Promise.all([request('/demo/me'), request('/demo/recipients'), history()]);
      // 탐지·알림 API는 담당 기능 병합 시 연결합니다.
      return { ...context, recipients, forecast: null, baseline: null, transactions, alerts: [], guides: [], links: [], shares: [] };
    },
    // 백엔드 구현 전까지 API 모드에서는 서버의 오류를 그대로 표시합니다.
    requestTransferHelp: (payload) => request('/transfer-help-requests', { method: 'POST', body: payload }),
    transfer: (payload) => request('/transfers', { method: 'POST', body: payload }),
    markSeen: (id) => request(`/alerts/${id}/seen`, { method: 'POST' }),
    respond: (id, response) => request(`/alerts/${id}/response`, { method: 'POST', body: { response } }),
    generateGuide: (id) => request(`/alerts/${id}/guide`, { method: 'POST' }),
    saveBudget: (payload) => request('/budget-settings', { method: 'PUT', body: payload }),
    saveExpense: (payload) => request(payload.id ? `/scheduled-expenses/${payload.id}` : '/scheduled-expenses', { method: payload.id ? 'PATCH' : 'POST', body: payload }),
    setMonitoring: (enabled) => request('/demo/me/monitoring-consent', { method: 'PUT', body: { consented: enabled } }),
    revokeShare: (id) => request(`/alert-shares/${id}/revoke`, { method: 'POST' }),
    setLink: (id, active) => request(`/supporter-links/${id}/${active ? 'accept' : 'revoke'}`, { method: 'POST' }),
    async resetData() { throw new AppError('실제 API 모드에서는 프런트엔드에서 데이터를 초기화하지 않아요.'); },
  };
}
