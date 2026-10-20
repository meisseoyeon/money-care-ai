import { AppContext } from '../shared/state/AppContext.js';
import { MOCK_DB_KEY as DB_KEY } from '../shared/lib/storageKeys.js';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { AppError } from '../shared/lib/errors.js';

export function AppProvider({ children }) {
  const [user, setUser] = useState(null), [data, setData] = useState(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [toast, setToast] = useState('');
  const serial = useRef(0);
  const sessionEpoch = useRef(0);
  const expireSession = useCallback(() => {
    ++serial.current;
    ++sessionEpoch.current;
    // 401은 로컬 인증만 정리합니다. 서버 로그아웃을 실행하지 않습니다.
    if (api.clearSession) api.clearSession();
    else api.logout();
    setUser(null); setData(null); setError('');
  }, []);
  const reload = useCallback(async () => {
    const ticket = ++serial.current;
    try { const next = await api.loadData(); if (ticket === serial.current) { setData(next); setUser(next.user); setError(''); } return next; }
    catch (e) { if (ticket === serial.current) { if (e.status === 401) expireSession(); else setError(e.message); } throw e; }
  }, [expireSession]);
  useEffect(() => { let active = true; (async () => { try { const restored = await api.restoreSession(); if (!active) return; if (restored) { setUser(restored); await reload(); } } catch (e) { if (active) setError(e.message); } finally { if (active) setLoading(false); } })(); return () => { active = false; }; }, [reload]);
  useEffect(() => { if (!toast) return; const t = setTimeout(() => setToast(''), 4000); return () => clearTimeout(t); }, [toast]);
  useEffect(() => {
    if (!user) return;
    const refresh = () => { if (document.visibilityState === 'visible') reload().catch(() => {}); };
    const storage = (e) => { if (e.key === DB_KEY) refresh(); };
    window.addEventListener('focus', refresh); window.addEventListener('storage', storage);
    const timer = setInterval(refresh, 10000);
    return () => { window.removeEventListener('focus', refresh); window.removeEventListener('storage', storage); clearInterval(timer); };
  }, [user?.user_id, reload]);
  const login = async (username, password) => {
    ++serial.current; ++sessionEpoch.current;
    const nextUser = await api.login(username, password);
    setUser(nextUser); setData(null);
    return (await reload()).user;
  };
  const logout = async () => { ++serial.current; ++sessionEpoch.current; await api.logout(); ++serial.current; setUser(null); setData(null); setError(''); };
  const run = async (method, ...args) => {
    const epoch = sessionEpoch.current;
    try {
      const result = await api[method](...args);
      if (epoch !== sessionEpoch.current) throw new AppError('체험이 변경되었어요. 다시 시도해 주세요.', 409);
      await reload(); return result;
    } catch (e) { if (e.status === 401 && epoch === sessionEpoch.current) expireSession(); throw e; }
  };
  return <AppContext.Provider value={{ user, data, loading, error, toast, notify: setToast, login, logout, reload, run, mode: api.mode }}>{children}</AppContext.Provider>;
}
