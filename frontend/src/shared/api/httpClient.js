import { AppError } from '../lib/errors.js';
import { TOKEN_KEY } from '../lib/storageKeys.js';

export function createHttpClient(baseUrl, { storage = sessionStorage, fetchImpl = fetch } = {}) {
  return async function request(path, { method = 'GET', body, headers = {} } = {}) {
    const token = storage.getItem(TOKEN_KEY), controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const res = await fetchImpl(`${baseUrl.replace(/\/$/, '')}${path}`, { method, headers: { ...headers, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) }, ...(body !== undefined ? { body: JSON.stringify(body) } : {}), signal: controller.signal });
      const json = res.status === 204 ? null : await res.json().catch(() => null);
      if (token !== storage.getItem(TOKEN_KEY)) throw new AppError('체험이 변경되었어요. 다시 시도해 주세요.', 409);
      if (!res.ok) { const detail = typeof json?.detail === 'string' ? json.detail : json?.message; throw new AppError(detail || `요청을 처리하지 못했어요. (${res.status})`, res.status); }
      if (res.status !== 204 && json === null) throw new AppError('서버 응답 형식을 확인해 주세요.', 502);
      return json;
    } catch (e) { if (e instanceof AppError) throw e; throw new AppError(e.name === 'AbortError' ? '응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요.' : '서버에 연결할 수 없어요. 네트워크를 확인해 주세요.', 503); }
    finally { clearTimeout(timeout); }
  };
}
