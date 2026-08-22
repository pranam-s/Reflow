"""Tests for reflow.llm.schema."""

from pydantic import BaseModel, ConfigDict

from reflow.llm.schema import json_schema_response_format


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    confidence: str


def test_json_schema_response_format_shape() -> None:
    response_format = json_schema_response_format(_Answer, name="answer")
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert json_schema["name"] == "answer"
    assert json_schema["strict"] is True
    assert "description" not in json_schema


def test_json_schema_response_format_includes_description() -> None:
    response_format = json_schema_response_format(_Answer, name="answer", description="an answer")
    assert response_format["json_schema"]["description"] == "an answer"


def test_json_schema_response_format_is_strict_compatible() -> None:
    response_format = json_schema_response_format(_Answer, name="answer")
    schema = response_format["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"text", "confidence"}
