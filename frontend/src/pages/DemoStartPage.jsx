import React, { useRef, useState } from 'react';
import { ArrowRight, Leaf, ShieldCheck } from 'lucide-react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext.jsx';
import { Button, ErrorMessage } from '../components/UI.jsx';

export default function DemoStartPage() {
  const { user, startDemo, error: sessionError } = useApp();
  const navigate = useNavigate();
  const [acknowledged, setAcknowledged] = useState(false), [consented, setConsented] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const lock = useRef(false);
  if (user) return <Navigate to="/" replace />;
  const start = async (event) => {
    event.preventDefault();
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await startDemo({ acknowledged, monitoring_consented: consented }); navigate('/', { replace: true }); }
    catch (e) { setError(e.message); }
    finally { lock.current = false; setBusy(false); }
  };
  return <div className="login-page">
    <section className="login-story">
      <div className="brand"><span className="brand-mark"><Leaf size={25} /></span><span>내 돈 안심<span className="brand-sub">MONEY CARE</span></span></div>
      <div className="story-main"><span className="story-kicker">내 일상에 작은 안심</span><h1>내 돈을 살펴보는 일,<br />먼저 편하게 체험해 봐요.</h1><p>내 전용 체험 통장으로<br />송금과 생활비 화면을 살펴볼 수 있어요.</p></div>
      <p className="story-footer"><ShieldCheck size={18} />실제 은행 계좌나 이메일은 필요하지 않아요.</p>
    </section>
    <main id="main-content" className="login-form-area"><div className="login-form-wrap">
      <span className="eyebrow">가입 없이 시작하기</span><h2>나만의 체험을 시작해요</h2>
      <p className="page-description">전용 사용자와 가상 잔액 80만 원을 만들어요. 체험은 기본 24시간 동안 사용할 수 있어요.</p>
      <form className="form-stack" onSubmit={start}>
        <div className="info-box">모든 계좌와 거래는 체험용 합성 데이터예요. 실제 돈은 이동하지 않고, 이메일을 입력하거나 메일을 받지 않아요.</div>
        <label className="checkbox-label"><input type="checkbox" checked={acknowledged} required disabled={busy} onChange={(e) => setAcknowledged(e.target.checked)} />합성 데이터로 진행되는 체험임을 확인했어요. (필수)</label>
        <label className="checkbox-label"><input type="checkbox" checked={consented} disabled={busy} onChange={(e) => setConsented(e.target.checked)} />체험 데이터에서 평소와 다른 거래와 생활비 부족을 살펴보는 데 동의해요. (선택)</label>
        <p className="helper">모니터링에 동의하지 않아도 통장과 설정을 볼 수 있어요. 가상 송금은 동의 후 이용할 수 있고, 내 설정에서 언제든 철회할 수 있어요.</p>
        <ErrorMessage>{error || sessionError}</ErrorMessage>
        <Button type="submit" className="full" busy={busy} disabled={!acknowledged}>체험 시작<ArrowRight size={19} /></Button>
      </form>
      <p className="login-footnote">새로고침해도 같은 탭의 유효한 체험은 유지돼요.</p>
    </div></main>
  </div>;
}
