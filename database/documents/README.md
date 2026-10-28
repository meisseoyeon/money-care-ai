# 문서 적재 MVP

검수한 공식 HTML **본문 발췌 3개**를 청크 5개로 만들어 기존 `documents`와
`doc_chunks`에 저장하는 수동 실행 도구입니다. 새 테이블/마이그레이션은 없습니다.
로그인·송금·생활비·API 시작 코드는 변경하지 않습니다.

자동 크롤러, PDF 추출/OCR, Airflow, 업로드 화면, 운영 RAG 검색/답변 생성은 포함하지 않습니다.
고정 질문으로 DB 검색을 확인하는 개발용 평가 명령만 제공합니다.
PDF가 필요하면 사람이 본문을 추출·검수한 뒤 아래 JSON 형식으로 준비합니다.

## 포함한 자료

| 파일 | 원문과 선정 범위 |
|---|---|
| texts/privacy-response.json | [2026-10-06 합동 보도자료](https://m.korea.kr/briefing/pressReleaseView.do?newsId=156784413&pWise=mSub&pWiseSub=C1): 개인정보 노출·피해 신고·지급정지 관련 본문 |
| texts/messenger-prevention.json | [2022-05-13 메신저피싱 주의](https://www.korea.kr/news/policyNewsView.do?newsId=148901587): 가족·지인 확인 예방수칙만 발췌 |
| texts/simple-transfer.json | [2024-08-19 간편송금 피해 대응](https://www.korea.kr/news/policyNewsView.do?newsId=148932788): 금융회사·선불업자 정보공유 설명만 발췌 |

2026-10-22 각 게시글의 **텍스트 공공누리 제1유형** 표시를 확인했습니다.
사진·카드 이미지·첨부·백과사전 전체를 수집/허용한 것이 아닙니다.
그 밖의 자료는 이용 조건과 내용을 확인한 뒤 별도 추가해야 합니다.
날짜만 알려진 발행일은 한국 시각 00:00으로 저장합니다(정확한 발행 시간이라는 뜻이 아님).

오래된 자료에서 당시 통계·기관장·신고번호·법정기한은 제외했습니다.
대응 절차에는 최신 자료를 우선 사용하고, 환급 보장이나 피해 확정으로 해석하지 않습니다.
원문의 문장을 발췌한 것이며 LLM이 요약/재작성한 본문이 아닙니다.

## 실행

프로젝트 루트의 활성화된 가상환경에서:

```powershell
Push-Location backend
python -m app.documents ../database/documents/manifest.json
Pop-Location
```

기본 명령은 **DB 연결·임베딩 API 호출 없이** 검증된 문서·청크를 출력합니다.
보류/제외 자료는 본문 파일도 열지 않습니다.

실제 적재는 `backend/.env`의 기존 `DATABASE_URL`, `GEMINI_API_KEY` 설정 후 실행합니다.
API 키는 Git이나 manifest에 저장하지 마세요.

```powershell
Push-Location backend
python -m app.documents ../database/documents/manifest.json --apply
Pop-Location
```

문서별 성공/중복/실패를 출력합니다. 실패가 있으면 종료 코드는 1입니다.
성공 문서의 임베딩 캐시와 실패 보고서는 `.cache/`에 남고 Git에서는 제외됩니다.
같은 명령으로 재시도하면 성공한 벡터를 재사용합니다. 실제 DB에는 가짜 벡터를 넣지 않습니다.
현재 개발 환경에 키가 없으면 실제 임베딩과 적재는 수행할 수 없습니다.

## 입력 규칙

`manifest.json`에 문서별 제목·기관·게시 기관·원문/첨부 URL·버전·수집일·발행일·이용 조건·
확인 URL/시각·검토 메모·본문 파일을 기록합니다.

- `review_status`: APPROVED / HOLD / EXCLUDED.
- APPROVED는 본문·이용 조건·증빙 URL/시각·검토 메모가 모두 필요합니다.
- `license`: KOGL-1 / PERMISSION / UNKNOWN. UNKNOWN은 승인할 수 없습니다.
- PERMISSION은 실제로 확보한 허락의 범위/근거를 메모해야 합니다.
- 첨부를 사용하면 `file_url`과 별도 `attachment_license`가 필요합니다.
- 승인 여부는 사람이 원문과 이용 범위를 검토한 기록입니다. 프로그램이 허락을 대신 판정하지 않습니다.
- 파일 경로는 manifest 폴더 내부로 제한합니다.

본문은 아래와 같이 사람이 정리한 섹션 배열입니다.

```json
[
  {
    "heading": "소제목",
    "location": "HTML 본문: 소제목 또는 PDF 5쪽",
    "tags": ["VOICE_PHISHING", "AFTER_TRANSFER"],
    "paragraphs": ["조건과 행동을 함께 보존한 원문 문단"]
  }
]
```

문단은 약 900자까지 묶고 제목/위치를 포함해 최대 1500자입니다.
섹션을 섞거나 긴 문단을 임의로 자르지 않으며 너무 긴 문단은 검수를 요청합니다.
작은 절차 청크는 그대로 보존합니다. 겹침 분할은 이번 MVP에서 사용하지 않습니다.

태그: VOICE_PHISHING, PREVENTION, AFTER_TRANSFER, PERSONAL_DATA_EXPOSED,
PAYMENT_SUSPENSION, MESSENGER_PHISHING, SIMPLE_TRANSFER, EASY_TERM,
TRANSFER_SCAM, UNKNOWN_RECIPIENT, BEFORE_TRANSFER.
예방 행동 안내는 기존 `doc_type=RESPONSE`에 PREVENTION 태그로 구분합니다.

이번 자료는 검수 후 송금 전 행동에 BEFORE_TRANSFER를 추가했습니다.
UNKNOWN_RECIPIENT는 가족·지인 신원/타인 계좌 확인 청크에만 붙였습니다.
새 상대라는 사실만으로 사기를 판단하지 않습니다. 두 단계 태그를 같은 섹션에 함께 붙이지 않습니다.
태그를 변경한 발췌 자료는 excerpt-v2로 적재하며 옛 인용/청크를 수정하지 않습니다.

`content_hash`는 제목/원문 위치 접두사를 제외한 정리 본문의 SHA-256입니다.
`raw_hash`는 `raw_file`이 있으면 그 파일, 없으면 검수 본문 JSON 파일 바이트의 SHA-256입니다.
**이번에 포함한 자료는 전체 HTML/PDF 파일 해시가 아니라 발췌 입력 파일 해시**입니다.
원본 HTML/PDF를 별도 보관하려면 해당 이용 범위 확인 후 `raw_file`을 지정하세요.
추가 검토 메타데이터와 raw_hash는 기존 `documents.license` TEXT에 JSON 문자열로 저장합니다.

## 와우님 전달 계약

| 설정 | 값 |
|---|---|
| 모델 | gemini-embedding-001 |
| 차원 | 1024 |
| 문서 task_type | RETRIEVAL_DOCUMENT |
| 질문 task_type | RETRIEVAL_QUERY |
| 정규화 | L2 |
| 청크 버전 | section-v1 |
| 임베딩 버전 | retrieval-1024-l2-v1 |

모델은 [Google 공식 임베딩 문서](https://ai.google.dev/gemini-api/docs/embeddings)를 참고합니다.
문서 하나당 벡터 하나가 아니라 **청크 하나당 벡터 하나**를 생성합니다.
1024차원/유한값/영벡터 검증 후 정규화하고 READY로 저장합니다.
실제 API 출력과 한국어 검색 품질은 키 설정 후 별도로 확인해야 합니다.
다른 모델/버전의 질문 벡터를 비교하면 안 됩니다.

와우님 검색 조건: documents.status=ACTIVE, doc_chunks.embedding_status=READY,
위 모델·청크·임베딩 버전. 검색 결과의 document_id, chunk_id와 documents의 제목·기관·URL·버전을
인용에 사용합니다. 원문 위치는 청크 본문 앞의 `[위치: ...]`에 보존했습니다.

## 중복/실패 동작

- 같은 URL·버전·내용/메타데이터/청크이면 UNCHANGED이며 API를 다시 호출하지 않습니다.
- 같은 버전의 내용/메타데이터가 바뀌면 실패합니다. 새 문서 버전을 지정하세요.
- 같은 본문의 다른 활성 URL은 DUPLICATE:문서ID로 보고하고 새 행을 만들지 않습니다.
- 문서별 벡터 준비는 DB 트랜잭션 밖에서 합니다.
- 문서·청크 전체 저장과 같은 URL의 이전 버전 RETIRED 처리는 하나의 트랜잭션입니다.
- 실패하면 기존 정상 문서/청크는 유지됩니다. 이전 인용을 위해 옛 청크를 삭제하지 않습니다.
- 동일 URL과 동일 본문의 동시 적재는 PostgreSQL advisory lock으로 직렬화합니다.
- 로컬 캐시에는 벡터와 해시만 저장하며 API 키는 저장하지 않습니다.

청크별 최근 임베딩 처리 결과는 `.cache/attempts/{chunk_id}.json`에 저장합니다.
document_id, chunk_id, content_hash, status(READY/FAILED), attempted_at, 실패 시 error_type을
기록합니다. 원본 API 오류 메시지와 키는 저장하지 않습니다. READY는 임베딩 준비 상태이며,
DB 저장 성공 여부는 last-run.json의 문서 상태에서 확인합니다.
재실행은 성공 캐시를 재사용하고 실패/미처리 청크만 API를 호출합니다.

## 질문 10개 검색 검증

`evaluation.json`은 Git에 저장하는 고정 정답 데이터입니다. 실행 결과나 임베딩 캐시가 아닙니다.
검색 결과를 보기 전에 자료를 읽고 정답 청크 ID를 지정했습니다.
송금 전 3개 / 송금 후 3개 / 개인정보 노출 2개 / 자료 밖 질문 2개입니다.
자료 버전으로 청크 ID가 바뀌면 정답도 자료를 읽고 갱신해야 합니다.

```powershell
Push-Location backend
python -m app.documents.evaluate ../database/documents/evaluation.json
Pop-Location
```

실제 Gemini 질문 임베딩과 PostgreSQL 코사인 거리 검색을 실행합니다.
질문 벡터는 `.cache/queries/`에 저장하며 같은 질문 재실행에 재사용합니다.
질문에는 RETRIEVAL_QUERY를 사용하며 모델·차원·정규화·검증은 문서용 함수를 재사용합니다.
정답 정보는 검색 입력/점수에 사용하지 않습니다.
검색 결과는 청크/문서 ID, 본문, 태그, 코사인 거리(작을수록 가까움),
제목·기관·URL·버전·수집일·발행일·원문 위치·모델/벡터 설정을 포함합니다.

필터 규칙:

- ACTIVE 문서 + READY 청크 + 공통 청크/임베딩 프로필만 검색합니다.
- stage가 있으면 해당 단계 태그를 반드시 포함하고 반대 단계는 제외합니다.
- situation_tags는 모두 일치하는 조건(AND)입니다. 단계 태그는 stage에만 지정합니다.
- 결과 부족 시 단계 필터를 풀어 다른 단계 자료를 대신 반환하지 않습니다.
- 수집일은 자료를 가져온 시각이며 최신성 보장이나 발행일을 뜻하지 않습니다.

상세 보고서는 `.cache/evaluation-report.json`에 저장됩니다.
양성 질문은 상위 3개 내 정답 포함(hit_at_3) 여부를 기록하고, 8개 중 7개 이상을 초기 목표로 봅니다.
질문별 FAIL이 있으면 명령 종료 코드 1로 알려 검토하게 합니다.
자료 밖 2개 질문은 **거리 임계값이 없으면 REVIEW_REQUIRED**이며 자동 통과시키지 않습니다.
가까운 벡터가 있다는 것만으로 답변 가능한 근거라고 판단할 수 없기 때문입니다.
운영용 근거 부족 정책/임계값은 와우 담당입니다. 합의한 값은 --max-distance로 검증할 수 있습니다.
10개 정답에 맞추려고 임계값이나 정답을 바꾸지 않습니다.
이번 5청크·10질문 결과는 연결 확인이며 검색 품질 보장이나 50개 평가 완료를 뜻하지 않습니다.

와우님 전달 계약은 이 README의 모델/태그/필터/결과 형식입니다.
운영 검색·점수/근거 부족 정책·대응 안내·화면은 변경하지 않았습니다.

## 테스트

```powershell
Push-Location backend
python -m unittest tests.test_document_ingestion.DocumentPreparationTests -v
# DEMO_TEST_DATABASE_URL을 별도 테스트 DB로 지정하면 저장 테스트도 실행됩니다.
python -m unittest tests.test_document_ingestion -v
Pop-Location
```

저장 테스트는 별도 PostgreSQL 스키마와 합성 자료/테스트 벡터만 사용합니다.
실제 Gemini 호출·검색 품질 검증과 구분됩니다.
