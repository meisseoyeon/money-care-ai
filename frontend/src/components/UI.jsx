import React, { useEffect, useId, useRef } from 'react';
import { ArrowRight, Check, ChevronLeft, Inbox, LoaderCircle, X } from 'lucide-react';
import { Link } from 'react-router-dom';

export function Button({ children, variant = 'primary', busy = false, disabled = false, type = 'button', className = '', ...props }) { return <button type={type} className={`button button-${variant} ${className}`} disabled={busy || disabled} {...props}>{busy && <LoaderCircle size={19} className="spin" aria-hidden="true" />}{children}</button>; }
export function PageTitle({ eyebrow, title, description, back, action }) { return <div className="page-title"><div>{back && <Link className="back-link" to={back}><ChevronLeft size={17} />돌아가기</Link>}{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1>{description && <p className="page-description">{description}</p>}</div>{action}</div>; }
export function Card({ children, className = '', ...props }) { return <section className={`card ${className}`} {...props}>{children}</section>; }
export function Empty({ title, description, to, action }) { return <div className="empty"><span className="empty-icon"><Inbox size={30} /></span><h3>{title}</h3><p>{description}</p>{to && <Link className="button button-secondary" to={to}>{action}<ArrowRight size={17} /></Link>}</div>; }
export function ErrorMessage({ children }) { return children ? <p className="error-message" role="alert">{children}</p> : null; }
export function Badge({ children, tone = 'neutral' }) { return <span className={`badge badge-${tone}`}>{children}</span>; }
export function Loading() { return <div className="loading" role="status"><LoaderCircle className="spin" size={26} />불러오고 있어요.</div>; }
export function Modal({ open, title, children, onClose }) {
  const ref = useRef(null), heading = useId();
  useEffect(() => { const dialog = ref.current; if (open && !dialog.open) dialog.showModal(); if (!open && dialog.open) dialog.close(); return () => { if (dialog.open) dialog.close(); }; }, [open]);
  return <dialog ref={ref} className="modal" aria-labelledby={heading} onCancel={(e) => { e.preventDefault(); onClose(); }}><div className="modal-header"><h2 id={heading}>{title}</h2><button className="icon-button" aria-label="닫기" onClick={onClose}><X size={22} /></button></div><div className="modal-body">{children}</div></dialog>;
}
export function SuccessIcon() { return <div className="success-icon"><Check size={30} strokeWidth={2.5} /></div>; }
