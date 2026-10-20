import { AppError } from '../lib/domain.js';

const TOKEN_KEY = 'moneycare.api.token';
// 이 파일에서 팀의 실제 FastAPI 경로/응답 DTO에 맞춰 변환하세요. 저장소 루트 docs/API_CONTRACT.md 참고.
export function createHttpApi(baseUrl) {
  async function request(path, { method = 'GET', body } = {}) {
    const token = sessionStorage.getItem(TOKEN_KEY), controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const res = await fetch(`${baseUrl.replace(/\/$/, '')}${path}`, { method, headers: { ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}), signal: controller.signal });
      const json = res.status === 204 ? null : await res.json().catch(() => null);
      if (!res.ok) { const detail = typeof json?.detail === 'string' ? json.detail : json?.message; throw new AppError(detail || `요청을 처리하지 못했어요. (${res.status})`, res.status); }
      return json;
    } catch (e) { if (e instanceof AppError) throw e; throw new AppError(e.name === 'AbortError' ? '응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요.' : '서버에 연결할 수 없어요. 네트워크를 확인해 주세요.', 503); }
    finally { clearTimeout(timeout); }
  }
  const items = (value) => Array.isArray(value) ? value : value?.items ?? [];
  return {
    mode: 'api',
    async login(email, password) { const result = await request('/auth/login', { method: 'POST', body: { email, password } }); if (!result?.access_token) throw new AppError('로그인 응답의 access_token을 확인해 주세요.', 500); sessionStorage.setItem(TOKEN_KEY, result.access_token); return request('/users/me'); },
    async restoreSession() { if (!sessionStorage.getItem(TOKEN_KEY)) return null; try { return await request('/users/me'); } catch (e) { if (e.status === 401) { sessionStorage.removeItem(TOKEN_KEY); return null; } throw e; } },
    async logout() { sessionStorage.removeItem(TOKEN_KEY); },
    async loadData() {
      const user = await request('/users/me');
      if (user.role === 'SUPPORTER') return { user, sharedAlerts: items(await request('/shared-alerts')) };
      const [accounts, settings, expenses, forecast, recipients, transactions, alerts, links, shares] = await Promise.all([
        request('/accounts'), request('/budget-settings'), request('/scheduled-expenses'), request('/budget-forecasts/latest').catch((e) => { if (e.status === 404) return null; throw e; }), request('/recipients'), request('/transactions'), request('/alerts'), request('/supporter-links'), request('/alert-shares'),
      ]);
      const alertItems = items(alerts);
      return { user, account: items(accounts)[0] ?? null, settings, expenses: items(expenses), forecast, recipients: items(recipients), transactions: items(transactions), alerts: alertItems, guides: alertItems.filter((a) => a.guide).map((a) => a.guide), links: items(links), shares: items(shares) };
    },
    // 백엔드 구현 전까지 API 모드에서는 서버의 오류를 그대로 표시합니다.
    requestTransferHelp: (payload) => request('/transfer-help-requests', { method: 'POST', body: payload }),
    transfer: (payload) => request('/transfers', { method: 'POST', body: payload }),
    markSeen: (id) => request(`/alerts/${id}/seen`, { method: 'POST' }),
    respond: (id, response) => request(`/alerts/${id}/response`, { method: 'POST', body: { response } }),
    generateGuide: (id) => request(`/alerts/${id}/guide`, { method: 'POST' }),
    saveBudget: (payload) => request('/budget-settings', { method: 'PUT', body: payload }),
    saveExpense: (payload) => request(payload.id ? `/scheduled-expenses/${payload.id}` : '/scheduled-expenses', { method: payload.id ? 'PATCH' : 'POST', body: payload }),
    setMonitoring: (enabled) => request('/users/me/monitoring-consent', { method: 'PUT', body: { consented: enabled } }),
    revokeShare: (id) => request(`/alert-shares/${id}/revoke`, { method: 'POST' }),
    setLink: (id, active) => request(`/supporter-links/${id}/${active ? 'accept' : 'revoke'}`, { method: 'POST' }),
    async resetData() { throw new AppError('실제 API 모드에서는 프런트엔드에서 데이터를 초기화하지 않아요.'); },
  };
}
