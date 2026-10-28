"""검수된 본문만 사용합니다. 다운로드/자동 요약/OCR은 하지 않습니다."""

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, model_validator

CHUNKING_VERSION = "section-v1"
MODEL = "gemini-embedding-001"
EMBEDDING_VERSION = "retrieval-1024-l2-v1"
DIMENSIONS = 1024
MAX_CHARS = 1500
TARGET_CHARS = 900
TAGS = {"VOICE_PHISHING", "PREVENTION", "AFTER_TRANSFER", "PERSONAL_DATA_EXPOSED",
        "PAYMENT_SUSPENSION", "MESSENGER_PHISHING", "SIMPLE_TRANSFER", "EASY_TERM",
        "TRANSFER_SCAM", "UNKNOWN_RECIPIENT", "BEFORE_TRANSFER"}


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def normalize(value: str) -> str:
    # 숫자·전화번호·기호는 보존합니다. 줄 끝 공백/개행만 정리합니다.
    value = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in value.splitlines()).strip()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    org: str = Field(min_length=1, max_length=100)
    publisher: str = Field(min_length=1, max_length=100)
    url: HttpUrl
    file_url: HttpUrl | None = None
    document_version: str = Field(min_length=1, max_length=50)
    doc_type: Literal["SCAM_CASE", "RESPONSE", "WELFARE", "EASY_TERM"]
    collected_at: AwareDatetime
    published_at: AwareDatetime | None = None
    review_status: Literal["APPROVED", "HOLD", "EXCLUDED"]
    license: Literal["KOGL-1", "PERMISSION", "UNKNOWN"] = "UNKNOWN"
    license_url: HttpUrl | None = None
    license_checked_at: AwareDatetime | None = None
    attachment_license: str = "NOT_USED"
    review_note: str = ""
    body_file: str | None = None
    raw_file: str | None = None

    @model_validator(mode="after")
    def approved(self):
        if self.review_status == "APPROVED":
            if self.license == "UNKNOWN" or not all((self.body_file, self.license_url,
                        self.license_checked_at, self.review_note)):
                raise ValueError("승인 문서는 본문 파일·이용 조건·확인 URL/시각·검토 메모가 필요합니다.")
            if self.file_url and self.attachment_license in ("", "NOT_USED", "UNKNOWN"):
                raise ValueError("첨부 파일의 이용 조건을 별도로 확인해 주세요.")
            if self.published_at and self.published_at > self.collected_at:
                raise ValueError("발행 시각이 수집 시각보다 미래입니다.")
        return self


class Section(StrictModel):
    heading: str = Field(min_length=1, max_length=180)
    location: str = Field(min_length=1, max_length=180)
    tags: list[str] = Field(min_length=1)
    paragraphs: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def content(self):
        if set(self.tags) - TAGS:
            raise ValueError("공통 태그 목록에 없는 값입니다.")
        if {"BEFORE_TRANSFER", "AFTER_TRANSFER"} <= set(self.tags):
            raise ValueError("송금 전·후 행동은 별도 섹션으로 구분해 주세요.")
        if any(not normalize(p) for p in self.paragraphs):
            raise ValueError("빈 문단은 허용하지 않습니다.")
        return self


class Manifest(StrictModel):
    documents: list[Source] = Field(min_length=1)


@dataclass(frozen=True)
class Chunk:
    id: str
    index: int
    content: str
    content_hash: str
    tags: list[str]


@dataclass(frozen=True)
class PreparedDocument:
    source: Source
    id: str
    content_hash: str
    raw_hash: str
    chunks: list[Chunk]


def local_file(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"manifest 폴더 안의 파일이 필요합니다: {name}")
    return path


def prepare(source: Source, root: Path) -> PreparedDocument:
    if source.review_status != "APPROVED":
        raise ValueError("승인되지 않은 자료는 처리할 수 없습니다.")
    path = local_file(root, source.body_file)
    sections = [Section.model_validate(s) for s in json.loads(path.read_text(encoding="utf-8-sig"))]
    if not sections:
        raise ValueError("본문에 섹션이 없습니다.")
    doc_id = "doc-" + digest(f"{source.url}\n{source.document_version}")
    chunks = []
    body = []
    for section in sections:
        prefix = f"[문서: {source.title}]\n[위치: {section.location}]\n[제목: {section.heading}]\n\n"
        parts = []
        current = ""
        for paragraph in section.paragraphs:
            paragraph = normalize(paragraph)
            # 조건과 행동이 임의로 갈라지지 않도록 긴 문단은 사람이 나누게 합니다.
            if len(prefix) + len(paragraph) > MAX_CHARS:
                raise ValueError(f"{section.location}: 문단이 너무 깁니다. 조건·절차 단위로 직접 나눠 주세요.")
            proposed = current + "\n\n" + paragraph if current else paragraph
            if current and len(prefix) + len(proposed) > TARGET_CHARS:
                parts.append(current)
                current = paragraph
            else:
                current = proposed
        if current:
            parts.append(current)
        body.append(section.heading + "\n" + "\n\n".join(normalize(p) for p in section.paragraphs))
        for part in parts:
            content = prefix + part
            index = len(chunks)
            key = f"{doc_id}:{index}:{CHUNKING_VERSION}:{MODEL}:{EMBEDDING_VERSION}"
            chunks.append(Chunk("chunk-" + digest(key), index, content, digest(content), sorted(set(section.tags))))
    raw = local_file(root, source.raw_file).read_bytes() if source.raw_file else path.read_bytes()
    return PreparedDocument(source, doc_id, digest("\n\n".join(body)), digest(raw), chunks)


def load_manifest(path: Path):
    manifest = Manifest.model_validate_json(path.read_text(encoding="utf-8-sig"))
    prepared, skipped, seen = [], [], set()
    for source in manifest.documents:
        if source.review_status != "APPROVED":
            skipped.append({"url": str(source.url), "status": source.review_status})
            continue
        doc = prepare(source, path.parent)
        if doc.id in seen:
            raise ValueError("같은 URL·버전이 목록에 중복되어 있습니다.")
        seen.add(doc.id)
        prepared.append(doc)
    return prepared, skipped
