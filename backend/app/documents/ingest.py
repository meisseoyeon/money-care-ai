"""문서별 원자적 적재. 외부 API 호출은 DB 트랜잭션 밖에서 수행합니다."""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.documents.prepare import CHUNKING_VERSION, DIMENSIONS, EMBEDDING_VERSION, MODEL, digest


def normalized_vector(values):
    if len(values) != DIMENSIONS or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        raise ValueError("임베딩은 유한한 숫자 1024개여야 합니다.")
    norm = math.hypot(*values)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("영벡터 또는 잘못된 크기의 벡터는 저장할 수 없습니다.")
    return [v / norm for v in values]


def gemini_embed(content, *, task_type="RETRIEVAL_DOCUMENT"):
    # 이 모듈을 import하거나 앱을 시작하는 것만으로 API를 호출하지 않습니다.
    from app.core.config import GEMINI_API_KEY
    if not GEMINI_API_KEY:
        raise ValueError("backend/.env에 GEMINI_API_KEY를 설정해 주세요.")
    from google import genai
    from google.genai import types
    with genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=30000)) as client:
        result = client.models.embed_content(model=MODEL, contents=content,
            config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=DIMENSIONS))
    if not result.embeddings or len(result.embeddings) != 1 or not result.embeddings[0].values:
        raise ValueError("청크 하나에 대한 임베딩 하나가 필요합니다.")
    return result.embeddings[0].values


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def cached_embedding(chunk, cache_dir: Path, embed):
    key = digest(f"{MODEL}:{EMBEDDING_VERSION}:{DIMENSIONS}:RETRIEVAL_DOCUMENT:{chunk.content_hash}")
    path = cache_dir / f"{key}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("key") != key:
            raise ValueError("임베딩 캐시 식별자가 일치하지 않습니다.")
        return normalized_vector(cached["vector"])
    vector = normalized_vector(embed(chunk.content))
    atomic_json(path, {"key": key, "vector": vector})
    return vector


def license_record(doc):
    source = doc.source
    return json.dumps({"terms": source.license, "evidence_url": str(source.license_url),
        "checked_at": source.license_checked_at.isoformat(), "attachment_terms": source.attachment_license,
        "publisher": source.publisher, "file_url": str(source.file_url) if source.file_url else None,
        "review_note": source.review_note, "raw_hash": doc.raw_hash}, ensure_ascii=False, sort_keys=True)


def existing_document(conn, doc):
    row = conn.execute(text("SELECT * FROM documents WHERE url=:url AND document_version=:version"),
                       {"url": str(doc.source.url), "version": doc.source.document_version}).mappings().first()
    if row is None:
        return False
    expected = {"id": doc.id, "title": doc.source.title, "org": doc.source.org,
                "doc_type": doc.source.doc_type, "content_hash": doc.content_hash, "license": license_record(doc),
                "published_at": doc.source.published_at, "collected_at": doc.source.collected_at}
    if any(row[key] != value for key, value in expected.items()):
        raise ValueError("같은 URL·버전의 내용/메타데이터가 바뀌었습니다. 새 문서 버전을 사용하세요.")
    rows = conn.execute(text("""SELECT id, chunk_index, content, content_hash, situation_tags,
        embedding_status, embedding IS NOT NULL AS has_vector FROM doc_chunks
        WHERE document_id=:id AND chunking_version=:chunking AND embedding_model=:model
          AND embedding_version=:version ORDER BY chunk_index"""),
        {"id": doc.id, "chunking": CHUNKING_VERSION, "model": MODEL, "version": EMBEDDING_VERSION}).mappings().all()
    if len(rows) != len(doc.chunks):
        raise ValueError("기존 청크 구성이 다릅니다. 새 문서/청크 버전이 필요합니다.")
    for row, chunk in zip(rows, doc.chunks):
        if (row["id"] != chunk.id or row["chunk_index"] != chunk.index or row["content"] != chunk.content
                or row["content_hash"] != chunk.content_hash or row["situation_tags"] != chunk.tags
                or row["embedding_status"] != "READY" or not row["has_vector"]):
            raise ValueError("기존 청크가 현재 입력과 다르거나 준비되지 않았습니다.")
    return True


