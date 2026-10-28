import argparse
import json
import sys
from pathlib import Path

from app.documents.prepare import CHUNKING_VERSION, DIMENSIONS, EMBEDDING_VERSION, MODEL, load_manifest


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="검수 본문의 문서·청크·임베딩 수동 적재")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--apply", action="store_true", help="생략하면 API/DB 없이 검증·미리보기만 실행")
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    try:
        documents, skipped = load_manifest(args.manifest.resolve())
        print(json.dumps({"model": MODEL, "dimensions": DIMENSIONS, "embedding_version": EMBEDDING_VERSION,
            "chunking_version": CHUNKING_VERSION, "skipped": skipped,
            "documents": [{"id": d.id, "title": d.source.title, "content_hash": d.content_hash,
                           "raw_hash": d.raw_hash,
                           "chunks": [{"id": c.id, "tags": c.tags, "content": c.content} for c in d.chunks]}
                          for d in documents]}, ensure_ascii=False, indent=2))
        if not args.apply or not documents:
            return 0
        from app.core.config import DATABASE_URL, GEMINI_API_KEY
        if not DATABASE_URL or not GEMINI_API_KEY:
            parser.error("--apply에는 backend/.env의 DATABASE_URL과 GEMINI_API_KEY가 필요합니다.")
        from sqlalchemy import create_engine
        from app.documents.ingest import ingest_documents
        engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 5})
        try:
            results = ingest_documents(engine, documents, args.cache_dir or args.manifest.resolve().parent / ".cache")
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 1 if any(r["status"] == "FAILED" for r in results) else 0
        finally:
            engine.dispose()
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
