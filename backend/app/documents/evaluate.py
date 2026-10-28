"""고정 질문으로 적재/검색 계약을 확인하는 도구. 운영 RAG/근거 부족 정책은 와우 담당."""

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import text

from app.documents.ingest import atomic_json, gemini_embed, normalized_vector
from app.documents.prepare import CHUNKING_VERSION, DIMENSIONS, EMBEDDING_VERSION, MODEL, TAGS, StrictModel, digest


class EvaluationCase(StrictModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    stage: Literal["BEFORE_TRANSFER", "AFTER_TRANSFER"] | None = None
    situation_tags: list[str] = []
    expected_chunk_ids: list[str] = []
    expected_no_answer: bool = False

    @model_validator(mode="after")
    def valid(self):
        if set(self.situation_tags) - TAGS:
            raise ValueError("알 수 없는 상황 태그입니다.")
        if {"BEFORE_TRANSFER", "AFTER_TRANSFER"} & set(self.situation_tags):
            raise ValueError("송금 단계는 stage에만 지정하세요.")
        if self.expected_no_answer == bool(self.expected_chunk_ids):
            raise ValueError("정답 청크 또는 근거 없음 중 하나를 지정하세요.")
        return self


def load_cases(path):
    cases = [EvaluationCase.model_validate(value) for value in json.loads(path.read_text(encoding="utf-8-sig"))]
    if not cases or len({c.id for c in cases}) != len(cases):
        raise ValueError("평가 ID는 비어 있지 않고 중복되지 않아야 합니다.")
    return cases


def query_embedding(question):
    return normalized_vector(gemini_embed(question, task_type="RETRIEVAL_QUERY"))


def search_for_evaluation(engine, vector, *, stage=None, situation_tags=(), top_k=3, max_distance=None):
    if stage not in (None, "BEFORE_TRANSFER", "AFTER_TRANSFER") or set(situation_tags) - TAGS:
        raise ValueError("잘못된 검색 태그입니다.")
    if not 1 <= top_k <= 10:
        raise ValueError("top_k는 1~10입니다.")
    if max_distance is not None and (not math.isfinite(max_distance) or not 0 <= max_distance <= 2):
        raise ValueError("코사인 거리는 0~2의 유한값이어야 합니다.")
    tags = sorted(set(situation_tags) | ({stage} if stage else set()))
    opposite = "AFTER_TRANSFER" if stage == "BEFORE_TRANSFER" else "BEFORE_TRANSFER"
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT c.id AS chunk_id, c.document_id, c.content, c.situation_tags,
            c.embedding_model, c.embedding_version, c.chunking_version,
            c.embedding <=> CAST(:vector AS vector) AS distance,
            d.title, d.org, d.url, d.document_version, d.collected_at, d.published_at
            FROM doc_chunks c JOIN documents d ON d.id=c.document_id
            WHERE d.status='ACTIVE' AND c.embedding_status='READY'
              AND c.embedding_model=:model AND c.embedding_version=:version
              AND c.chunking_version=:chunking AND c.situation_tags @> CAST(:tags AS jsonb)
              AND (:no_stage OR NOT (c.situation_tags @> CAST(:opposite AS jsonb)))
            ORDER BY distance,c.id LIMIT :limit"""),
            {"vector": json.dumps(normalized_vector(vector)), "model": MODEL, "version": EMBEDDING_VERSION,
             "chunking": CHUNKING_VERSION, "tags": json.dumps(tags), "no_stage": stage is None,
             "opposite": json.dumps([opposite]), "limit": top_k}).mappings().all()
    results = []
    for row in rows:
        if max_distance is not None and row["distance"] > max_distance:
            continue
        item = dict(row)
        item["embedding_dimensions"] = DIMENSIONS
        # 원문 위치는 기존 청크 접두사를 재사용하며 중복 컬럼을 만들지 않습니다.
        item["location"] = next((line[5:-1] for line in row["content"].splitlines() if line.startswith("[위치: ")), "")
        for key in ("collected_at", "published_at"):
            item[key] = item[key].isoformat() if item[key] else None
        results.append(item)
    return results


def evaluate(engine, cases, cache_dir, *, embed=query_embedding, max_distance=None):
    results = []
    cache_dir = Path(cache_dir)
    for case in cases:
        key = digest(f"RETRIEVAL_QUERY:{MODEL}:{EMBEDDING_VERSION}:{case.question}")
        path = cache_dir / "queries" / f"{key}.json"
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("key") != key:
                raise ValueError("질문 캐시 키가 다릅니다.")
            vector = normalized_vector(value["vector"])
        else:
            vector = normalized_vector(embed(case.question))
            atomic_json(path, {"key": key, "vector": vector})
        # 정답 정보는 검색/임베딩 입력에 사용하지 않고 결과 채점에만 사용합니다.
        hits = search_for_evaluation(engine, vector, stage=case.stage,
                                    situation_tags=case.situation_tags, max_distance=max_distance)
        found = bool(set(case.expected_chunk_ids) & {h["chunk_id"] for h in hits})
        status = ("REVIEW_REQUIRED" if case.expected_no_answer and max_distance is None
                  else "PASS" if (not hits if case.expected_no_answer else found) else "FAIL")
        results.append({**case.model_dump(), "status": status, "hit_at_3": found if not case.expected_no_answer else None,
                        "retrieved": hits})
    positives = [r for r in results if not r["expected_no_answer"]]
    report = {"model": MODEL, "dimensions": DIMENSIONS, "embedding_version": EMBEDDING_VERSION,
              "chunking_version": CHUNKING_VERSION, "max_distance": max_distance,
              "answerable_count": len(positives), "hits_at_3": sum(r["hit_at_3"] for r in positives),
              "positive_target_met": bool(positives) and sum(r["hit_at_3"] for r in positives) >= math.ceil(len(positives) * 7 / 8),
              "negative_review_required": sum(r["status"] == "REVIEW_REQUIRED" for r in results),
              "results": results}
    atomic_json(cache_dir / "evaluation-report.json", report)
    return report


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="질문 10개로 적재/검색 계약 검증 (운영 RAG 아님)")
    parser.add_argument("cases", type=Path)
    parser.add_argument("--max-distance", type=float, help="와우 담당 근거 부족 정책이 정한 임계값. 생략 시 음성 질문은 검토 필요")
    args = parser.parse_args()
    from app.core.config import DATABASE_URL, GEMINI_API_KEY
    if not DATABASE_URL or not GEMINI_API_KEY:
        parser.error("DATABASE_URL과 GEMINI_API_KEY가 필요합니다.")
    from sqlalchemy import create_engine
    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})
    try:
        report = evaluate(engine, load_cases(args.cases), args.cases.resolve().parent / ".cache",
                          max_distance=args.max_distance)
        print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))
        print("상세 결과: database/documents/.cache/evaluation-report.json")
        return 1 if any(r["status"] == "FAIL" for r in report["results"]) else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
