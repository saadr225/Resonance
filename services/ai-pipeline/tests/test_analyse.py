from __future__ import annotations

import pytest

from analyse import MockAnalyzer, validate_insight


def test_validate_insight_normalizes_bad_values() -> None:
    insight = validate_insight({"summary": "", "action_items": "bad", "sentiment": "confused"})

    assert insight.summary == "No clear summary is available yet."
    assert insight.action_items == []
    assert insight.sentiment == "neutral"


@pytest.mark.asyncio
async def test_mock_analyzer_is_deterministic() -> None:
    insight = await MockAnalyzer().analyze("Speaker 1: We need a follow up action tomorrow.")

    assert "Speaker 1" in insight.summary
    assert insight.action_items == ["Review the mentioned follow-up after the call."]
    assert insight.sentiment == "neutral"
