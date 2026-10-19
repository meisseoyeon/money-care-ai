import React, { useState } from 'react';
import { ArrowDownLeft, ArrowUpRight, ChevronDown } from 'lucide-react';
import { useApp } from '../context/AppContext.jsx';
import { formatTime, won } from '../lib/domain.js';
import { Button, Card, Empty, PageTitle } from '../components/UI.jsx';

export default function TransactionsPage() {
  const { data } = useApp(); const [filter, setFilter] = useState('ALL'), [limit, setLimit] = useState(15);
  const list = (data.transactions ?? []).filter((t) => filter === 'ALL' || t.direction === filter);
  return <><PageTitle eyebrow="통장 기록" title="내 거래 내역" description="들어온 돈과 나간 돈을 한눈에 살펴봐요." /><Card><div className="section-heading"><div className="segmented" role="group" aria-label="입출금 필터">{[['ALL','전체'],['OUT','나간 돈'],['IN','들어온 돈']].map(([key,label]) => <button key={key} aria-pressed={filter === key} className={filter === key ? 'active' : ''} onClick={() => { setFilter(key); setLimit(15); }}>{label}</button>)}</div><span className="helper">총 {list.length}건</span></div>{list.length ? <div className="history-list">{list.slice(0,limit).map((t) => <details key={t.id} className="history-item"><summary><span className={`transaction-icon ${t.direction === 'IN' ? 'incoming' : ''}`}>{t.direction === 'IN' ? <ArrowDownLeft size={20} /> : <ArrowUpRight size={20} />}</span><div className="grow"><strong>{t.description}</strong><small>{formatTime(t.occurred_at)}</small></div><div className="history-value"><strong className={t.direction === 'IN' ? 'positive' : ''}>{t.direction === 'IN' ? '+' : '−'}{won(t.amount)}</strong><small>잔액 {won(t.balance_after)}</small></div><ChevronDown size={16} className="detail-chevron" /></summary><div className="history-detail"><p><span>거래 종류</span>{({ TRANSFER:'송금', PURCHASE:'구매', INCOME:'수입', REFUND:'환불', WITHDRAWAL:'출금', DEPOSIT:'입금' })[t.tx_type] || t.tx_type}</p><p><span>거래 후 잔액</span>{won(t.balance_after)}</p><p><span>거래 구분</span>가상 거래</p></div></details>)}</div> : <Empty title="해당하는 거래가 없어요" description="다른 조건을 선택해 보세요." />}{list.length>limit && <Button variant="secondary" className="full load-more" onClick={() => setLimit(limit+15)}>이전 거래 더 보기</Button>}</Card></>;
}
