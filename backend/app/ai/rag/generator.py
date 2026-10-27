import json
import time
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.ai.rag.prompts import GUIDE_PROMPT_VERSION, GUIDE_SYSTEM_INSTRUCTION, build_guide_prompt
from app.core.config import GEMINI_API_KEY, GEMINI_MODEL

TIMEOUT_MS = 15000  # Gemini API는 10초 미만을 허용하지 않음

# Gemini에게 이 모양의 JSON으로만 답하게 함
STEPS_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["instruction", "sources"],
            },
        },
    },
    "required": ["steps"],
}


@dataclass
class GuideLlmResult:
    steps: list[dict]  # [{"instruction": "...", "sources": [1]}, ...]
    model: str
    prompt_version: str
    latency_ms: int


def generate_rag_steps(chunks: list[dict]) -> GuideLlmResult:
    """검색한 문단을 근거로 대응 단계 생성. 실패하면 예외 → 부르는 쪽에서 고정 안내로."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았어요.")
    client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    started = time.perf_counter()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=build_guide_prompt(chunks),
        config=types.GenerateContentConfig(
            system_instruction=GUIDE_SYSTEM_INSTRUCTION,
            temperature=0.2,
            max_output_tokens=600,
            response_mime_type="application/json",
            response_schema=STEPS_SCHEMA,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    steps = json.loads(response.text or "{}").get("steps", [])
    return GuideLlmResult(steps=steps, model=GEMINI_MODEL,
                          prompt_version=GUIDE_PROMPT_VERSION, latency_ms=latency_ms)