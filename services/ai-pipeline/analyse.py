from __future__ import annotations

import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Protocol


VALID_SENTIMENTS = {"positive", "neutral", "negative"}


@dataclass(frozen=True)
class InsightPayload:
    summary: str
    action_items: list[str]
    sentiment: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "action_items": self.action_items,
            "sentiment": self.sentiment,
        }


class Analyzer(Protocol):
    async def analyze(self, transcript: str) -> InsightPayload:
        ...


def validate_insight(payload: dict[str, Any]) -> InsightPayload:
    summary = str(payload.get("summary", "")).strip()
    action_items = payload.get("action_items", [])
    sentiment = str(payload.get("sentiment", "neutral")).strip().lower()

    if not isinstance(action_items, list):
        action_items = []
    action_items = [str(item).strip() for item in action_items if str(item).strip()]
    if sentiment not in VALID_SENTIMENTS:
        sentiment = "neutral"
    if not summary:
        summary = "No clear summary is available yet."

    return InsightPayload(summary=summary, action_items=action_items, sentiment=sentiment)


class MockAnalyzer:
    async def analyze(self, transcript: str) -> InsightPayload:
        cleaned = " ".join(transcript.split())
        if not cleaned:
            return InsightPayload(
                summary="Waiting for speech to produce a useful summary.",
                action_items=[],
                sentiment="neutral",
            )
        summary = cleaned[:220]
        if len(cleaned) > 220:
            summary += "..."
        action_items = []
        lowered = cleaned.lower()
        if "follow up" in lowered or "todo" in lowered or "action" in lowered:
            action_items.append("Review the mentioned follow-up after the call.")
        return InsightPayload(summary=summary, action_items=action_items, sentiment="neutral")


class AnthropicAnalyzer:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model or getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    async def analyze(self, transcript: str) -> InsightPayload:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=(
                "Return only valid JSON with exactly three keys: summary (string), action_items (array of strings), and sentiment (string). \n"
                "The sentiment value MUST be exactly one word: positive, neutral, or negative. \n"
                "The action_items value MUST be a list of strings, or an empty list [] if there are none. Do not return a string for action_items."
            ),
            messages=[{"role": "user", "content": f"Meeting transcript window:\n{transcript}"}],
        )
        raw = response.content[0].text
        return validate_insight(json.loads(raw))


class OpenAIAnalyzer:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model or getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def analyze(self, transcript: str) -> InsightPayload:
        response = await self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON with exactly three keys: summary (string), action_items (array of strings), and sentiment (string). \n"
                        "The sentiment value MUST be exactly one word: positive, neutral, or negative. \n"
                        "The action_items value MUST be a list of strings, or an empty list [] if there are none. Do not return a string for action_items."
                    ),
                },
                {"role": "user", "content": f"Meeting transcript window:\n{transcript}"},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        return validate_insight(json.loads(raw))


class OpenRouterAnalyzer:
    def __init__(self, api_key: str, model: str | None = None) -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            max_retries=0,
        )
        self._model = model or getenv("OPENROUTER_MODEL", "deepseek/deepseek-v4-flash:free")

    async def analyze(self, transcript: str) -> InsightPayload:
        import logging
        logger = logging.getLogger("resonance.ai-pipeline.analyzer")
        
        response = await self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            extra_body={"reasoning": {"enabled": True}},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return only valid JSON with exactly three keys: summary (string), action_items (array of strings), and sentiment (string). \n"
                        "The sentiment value MUST be exactly one word: positive, neutral, or negative. \n"
                        "The action_items value MUST be a list of strings, or an empty list [] if there are none. Do not return a string for action_items."
                    ),
                },
                {"role": "user", "content": f"Meeting transcript window:\n{transcript}"},
            ],
        )
        msg_dict = response.choices[0].message.model_dump()
        raw = msg_dict.get("content") or "{}"
        reasoning = msg_dict.get("reasoning") or msg_dict.get("reasoning_content") or msg_dict.get("reasoning_details")
        
        logger.info(f"OpenRouter Raw Reasoning: {reasoning}")
        logger.info(f"OpenRouter Raw Content: {raw}")
        
        # DeepSeek V4 flash sometimes dumps the final output entirely into the reasoning block
        if raw.strip() in ("", "{}", "None") and reasoning:
            raw = str(reasoning)

        # DeepSeek sometimes outputs json in markdown blocks even with json_object
        raw = raw.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
        
        try:
            parsed = json.loads(raw)
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON: {e} | Raw string: {raw}")
            parsed = {}
        return validate_insight(parsed)


def create_analyzer(provider: str | None = None) -> Analyzer:
    selected = (provider or getenv("LLM_PROVIDER", "mock")).lower()
    if selected == "anthropic":
        api_key = getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic.")
        return AnthropicAnalyzer(api_key)
    if selected == "openai":
        api_key = getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai.")
        return OpenAIAnalyzer(api_key)
    if selected == "openrouter":
        api_key = getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter.")
        return OpenRouterAnalyzer(api_key)
    return MockAnalyzer()
