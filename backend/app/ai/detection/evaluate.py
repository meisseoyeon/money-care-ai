"""평가 시나리오로 탐지 규칙의 성능(잡은 것, 놓친 것)을 계산하는 도구.

실행 (backend 폴더에서):
    python -m app.ai.detection.evaluate ../database/evaluation/detection_scenarios.json
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import text

from app.ai.detection.rules import check_large_outflow, check_new_counterparty
from app.baselines.calculator import calculate_baseline
from app.db.session import session_factory

DEMO_USER_ID = "user1"


def predict(scenario: dict, past_counterparty_ids: set[str], p95: int | None) -> list[str]:
    """시나리오 하나에 규칙 2개를 실행해서 걸린 규칙 이름 목록을 돌려줌. 빈 목록이면 알림 없음."""
    results = [
        check_new_counterparty(scenario["counterparty_id"], past_counterparty_ids),
        check_large_outflow(scenario["amount"], p95),
    ]
    return [r.detection_type for r in results if r is not None]


def score(rows: list[dict]) -> dict:
    """정답(label)과 예측(alerted)을 비교해 4칸과 지표를 계산."""
    # rows의 각 항목: {"label": "RISK" 또는 "NORMAL", "alerted": True 또는 False, ...}
    tp = sum(1 for r in rows if r["label"] == "RISK" and r["alerted"])          # 잡음
    fn = sum(1 for r in rows if r["label"] == "RISK" and not r["alerted"])      # 놓침
    fp = sum(1 for r in rows if r["label"] == "NORMAL" and r["alerted"])        # 괜히 울림
    tn = sum(1 for r in rows if r["label"] == "NORMAL" and not r["alerted"])    # 조용

    # 위험이나 알림이 하나도 없으면 나눌 수 없으므로 None
    recall = tp / (tp + fn) if tp + fn else None        # 위험 중 몇 %를 잡았나
    precision = tp / (tp + fp) if tp + fp else None     # 알림 중 몇 %가 진짜 위험이었나
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "recall": recall, "precision": precision}


def load_demo_history():
    """user1의 정상 거래 30일 치와 시드 기준 시각. 평가 기준은 체험을 시작한 시점의 평소 모습."""
    with session_factory()() as db:
        as_of = db.execute(text(
            "SELECT as_of FROM demo_seed_metadata WHERE user_id = :u"), {"u": DEMO_USER_ID}).scalar_one()
        history = db.execute(text("""
            SELECT user_id, occurred_at, direction, amount, counterparty_id FROM transactions
            WHERE user_id = :u AND source = 'SYNTHETIC' AND occurred_at < :as_of
        """), {"u": DEMO_USER_ID, "as_of": as_of}).mappings().all()
    return as_of, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", type=Path)
    args = parser.parse_args()
    scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))

    as_of, history = load_demo_history()
    baseline = calculate_baseline([type("Tx", (), dict(h))() for h in history], user_id=DEMO_USER_ID, as_of=as_of)
    p95 = int(round(baseline.p95_out_amount)) if baseline.p95_out_amount is not None else None
    past_ids = {h["counterparty_id"] for h in history if h["direction"] == "OUT" and h["counterparty_id"]}

    rows = []
    for s in scenarios:
        rules = predict(s, past_ids, p95)
        rows.append({**s, "alerted": bool(rules), "rules": rules})

    result = score(rows)
    print(f"기준: user1 정상 거래 {len(history)}건, 평소 기준 p95 = {p95:,}원, 평소 상대 {len(past_ids)}명\n")
    for r in rows:
        mark = {(True, "RISK"): "✅ 잡음", (False, "RISK"): "❌ 놓침",
                (True, "NORMAL"): "⚠️ 괜히 울림", (False, "NORMAL"): "✅ 조용"}[(r["alerted"], r["label"])]
        print(f"{r['id']}  {r['label']:6}  {mark:8}  {','.join(r['rules']) or '-':28}  {r['description']}")
    print(f"\n잡음 {result['tp']} / 놓침 {result['fn']} / 괜히 울림 {result['fp']} / 조용 {result['tn']}")
    print(f"재현율 {result['recall']:.0%}   정밀도 {result['precision']:.0%}")

    report = {"p95_out_amount": p95, "history_count": len(history), **result,
              "rows": [{k: r[k] for k in ("id", "label", "alerted", "rules")} for r in rows]}
    out = args.scenarios.parent / "detection_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n보고서: {out}")


if __name__ == "__main__":
    main()