def store_document(engine, doc, vectors):
    if len(vectors) != len(doc.chunks):
        raise ValueError("청크와 벡터 개수가 다릅니다.")
    vectors = [normalized_vector(v) for v in vectors]
    source = doc.source
    with engine.begin() as conn:
        # 같은 URL의 동시 적재/개정판 발행을 직렬화합니다.
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:url, 0))"), {"url": str(source.url)})
        if existing_document(conn, doc):
            return "UNCHANGED"
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:hash, 1))"), {"hash": doc.content_hash})
        duplicate = conn.execute(text("SELECT id FROM documents WHERE content_hash=:hash AND url<>:url AND status='ACTIVE' LIMIT 1"),
                                 {"hash": doc.content_hash, "url": str(source.url)}).scalar()
        if duplicate:
            return f"DUPLICATE:{duplicate}"
        conn.execute(text("""INSERT INTO documents
            (id,title,org,doc_type,url,document_version,content_hash,collected_at,published_at,license,status)
            VALUES (:id,:title,:org,:type,:url,:version,:hash,:collected,:published,:license,'ACTIVE')"""),
            {"id": doc.id, "title": source.title, "org": source.org, "type": source.doc_type,
             "url": str(source.url), "version": source.document_version, "hash": doc.content_hash,
             "collected": source.collected_at, "published": source.published_at, "license": license_record(doc)})
        for chunk, vector in zip(doc.chunks, vectors):
            conn.execute(text("""INSERT INTO doc_chunks
                (id,document_id,chunk_index,content,content_hash,chunking_version,situation_tags,
                 embedding_model,embedding_version,embedding_status,embedding,embedded_at)
                VALUES (:id,:document,:index,:content,:hash,:chunking,CAST(:tags AS jsonb),
                        :model,:version,'READY',CAST(:vector AS vector),CURRENT_TIMESTAMP)"""),
                {"id": chunk.id, "document": doc.id, "index": chunk.index, "content": chunk.content,
                 "hash": chunk.content_hash, "chunking": CHUNKING_VERSION, "tags": json.dumps(chunk.tags),
                 "model": MODEL, "version": EMBEDDING_VERSION, "vector": json.dumps(vector, allow_nan=False)})
        # 새 버전 청크 저장까지 성공했을 때만 과거 버전을 검색 대상에서 제외합니다.
        conn.execute(text("UPDATE documents SET status='RETIRED' WHERE url=:url AND id<>:id AND status='ACTIVE'"),
                     {"url": str(source.url), "id": doc.id})
    return "IMPORTED"


def ingest_documents(engine, documents, cache_dir: Path, *, embed=gemini_embed):
    results = []
    for doc in documents:
        try:
            with engine.connect() as conn:
                exists = existing_document(conn, doc)
            if exists:
                status = "UNCHANGED"
            else:
                vectors = []
                for chunk in doc.chunks:
                    attempt = {"document_id": doc.id, "chunk_id": chunk.id,
                               "content_hash": chunk.content_hash,
                               "attempted_at": datetime.now(timezone.utc).isoformat()}
                    try:
                        vectors.append(cached_embedding(chunk, cache_dir, embed))
                        attempt["status"] = "READY"
                    except Exception as exc:
                        attempt.update(status="FAILED", error_type=type(exc).__name__)
                        raise
                    finally:
                        atomic_json(cache_dir / "attempts" / f"{chunk.id}.json", attempt)
                status = store_document(engine, doc, vectors)
            result = {"document_id": doc.id, "url": str(doc.source.url), "status": status,
                      "chunks": len(doc.chunks)}
        except Exception as exc:
            # API 응답/키/전체 본문을 로그에 출력하지 않습니다.
            result = {"document_id": doc.id, "status": "FAILED", "error_type": type(exc).__name__}
        results.append(result)
        atomic_json(cache_dir / "last-run.json", {"at": datetime.now(timezone.utc).isoformat(), "results": results})
    return results
