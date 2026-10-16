import React, { useState } from 'react';
import { LogOut, ShieldCheck, UsersRound } from 'lucide-react';
import { useApp } from '../context/AppContext.jsx';
import { Badge, Button, ErrorMessage, Modal } from './UI.jsx';

export default function SettingsModal({ open, onClose }) {
  const { data, user, run, logout, notify } = useApp(); const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const active = Boolean(user?.monitoring_consented_at && !user?.monitoring_revoked_at);
  const execute = async (name, ...args) => { setBusy(true); setError(''); try { await run(name, ...args); notify('설정을 저장했어요.'); } catch (e) { setError(e.message); } finally { setBusy(false); } };
  return <Modal open={open} title="내 설정" onClose={onClose}><p className="helper">{user?.display_name} · {user?.email}</p>{user?.role === 'OWNER' && <><div className="setting-block"><h3><ShieldCheck size={19} />모니터링</h3><p>송금과 생활비에서 평소와 다른 점을 확인해요.</p><div className="row"><Badge tone={active ? 'green' : 'neutral'}>{active ? '켜져 있어요' : '꺼져 있어요'}</Badge><Button variant="secondary" busy={busy} onClick={() => execute('setMonitoring', !active)}>{active ? '끄기' : '동의하고 켜기'}</Button></div></div><div className="setting-block"><h3><UsersRound size={19} />도움받을 사람</h3>{data?.links?.length ? data.links.map((l) => <div key={l.id}><div className="row"><span>{l.supporter_name ?? '지원자'} · {l.status === 'ACTIVE' ? '연결됨' : '연결 해제됨'}</span><Button variant="ghost" busy={busy} onClick={() => execute('setLink', l.id, l.status !== 'ACTIVE')}>{l.status === 'ACTIVE' ? '연결 해제' : '다시 연결'}</Button></div><p className="helper">연결을 해제하면 기존 알림 공유도 철회돼요.</p></div>) : <p>연결된 지원자가 없어요.</p>}</div></>}<ErrorMessage>{error}</ErrorMessage><Button variant="secondary" className="full" onClick={async () => { await logout(); onClose(); }}><LogOut size={18} />로그아웃</Button></Modal>;
}
