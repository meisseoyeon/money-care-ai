import React, { useState } from 'react';
import { ChevronDown, HandHeart, RefreshCw, UsersRound } from 'lucide-react';
import { useApp } from '../../shared/state/AppContext.js';
import { formatTime } from '../../shared/lib/format.js';
import { Badge, Button, Card, Empty, ErrorMessage, PageTitle } from '../../shared/ui/UI.jsx';
import Guide from '../alerts/Guide.jsx';

export default function SupporterPage() {
  const { user, data, reload } = useApp(); const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const refresh = async () => { setBusy(true); setError(''); try { await reload(); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  return <><PageTitle eyebrow="함께 살펴보기" title={`${user.display_name}님에게 공유된 알림`} description="당사자가 도움을 요청하며 공유한 내용만 보여요." action={<Button variant="secondary" busy={busy} onClick={refresh}><RefreshCw size={17} />새로고침</Button>} /><div className="privacy-note"><UsersRound size={22} /><p>통장 전체 내역은 볼 수 없어요. 연결이나 공유가 철회되면 알림도 더 이상 표시되지 않아요.</p></div><ErrorMessage>{error}</ErrorMessage>{data.sharedAlerts?.length ? <div className="supporter-list">{data.sharedAlerts.map((a) => <Card key={a.share_id}><div className="section-heading"><div className="row"><span className="avatar peach">{a.owner_name?.slice(0, 1)}</span><div><h2>{a.owner_name}님이 도움을 요청했어요</h2><p className="helper">{formatTime(a.shared_at)}</p></div></div><Badge tone="green">공유 중</Badge></div><h3>{a.title}</h3><details className="shared-detail"><summary>알림 자세히 보기<ChevronDown size={18} /></summary><div className="shared-content"><p className="easy-explanation">{a.explanation || '설명을 아직 준비하지 못했어요. 당사자와 함께 알림을 확인해 주세요.'}</p>{a.guide ? <Guide guide={a.guide} /> : <div className="info-box"><HandHeart size={20} /><p>당사자와 함께 계획한 거래인지 먼저 확인해 주세요.</p></div>}</div></details></Card>)}</div> : <Card><Empty title="아직 공유받은 알림이 없어요" description="당사자가 ‘도와주세요’를 눌러 공유하면 여기에 표시돼요." /></Card>}</>;
}
