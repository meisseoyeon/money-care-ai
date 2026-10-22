import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

from sqlalchemy import event, text

from app.documents.ingest import cached_embedding, ingest_documents, normalized_vector, store_document
from app.documents.prepare import DIMENSIONS, MAX_CHARS, Source, load_manifest, normalize, prepare
from tests.postgres_support import PostgresSchemaTestCase


def source(root, *, url="https://example.go.kr/prevention", version="v1", paragraphs=None):
    body = [{"heading": "송금 전 확인", "location": "HTML 본문: 송금 전 확인",
             "tags": ["VOICE_PHISHING", "PREVENTION"],
             "paragraphs": paragraphs or ["이 문장은 적재 기능 검증용 합성 문장입니다."]}]
    (root / "body.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return Source(title="합성 테스트 자료", org="테스트 기관", publisher="테스트 게시 기관", url=url,
                  document_version=version, doc_type="RESPONSE", collected_at="2026-10-22T05:00:00Z",
                  published_at="2026-10-01T00:00:00+09:00", review_status="APPROVED",
                  license="KOGL-1", license_url=url, license_checked_at="2026-10-22T05:00:00Z",
                  review_note="합성 테스트 전용. 공식 자료를 사칭하지 않습니다.", body_file="body.json")


class DocumentPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_shipped_manifest_has_three_reviewed_sources_and_locatable_chunks(self):
        path = Path(__file__).resolve().parents[2] / "database/documents/manifest.json"
        docs, skipped = load_manifest(path)
        self.assertEqual(len(docs), 3)
        self.assertEqual(skipped, [])
        self.assertTrue(any("AFTER_TRANSFER" in c.tags for d in docs for c in d.chunks))
        self.assertTrue(any("PREVENTION" in c.tags for d in docs for c in d.chunks))
        for doc in docs:
            self.assertEqual(doc.source.license, "KOGL-1")
            for chunk in doc.chunks:
                self.assertIn("[위치:", chunk.content)
                self.assertLessEqual(len(chunk.content), MAX_CHARS)

    def test_hold_without_body_is_skipped_before_file_or_embedding_access(self):
        entry = source(self.root).model_dump(mode="json")
        entry.update(review_status="HOLD", body_file="missing.json", license="UNKNOWN")
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"documents": [entry]}), encoding="utf-8")
        docs, skipped = load_manifest(path)
        self.assertEqual(docs, [])
        self.assertEqual(skipped[0]["status"], "HOLD")

    def test_unknown_license_and_unchecked_attachment_cannot_be_approved(self):
        entry = source(self.root).model_dump(mode="json")
        for changed in ({"license": "UNKNOWN"}, {"license_url": None},
                        {"file_url": "https://example.go.kr/a.pdf", "attachment_license": "UNKNOWN"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                Source.model_validate({**entry, **changed})

    def test_stable_ids_normalization_and_no_arbitrary_split_of_long_procedure(self):
        entry = source(self.root, paragraphs=["조건입니다.\r\n112로 요청합니다.  ", "예외는 확인하세요."])
        first, second = prepare(entry, self.root), prepare(entry, self.root)
        self.assertEqual(first, second)
        self.assertIn("112로 요청합니다.", first.chunks[0].content)
        self.assertEqual(normalize("가\r\n나  "), "가\n나")
        entry = source(self.root, paragraphs=["가" * 1600])
        with self.assertRaisesRegex(ValueError, "직접 나눠"):
            prepare(entry, self.root)

    def test_external_files_and_unknown_tags_are_rejected(self):
        entry = source(self.root).model_copy(update={"body_file": "../outside.json"})
        with self.assertRaises(ValueError):
            prepare(entry, self.root)
        entry = source(self.root)
        path = self.root / "body.json"
        sections = json.loads(path.read_text(encoding="utf-8"))
        sections[0]["tags"] = ["UNREVIEWED_TAG"]
        path.write_text(json.dumps(sections), encoding="utf-8")
        with self.assertRaises(ValueError):
            prepare(entry, self.root)

    def test_cache_reuses_valid_vectors_and_rejects_bad_api_output(self):
        chunk = prepare(source(self.root), self.root).chunks[0]
        embed = Mock(return_value=[1.0] * DIMENSIONS)
        first = cached_embedding(chunk, self.root / "cache", embed)
        second = cached_embedding(chunk, self.root / "cache", embed)
        embed.assert_called_once()
        self.assertAlmostEqual(math.hypot(*first), 1)
        self.assertEqual(first, second)
        for invalid in ([0.0] * DIMENSIONS, [1] * 768, [float("nan")] * DIMENSIONS,
                        [float("inf")] * DIMENSIONS, [True] * DIMENSIONS):
            with self.subTest(length=len(invalid)), self.assertRaises(ValueError):
                normalized_vector(invalid)


@unittest.skipUnless(os.getenv("DEMO_TEST_DATABASE_URL"), "PostgreSQL integration mode required")
class DocumentStorageTests(PostgresSchemaTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.url = "https://example.go.kr/" + uuid4().hex
        self.paragraphs = [f"적재 검증용 합성 문장입니다. 테스트 식별자 {self.url}"]
        self.doc = prepare(source(self.root, url=self.url, paragraphs=self.paragraphs), self.root)
        self.embed = Mock(return_value=[1.0] * DIMENSIONS)

    def saved(self, doc):
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT status FROM documents WHERE id=:id"), {"id": doc.id}).scalar()

    def test_atomic_ready_storage_rerun_and_source_metadata(self):
        result = ingest_documents(self.engine, [self.doc], self.root / "cache", embed=self.embed)
        self.assertEqual(result[0]["status"], "IMPORTED")
        again = ingest_documents(self.engine, [self.doc], self.root / "cache", embed=self.embed)
        self.assertEqual(again[0]["status"], "UNCHANGED")
        self.embed.assert_called_once()
        with self.engine.connect() as conn:
            row = conn.execute(text("""SELECT c.embedding_status, vector_dims(c.embedding) AS dims,
                c.content, d.license FROM doc_chunks c JOIN documents d ON d.id=c.document_id
                WHERE d.id=:id"""), {"id": self.doc.id}).mappings().one()
        self.assertEqual(row["dims"], 1024)
        self.assertEqual(row["embedding_status"], "READY")
        self.assertIn("[위치:", row["content"])
        self.assertEqual(json.loads(row["license"])["raw_hash"], self.doc.raw_hash)

    def test_mid_insert_failure_rolls_back_and_retry_reuses_embedding(self):
        def fail(conn, cursor, statement, parameters, context, executemany):
            if "INSERT INTO doc_chunks" in statement:
                raise RuntimeError("forced database failure")
        event.listen(self.engine, "before_cursor_execute", fail)
        try:
            result = ingest_documents(self.engine, [self.doc], self.root / "cache", embed=self.embed)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail)
        self.assertEqual(result[0]["status"], "FAILED")
        self.assertIsNone(self.saved(self.doc))
        result = ingest_documents(self.engine, [self.doc], self.root / "cache", embed=self.embed)
        self.assertEqual(result[0]["status"], "IMPORTED")
        self.embed.assert_called_once()

    def test_api_failure_does_not_publish_document(self):
        result = ingest_documents(self.engine, [self.doc], self.root / "cache",
                                  embed=Mock(side_effect=RuntimeError("forced API failure")))
        self.assertEqual(result[0]["status"], "FAILED")
        self.assertIsNone(self.saved(self.doc))

    def test_changed_same_version_is_rejected_and_new_version_preserves_old_chunks(self):
        ingest_documents(self.engine, [self.doc], self.root / "cache", embed=self.embed)
        spec = source(self.root, url=self.url, paragraphs=["새로운 합성 문장입니다."])
        changed = prepare(spec, self.root)
        result = ingest_documents(self.engine, [changed], self.root / "cache", embed=self.embed)
        self.assertEqual(result[0]["status"], "FAILED")
        self.assertEqual(self.saved(self.doc), "ACTIVE")
        new = prepare(spec.model_copy(update={"document_version": "v2"}), self.root)
        failed = ingest_documents(self.engine, [new], self.root / "cache",
                                  embed=Mock(side_effect=RuntimeError("forced new version failure")))
        self.assertEqual(failed[0]["status"], "FAILED")
        self.assertEqual(self.saved(self.doc), "ACTIVE")
        self.assertIsNone(self.saved(new))
        result = ingest_documents(self.engine, [new], self.root / "cache", embed=self.embed)
        self.assertEqual(result[0]["status"], "IMPORTED")
        self.assertEqual(self.saved(self.doc), "RETIRED")
        self.assertEqual(self.saved(new), "ACTIVE")
        with self.engine.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM doc_chunks WHERE document_id=:id"),
                                          {"id": self.doc.id}).scalar(), 1)

    def test_same_body_other_url_is_reported_as_duplicate(self):
        ingest_documents(self.engine, [self.doc], self.root / "cache", embed=self.embed)
        other = prepare(source(self.root, url=self.url + "/mirror", paragraphs=self.paragraphs), self.root)
        result = ingest_documents(self.engine, [other], self.root / "cache", embed=self.embed)
        self.assertTrue(result[0]["status"].startswith("DUPLICATE:"))
        self.assertIsNone(self.saved(other))

    def test_same_document_concurrent_import_is_idempotent(self):
        from concurrent.futures import ThreadPoolExecutor
        vector = [1.0] * DIMENSIONS
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: store_document(self.engine, self.doc, [vector]), range(2)))
        self.assertCountEqual(statuses, ["IMPORTED", "UNCHANGED"])
