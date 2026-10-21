import { AppContext } from '../shared/state/AppContext.js';
import { MOCK_DB_KEY as DB_KEY } from '../shared/lib/storageKeys.js';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import { AppError } from '../shared/lib/errors.js';
import { CHECKING, effectivePreparation, isPreparationReady } from '../features/preparation/state.js';

export function AppProvider({ children }) {
  const [user, setUser] = useState(null), [data, setData] = useState(null), [loading, setLoading] = useState(true), [error, setError] = useState(''), [toast, setToast] = useState('');
  const serial = useRef(0);
  const sessionEpoch = useRef(0);
  const [preparation, setPreparation] = useState(CHECKING);
  const preparationRef = useRef(CHECKING);
  const [financialBusy, setFinancialBusy] = useState(false);
  const financialCount = useRef(0);
  const updatePreparation = useCallback((next) => { preparationRef.current = next; setPreparation(next); }, []);
  const expireSession = useCallback(() => {
    ++serial.current;
    ++sessionEpoch.current;
    // 401은 로컬 인증만 정리합니다. 서버 로그아웃을 실행하지 않습니다.
    if (api.clearSession) api.clearSession();
    else api.logout();
    setUser(null); setData(null); setError(''); updatePreparation(CHECKING);
  }, [updatePreparation]);
  const reload = useCallback(async () => {
    const ticket = ++serial.current;
    if (api.mode === 'api') updatePreparation(CHECKING);
    try {
      const next = await api.loadData();
      if (ticket === serial.current) {
        setData(next); setUser(next.user); setError('');
        updatePreparation(next.preparation ?? (api.mode === 'mock' ? { status: 'READY', source: 'mock', message: '송금 준비가 끝났어요.' } : { status: 'ERROR', message: '준비 결과를 확인하지 못했어요.' }));
      }
      return next;
    } catch (e) {
      if (ticket === serial.current) {
        if (e.status === 401) expireSession();
        else {
          setError(e.message);
          updatePreparation({ status: 'ERROR', message: '준비 상태를 확인하지 못했어요. 연결을 확인하고 다시 조회해 주세요.' });
          setData((previous) => previous ? { ...previous, forecast: null, baseline: null } : null);
        }
      }
      throw e;
    }
  }, [expireSession, updatePreparation]);
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
    updatePreparation(CHECKING);
    const epoch = sessionEpoch.current;
    const nextUser = await api.login(username, password);
    if (epoch !== sessionEpoch.current) throw new AppError('로그인이 변경되었어요. 다시 시도해 주세요.', 409);
    setUser(nextUser); setData(null);
    return (await reload()).user;
  };
  const logout = async () => {
    ++serial.current; ++sessionEpoch.current; updatePreparation(CHECKING);
    try { await api.logout(); }
    catch (e) { updatePreparation({ status: 'ERROR', message: '로그아웃하지 못했어요. 연결을 확인하고 다시 시도해 주세요.' }); throw e; }
    ++serial.current; setUser(null); setData(null); setError('');
  };
  const run = async (method, ...args) => {
    const epoch = sessionEpoch.current;
    if (method === 'transfer' && (!isPreparationReady(preparationRef.current) || financialCount.current > 0)) {
      throw new AppError('송금 준비가 끝난 뒤 다시 확인해 주세요.', 409);
    }
    const financial = ['transfer', 'saveBudget', 'saveExpense'].includes(method);
    if (financial) { financialCount.current += 1; setFinancialBusy(true); }
    try {
      const result = await api[method](...args);
      if (epoch !== sessionEpoch.current) throw new AppError('체험이 변경되었어요. 다시 시도해 주세요.', 409);
      // 확정된 송금을 조회 실패 때문에 실패한 송금으로 표시하지 않습니다.
      try { await reload(); } catch { /* reload가 준비 실패와 송금 차단 상태를 설정합니다. */ }
      return result;
    } catch (e) {
      if (epoch === sessionEpoch.current) {
        if (e.status === 401) expireSession();
        else if (financial) { try { await reload(); } catch { /* 재조회 실패 시 차단 유지 */ } }
      }
      throw e;
    } finally {
      if (financial) { financialCount.current -= 1; setFinancialBusy(financialCount.current > 0); }
    }
  };
  const currentPreparation = financialBusy ? CHECKING : effectivePreparation(preparation);
  return <AppContext.Provider value={{ user, data, loading, error, toast, preparation: currentPreparation, canTransfer: currentPreparation.status === 'READY', notify: setToast, login, logout, reload, run, mode: api.mode }}>{children}</AppContext.Provider>;
}
