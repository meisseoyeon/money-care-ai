import React, { useRef, useState } from 'react';
import { ArrowRight, Check, ChevronRight, HandHeart, LockKeyhole, Send, ShieldAlert, Wallet } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext.jsx';
import { validateMoney, won } from '../lib/domain.js';
import { reviewTransfer } from '../lib/transferReview.js';
import { Badge, Button, Card, ErrorMessage, Modal, PageTitle, SuccessIcon } from '../components/UI.jsx';

export default function TransferPage() {
  const { data, run } = useApp();
  const navigate = useNavigate();
  const [recipientId, setRecipientId] = useState('');
  const [amount, setAmount] = useState('');
  const [draft, setDraft] = useState(null);
  const [step, setStep] = useState('confirm');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const lock = useRef(false), request = useRef(null);
  const recipients = data.recipients ?? [];
  const recipient = recipients.find((r) => r.id === recipientId);
  const balance = data.account?.current_balance ?? 0;
  const supporter = data.links?.find((link) => link.status === 'ACTIVE');

  const closeDraft = () => {
    if (lock.current) return;
    setDraft(null);
    setError('');
  };
  const goTo = (next) => { if (!lock.current) { setError(''); setStep(next); } };
  const confirm = (event) => {
    event.preventDefault();
    setError('');
    try {
      const n = validateMoney(Number(amount));
      if (!recipient) throw new Error('받는 사람을 먼저 선택해 주세요.');
      if (n > balance) throw new Error('통장에 있는 돈보다 많이 보낼 수 없어요.');
      const review = reviewTransfer(data, n);
      const fingerprint = `${recipientId}:${n}`;
      if (!request.current || request.current.fingerprint !== fingerprint) request.current = { fingerprint, id: crypto.randomUUID() };
      setDraft({ amount: n, recipient, balance, ...review });
      setStep(review.requiresReview ? 'warning' : 'confirm');
    } catch (e) { setError(e.message); }
  };

  const requestHelp = async () => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError('');
    try {
      await run('requestTransferHelp', { request_id: request.current.id, counterparty_id: draft.recipient.id, amount: draft.amount });
      setStep('shared');
    } catch (e) { setError(e.message); }
    finally { lock.current = false; setBusy(false); }
  };

  const send = async () => {
    if (lock.current || step !== 'confirm') return;
    lock.current = true;
    setBusy(true);
    setError('');
    try {
      const response = await run('transfer', { request_id: request.current.id, counterparty_id: draft.recipient.id, amount: draft.amount });
      setResult({ ...response, recipient: draft.recipient });
      setDraft(null);
      setAmount('');
      request.current = null;
    } catch (e) { setError(e.message); }
    finally { lock.current = false; setBusy(false); }
  };

  const modalTitle = { warning: '보내기 전에 잠깐 확인해요', help: '송금 전에 도움을 요청할까요?', shared: '도움 요청을 공유했어요', confirm: '보낼 내용 확인' }[step];

  return <>
    <PageTitle eyebrow="가상 송금" title="누구에게 보낼까요?" description="받는 사람과 금액을 천천히 확인해 주세요." />
    <div className="transfer-grid">
      <form onSubmit={confirm} className="form-stack">
        <Card>
          <div className="section-heading"><h2>받는 사람</h2><span className="helper">한 명을 선택해 주세요</span></div>
          <div className="recipient-list" role="group" aria-label="받는 사람 선택">
            {recipients.map((r) => <button type="button" className={`recipient ${recipientId === r.id ? 'selected' : ''}`} key={r.id} aria-pressed={recipientId === r.id} onClick={() => { setRecipientId(r.id); setError(''); }}>
              <span className={`avatar ${r.familiar ? '' : 'peach'}`}>{r.initial || r.name.slice(0, 1)}</span>
              <span className="grow"><strong>{r.name}</strong><small>{r.bank} {r.account_hint}</small></span>
              {!r.familiar && <Badge tone="peach">처음 보내요</Badge>}
              <span className="recipient-check">{recipientId === r.id && <Check size={15} />}</span>
            </button>)}
          </div>
        </Card>
        <Card>
          <h2>보낼 금액</h2>
          <label className="amount-label"><span className="sr-only">송금 금액</span><div className="amount-input"><input name="amount" type="text" inputMode="numeric" autoComplete="off" placeholder="0" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^0-9]/g, ''))} /><span>원</span></div></label>
          <div className="quick-amounts">{[10000, 50000, 100000, 300000].map((n) => <Button key={n} variant="secondary" onClick={() => setAmount(String(n))}>{n / 10000}만 원</Button>)}</div>
          <ErrorMessage>{!draft && error}</ErrorMessage>
          <Button type="submit" className="full" disabled={!recipientId || !amount}>보낼 내용 확인 <ArrowRight size={19} /></Button>
        </Card>
      </form>
      <div className="transfer-aside">
        <Card className="soft-card"><span className="icon-tile"><Wallet size={24} /></span><p className="helper">보낼 수 있는 돈</p><p className="aside-amount">{won(balance)}</p><p className="helper">{data.account?.display_name}</p><div className="soft-divider" /><h3>잠깐, 확인해 주세요.</h3><ul className="gentle-list"><li>받는 사람이 맞는지 확인해요.</li><li>부탁받은 송금이라면 한 번 더 생각해요.</li><li>실제 돈이 이동하지 않는 가상 송금이에요.</li></ul></Card>
        <p className="secure-note"><LockKeyhole size={16} />송금 후에는 통장 기록에서 확인할 수 있어요.</p>
      </div>
    </div>

    <Modal open={Boolean(draft)} title={modalTitle} onClose={closeDraft}>
      {draft && <>
        {step === 'warning' && <>
          <p className="helper">아직 돈을 보내지 않았어요. 아래 내용을 먼저 살펴봐요.</p>
          <div className="transfer-warnings">
            <section className="transfer-warning"><span className="icon-tile warm"><ShieldAlert size={23} /></span><div><h3>평소보다 큰 금액을 보내려고 해요</h3><p>{draft.recipient.name}님에게 {won(draft.amount)}을 보내려고 해요. 10만 원이 넘는 송금은 한 번 더 확인해 주세요.</p></div></section>
            {draft.forecast?.shortage_amount > 0 && <section className="transfer-warning"><span className="icon-tile warm"><Wallet size={23} /></span><div><h3>다음 수입일까지 생활비가 부족할 수 있어요</h3><p>이 돈을 보내면 예정된 지출과 생활비를 위해 {won(draft.forecast.shortage_amount)}이 더 필요할 수 있어요.</p></div></section>}
            {!draft.recipient.familiar && <div className="info-box">처음 보내는 상대예요. 받는 사람과 계좌가 맞는지 확인해 주세요.</div>}
          </div>
          <Button className="full" onClick={() => goTo('help')}><HandHeart size={20} />도움 요청하기</Button>
          <Button className="full" variant="secondary" onClick={() => goTo('confirm')}>확인했어요 · 보낼 내용 확인<ArrowRight size={18} /></Button>
          <Button className="full" variant="ghost" onClick={closeDraft}>금액을 다시 입력할게요</Button>
        </>}

        {step === 'help' && <>
          {supporter ? <>
            <p><strong>{supporter.supporter_name || '연결된 지원자'}</strong>님에게 아래 송금 예정 내용과 확인할 점을 공유해요.</p>
            <div className="receipt"><div><span>받는 사람</span><strong>{draft.recipient.name}</strong></div><div><span>보내려는 금액</span><strong>{won(draft.amount)}</strong></div>{draft.forecast?.shortage_amount > 0 && <div><span>예상 생활비 부족</span><strong>{won(draft.forecast.shortage_amount)}</strong></div>}</div>
            <div className="info-box">아직 돈을 보내지 않았어요. 도움 요청에는 송금 예정 내용만 공유하고, 통장 전체 내역은 공유하지 않아요.</div>
            <ErrorMessage>{error}</ErrorMessage>
            <Button className="full" busy={busy} onClick={requestHelp}><HandHeart size={19} />공유하고 도움 요청하기</Button>
          </> : <div className="info-box">연결된 지원자가 없어요. 송금을 잠시 멈추고, 설정에서 지원자 연결을 확인하거나 믿을 수 있는 사람에게 직접 물어봐 주세요.</div>}
          <Button className="full" variant="secondary" disabled={busy} onClick={() => goTo('warning')}>이전으로</Button>
          <Button className="full" variant="ghost" disabled={busy} onClick={closeDraft}>송금을 멈출게요</Button>
        </>}

        {step === 'shared' && <>
          <SuccessIcon />
          <p className="center">연결된 지원자에게 송금 예정 내용을 공유했어요.<br />아직 돈은 보내지 않았어요.</p>
          <div className="info-box">도움 요청은 송금 승인이 아니에요. 걱정된다면 지원자와 이야기한 뒤 진행해 주세요.</div>
          <Button className="full" onClick={closeDraft}>송금을 멈추고 기다릴게요</Button>
          <Button className="full" variant="secondary" onClick={() => goTo('confirm')}>보낼 내용 확인<ArrowRight size={18} /></Button>
        </>}

        {step === 'confirm' && <>
          <div className="confirm-recipient"><span className="avatar large">{draft.recipient.initial}</span><h3>{draft.recipient.name}님에게</h3><p className="confirm-amount">{won(draft.amount)}</p></div>
          <div className="receipt"><div><span>받는 계좌</span><strong>{draft.recipient.bank} {draft.recipient.account_hint}</strong></div><div><span>보낸 뒤 잔액</span><strong>{won(draft.projectedBalance)}</strong></div></div>
          <ErrorMessage>{error}</ErrorMessage>
          <Button className="full" busy={busy} onClick={send}><Send size={18} />보내기</Button>
          <Button className="full" variant="secondary" disabled={busy} onClick={() => draft.requiresReview ? goTo('warning') : closeDraft()}>다시 확인할게요</Button>
        </>}
      </>}
    </Modal>

    <Modal open={Boolean(result)} title="송금이 끝났어요" onClose={() => setResult(null)}>
      {result && <><SuccessIcon /><p className="center"><strong>{result.recipient.name}</strong>님에게<br /><span className="confirm-amount">{won(result.transaction.amount)}</span>을 보냈어요.</p><p className="center muted">현재 잔액 {won(result.transaction.balance_after)}</p>{result.alert_ids?.length > 0 && <div className="callout">함께 확인할 알림이 있어요. 쉬운 설명을 살펴봐요.</div>}<Button className="full" onClick={() => { const alertId = result.alert_ids?.[0]; setResult(null); navigate(alertId ? `/alerts/${alertId}` : '/transactions'); }}>{result.alert_ids?.length ? '알림 확인하기' : '거래 내역 보기'}<ChevronRight size={18} /></Button><Link to="/" className="button button-secondary" onClick={() => setResult(null)}>홈으로</Link></>}
    </Modal>
  </>;
}
