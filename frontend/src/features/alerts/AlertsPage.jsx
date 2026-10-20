import React, { useState } from 'react';
import { ArrowRight, Bell, Wallet } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useApp } from '../../shared/state/AppContext.js';
import { ALERT_LABELS, RESPONSE_LABELS } from './constants.js';
import { formatTime } from '../../shared/lib/format.js';
import { Badge, Card, Empty, PageTitle } from '../../shared/ui/UI.jsx';

export default function AlertsPage() {
  const { data } = useApp(); const [unanswered, setUnanswered] = useState(false);
  const alerts = (data.alerts ?? []).filter((a) => !unanswered || a.status !== 'ANSWERED');
  return <><PageTitle eyebrow="작은 확인, 더 큰 안심" title="함께 확인해봐요" description="알림은 사기를 단정하지 않아요. 계획한 일인지 살펴봐요." /><div className="alert-toolbar"><span>{data.alerts?.length ?? 0}개의 알림</span><label className="checkbox-label"><input type="checkbox" checked={unanswered} onChange={(e) => setUnanswered(e.target.checked)} />아직 답하지 않은 알림만</label></div>{alerts.length ? <div className="alert-grid">{alerts.map((a) => <Link key={a.id} to={`/alerts/${a.id}`} className={`card alert-card ${a.status === 'NEW' ? 'unread' : ''}`}><div className="row"><span className={`icon-tile ${a.alert_type === 'BUDGET_SHORTAGE' ? 'warm' : ''}`}>{a.alert_type === 'BUDGET_SHORTAGE' ? <Wallet size={23} /> : <Bell size={23} />}</span><Badge tone={a.status === 'NEW' ? 'peach' : 'neutral'}>{a.status === 'NEW' ? '새 알림' : a.status === 'ANSWERED' ? '응답했어요' : '확인했어요'}</Badge></div><span className="eyebrow">{ALERT_LABELS[a.alert_type] || '확인 알림'}</span><h2>{a.title}</h2><p>{a.explanation}</p><div className="alert-card-footer"><small>{formatTime(a.created_at)}</small><span>{a.user_response ? RESPONSE_LABELS[a.user_response] : '자세히 보기'} <ArrowRight size={17} /></span></div></Link>)}</div> : <Card><Empty title={unanswered ? '모든 알림에 답했어요' : '아직 확인할 알림이 없어요'} description="평소와 다른 송금이나 생활비 변화가 있으면 알려드릴게요." to="/transfer" action="돈 보내기" /></Card>}</>;
}
