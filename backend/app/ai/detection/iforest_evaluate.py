"""Isolation Forest(머신러닝 이상 탐지)를 규칙과 같은 평가 시나리오로 비교하는 도구. 실제 알림에는 쓰지 않음(SHADOW).

설치 (평가용, 서버에는 필요 없음):
    pip install -r requirements.txt -r requirements-eval.txt
실행 (backend 폴더에서):
    python -m app.ai.detection.iforest_evaluate ../database/evaluation/detection_scenarios.json
"""
import argparse
import json
import math
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest

from app.ai.detection.evaluate import load_demo_history, predict, score
from app.baselines.calculator import calculate_baseline

DEMO_USER_ID = "user1"
DETECTOR_VERSION = "iforest-v1"
RANDOM_STATE = 42  # 같은 데이터면 항상 같은 결과가 나오게 고정
THRESHOLD_PERCENTILE = 5  # 평소 거래 점수 하위 5%보다 낮으면 이상 (규칙의 p95와 같은 발상)


def make_features(amount: int, is_new_counterparty: bool) -> list[float]:
    """송금 하나를 숫자 2개로 바꿈. 모델은 숫자만 이해함."""
    return [
        math.log1p(amount),               # 금액 (로그: 1만원과 2만원 차이 ≒ 10만원과 20만원 차이)
        1.0 if is_new_counterparty else 0.0,  # 처음 보내는 상대면 1
    ]


def history_features(history) -> list[list[float]]:
    """평소 출금 거래를 시간 순서대로 보며, 그때 기준으로 처음 보는 상대였는지 계산."""
    seen: set[str] = set()
    rows = []
    for h in sorted(history, key=lambda h: h["occurred_at"]):
        if h["direction"] != "OUT":
            continue
        cp = h["counterparty_id"]
        rows.append(make_features(h["amount"], cp is not None and cp not in seen))
        if cp:
            seen.add(cp)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", type=Path)
    args = parser.parse_args()
    scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))

    as_of, history = load_demo_history()
    past_ids = {h["counterparty_id"] for h in history if h["direction"] == "OUT" and h["counterparty_id"]}

    # 1. 평소 거래로 "정상이 어떤 모습인지" 학습 (정답 라벨은 학습에 쓰지 않음)
    train = np.array(history_features(history))
    model = IsolationForest(n_estimators=200, random_state=RANDOM_STATE).fit(train)
    # 점수가 낮을수록 이상. 평소 거래 점수의 하위 5%를 기준선으로
    threshold = float(np.percentile(model.score_samples(train), THRESHOLD_PERCENTILE))

    # 2. 같은 시나리오를 규칙과 모델로 각각 판단
    baseline = calculate_baseline([type("Tx", (), dict(h))() for h in history], user_id=DEMO_USER_ID, as_of=as_of)
    p95 = int(round(baseline.p95_out_amount))
    rule_rows, model_rows = [], []
    for s in scenarios:
        is_new = s["counterparty_id"] not in past_ids
        model_score = float(model.score_samples(np.array([make_features(s["amount"], is_new)]))[0])
        rule_rows.append({**s, "alerted": bool(predict(s, past_ids, p95))})
        model_rows.append({**s, "alerted": model_score < threshold, "score": model_score})

    rule, ml = score(rule_rows), score(model_rows)
    print(f"학습: user1 평소 출금 {len(train)}건, 이상 기준 점수 {threshold:.3f} (하위 {THRESHOLD_PERCENTILE}%)\n")
    print(f"{'ID':4} {'정답':6} {'규칙':6} {'모델':6} {'모델 점수':>9}  설명")
    for r, m in zip(rule_rows, model_rows):
        mark = lambda row: "🔔" if row["alerted"] else "-"
        print(f"{r['id']:4} {r['label']:6} {mark(r):6} {mark(m):6} {m['score']:9.3f}  {r['description']}")
    print(f"\n{'':10}{'잡음':>4} {'놓침':>4} {'괜히 울림':>6} {'조용':>4}   재현율  정밀도")
    for name, res in (("규칙", rule), ("Isolation Forest", ml)):
        pct = lambda v: "-" if v is None else f"{v:.0%}"
        print(f"{name:16}{res['tp']:>3} {res['fn']:>4} {res['fp']:>6} {res['tn']:>6}   {pct(res['recall']):>5}  {pct(res['precision']):>5}")

    report = {"detector_version": DETECTOR_VERSION, "execution_mode": "SHADOW", "train_count": len(train),
              "threshold": threshold, "threshold_percentile": THRESHOLD_PERCENTILE,
              "rules": rule, "iforest": ml,
              "rows": [{"id": m["id"], "label": m["label"], "rule_alerted": r["alerted"],
                        "iforest_alerted": m["alerted"], "iforest_score": round(m["score"], 4)}
                       for r, m in zip(rule_rows, model_rows)]}
    out = args.scenarios.parent / "iforest_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n보고서: {out}")


if __name__ == "__main__":
    main()
