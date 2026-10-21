import time
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.ai.explanation.prompts import PROMPT_VERSION, SYSTEM_INSTRUCTION, build_user_prompt
from app.core.config import GEMINI_API_KEY, GEMINI_MODEL

TIMEOUT_MS = 15000  # Gemini API는 10초 미만을 허용하지 않음. 보통 1초 안에 응답.


@dataclass
class LlmResult:
    text: str
    model: str
    prompt_version: str
    latency_ms: int


def generate_llm_explanation(alert_type: str, evidence: dict) -> LlmResult:
    """Gemini로 쉬운 설명 생성. 실패하면 예외를 던지고, 부르는 쪽에서 대체 문구로 전환."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았어요.")
    client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    started = time.perf_counter()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=build_user_prompt(alert_type, evidence),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.3,         # 낮을수록 매번 비슷하고 안정적인 문장
            max_output_tokens=200,   # 100자 설명에 충분한 길이
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("LLM 응답이 비어 있어요.")
    return LlmResult(text=text, model=GEMINI_MODEL, prompt_version=PROMPT_VERSION, latency_ms=latency_ms)