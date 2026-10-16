import React from 'react';
import { Navigate, Outlet, Route, Routes } from 'react-router-dom';
import { useApp } from './context/AppContext.jsx';
import { Loading, Button } from './components/UI.jsx';
import Layout from './components/Layout.jsx';
import LoginPage from './pages/LoginPage.jsx';
import HomePage from './pages/HomePage.jsx';
import TransferPage from './pages/TransferPage.jsx';
import TransactionsPage from './pages/TransactionsPage.jsx';
import AlertsPage from './pages/AlertsPage.jsx';
import AlertDetailPage from './pages/AlertDetailPage.jsx';
import BudgetPage from './pages/BudgetPage.jsx';
import SupporterPage from './pages/SupporterPage.jsx';

function Protected({ role }) { const { user, loading } = useApp(); if (loading) return <Loading />; if (!user) return <Navigate to="/login" replace />; if (role && user.role !== role) return <Navigate to={user.role === 'SUPPORTER' ? '/supporter' : '/'} replace />; return <Outlet />; }
export default function App() {
  const { user, loading, data, error, reload } = useApp();
  if (loading) return <Loading />;
  if (user && !data) return <div className="loading"><p role="alert">{error || '데이터를 불러오고 있어요.'}</p><Button onClick={() => reload().catch(() => {})}>다시 시도</Button></div>;
  return <><a className="skip-link" href="#main-content" onClick={(e) => { e.preventDefault(); const main = document.getElementById('main-content'); if (main) { main.tabIndex = -1; main.focus(); } }}>본문으로 이동</a><Routes><Route path="/login" element={<LoginPage />} /><Route element={<Protected />}><Route element={<Layout />}><Route element={<Protected role="OWNER" />}><Route index element={<HomePage />} /><Route path="transfer" element={<TransferPage />} /><Route path="transactions" element={<TransactionsPage />} /><Route path="alerts" element={<AlertsPage />} /><Route path="alerts/:id" element={<AlertDetailPage />} /><Route path="budget" element={<BudgetPage />} /></Route><Route element={<Protected role="SUPPORTER" />}><Route path="supporter" element={<SupporterPage />} /></Route></Route></Route><Route path="*" element={<Navigate to={user ? (user.role === 'SUPPORTER' ? '/supporter' : '/') : '/login'} replace />} /></Routes></>;
}
