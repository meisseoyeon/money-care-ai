import React, { useRef, useState } from 'react';
import { useApp } from '../context/AppContext.jsx';
import { Button, ErrorMessage, Modal } from './UI.jsx';

export default function DemoRestartModal({ onClose, onDone }) {
  const { startDemo } = useApp();
  const [acknowledged, setAcknowledged] = useState(false), [consented, setConsented] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const lock = useRef(false);
  const restart = async () => {
    if (lock.current || !acknowledged) return;
    lock.current = true; setBusy(true); setError('');
    try { await startDemo({ acknowledged: true, monitoring_consented: consented, restart: true }); onDone(); }
    catch (e) { setError(e.message); }
    finally { lock.current = false; setBusy(false); }
  };
  return <Modal open title="처음부터 다시 체험할까요?" onClose={() => { if (!lock.current) onClose(); }}>
    <p>새 체험 사용자와 통장을 만들어요. 이전 체험은 종료되어 다시 접근할 수 없어요. 실제 계좌나 돈에는 영향을 주지 않아요.</p>
    <div className="form-stack">
      <label className="checkbox-label"><input type="checkbox" checked={acknowledged} disabled={busy} onChange={(e) => setAcknowledged(e.target.checked)} />합성 데이터 체험을 새로 시작하는 것을 확인했어요.</label>
      <label className="checkbox-label"><input type="checkbox" checked={consented} disabled={busy} onChange={(e) => setConsented(e.target.checked)} />새 체험 데이터의 모니터링에 동의해요. (선택)</label>
      <ErrorMessage>{error}</ErrorMessage>
      <Button className="full" disabled={!acknowledged} busy={busy} onClick={restart}>새 체험 시작</Button>
      <Button className="full" variant="secondary" disabled={busy} onClick={onClose}>취소</Button>
    </div>
  </Modal>;
}
