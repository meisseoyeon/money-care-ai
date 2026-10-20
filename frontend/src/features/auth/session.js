import { TOKEN_KEY } from '../../shared/lib/storageKeys.js';
import { AppError } from '../../shared/lib/errors.js';


export function createAuthSessions({ request, storage }) {
  let inFlight = null;
  const clear = () => { storage.removeItem(TOKEN_KEY); storage.removeItem('moneycare.api.demo.creation'); };
  return {
    clear,
    login(username, password) {
      if (inFlight) return Promise.reject(new AppError('로그인 요청이 끝난 뒤 다시 시도해 주세요.', 409));
      inFlight = (async () => {
        try {
          const result = await request('/auth/login', { method: 'POST', body: { username, password } });
          if (!result?.access_token || !result?.user) throw new AppError('로그인 응답을 확인해 주세요.', 502);
          storage.setItem(TOKEN_KEY, result.access_token);
          storage.removeItem('moneycare.api.demo.creation');
          return result.user;
        } finally { inFlight = null; }
      })();
      return inFlight;
    },
    async restore() {
      // 이전 자동 생성 요청을 재실행하지 않습니다.
      storage.removeItem('moneycare.api.demo.creation');
      if (!storage.getItem(TOKEN_KEY)) return null;
      try { return (await request('/auth/me')).user; }
      catch (error) { if (error.status === 401) { clear(); return null; } throw error; }
    },
    async logout() {
      if (inFlight) throw new AppError('로그인 요청이 끝난 뒤 다시 시도해 주세요.', 409);
      if (storage.getItem(TOKEN_KEY)) {
        try { await request('/auth/logout', { method: 'POST' }); }
        catch (error) { if (error.status !== 401) throw error; }
      }
      clear();
    },
  };
}
