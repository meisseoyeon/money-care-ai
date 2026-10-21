import React, { useState } from 'react';
import { CheckCircle, LoaderCircle, RefreshCw } from 'lucide-react';
import { useApp } from '../../shared/state/AppContext.js';
import { Button, ErrorMessage } from '../../shared/ui/UI.jsx';

export default function PreparationStatus() {
  const { preparation, reload, logout } = useApp();
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const checking = preparation.status === 'CHECKING', ready = preparation.status === 'READY';
  const retry = async (action) => { if (busy) return; setBusy(true); setError(''); try { await action(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  return <section className={`preparation-status ${ready ? 'is-ready' : ''}`} aria-label="송금 준비 상태" aria-busy={checking}>
    <div role="status" aria-live="polite" className="preparation-copy">
      {checking ? <LoaderCircle size={20} className="spin" aria-hidden="true" /> : ready ? <CheckCircle size={20} aria-hidden="true" /> : <RefreshCw size={20} aria-hidden="true" />}
      <div><strong>{ready ? '송금 준비 완료' : checking ? '송금을 준비하고 있어요' : '송금 준비가 필요해요'}</strong><p>{preparation.message}</p></div>
    </div>
    {!ready && !checking && <div className="preparation-actions"><Button variant="secondary" busy={busy} onClick={() => retry(reload)}>다시 조회</Button><Button variant="ghost" disabled={busy} onClick={() => retry(logout)}>다시 로그인</Button></div>}
    <ErrorMessage>{error}</ErrorMessage>
  </section>;
}
