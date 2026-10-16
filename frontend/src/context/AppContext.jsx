import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api } from '../services/api.js';
import { DB_KEY } from '../services/mockApi.js';

const Context = createContext(null);
export function AppProvider({ children }) {
  const [user, setUser] = useState(null), [data, setData] = useState(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [toast, setToast] = useState('');
  const serial = useRef(0);
  const reload = useCallback(async () => {
    const ticket = ++serial.current;
    try { const next = await api.loadData(); if (ticket === serial.current) { setData(next); setUser(next.user); setError(''); } return next; }
    catch (e) { if (ticket === serial.current) { if (e.status === 401) { setUser(null); setData(null); await api.logout(); } else setError(e.message); } throw e; }
  }, []);
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
  const login = async (email, password) => { await api.login(email, password); return (await reload()).user; };
  const logout = async () => { ++serial.current; await api.logout(); setUser(null); setData(null); setError(''); };
  const run = async (method, ...args) => { try { const result = await api[method](...args); await reload(); return result; } catch (e) { if (e.status === 401) await logout(); throw e; } };
  return <Context.Provider value={{ user, data, loading, error, toast, notify: setToast, login, logout, reload, run, mode: api.mode }}>{children}</Context.Provider>;
}
export const useApp = () => useContext(Context);
