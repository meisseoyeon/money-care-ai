import React from 'react';
import { BookOpen, ExternalLink } from 'lucide-react';
import { Badge } from '../../shared/ui/UI.jsx';

export default function Guide({ guide }) {
  if (!guide) return null;
  const steps = guide.steps ?? [];
  return <section className="guide"><div className="section-heading"><h3><BookOpen size={20} />지금 이렇게 해보세요</h3><Badge>{guide.method === 'FALLBACK' ? '기본 안내' : '근거 기반 안내'}</Badge></div><ol className="guide-steps">{steps.map((s, i) => <li key={i}><span className="step-number">{i + 1}</span><p>{typeof s === 'string' ? s : s.instruction}</p></li>)}</ol>{guide.citations?.length ? <details className="sources"><summary>안내 출처 확인</summary>{guide.citations.map((c, i) => { const url = /^https?:\/\//.test(c.url ?? '') ? c.url : null; return <div key={c.chunk_id ?? i}><strong>{c.title}</strong><p>{c.org} · 수집일 {c.collected_at}</p>{url && <a href={url} target="_blank" rel="noreferrer">원문 보기 <ExternalLink size={14} /></a>}</div>; })}</details> : <p className="helper">미리 준비한 기본 안내예요. 검색한 원문이나 AI 생성 결과로 표시하지 않아요.</p>}</section>;
}
