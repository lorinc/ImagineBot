"""Integration test — calls real Gemini API. Requires GCP credentials (ADC)."""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/gateway"))

import vertexai
from config import GCP_PROJECT, REGION

vertexai.init(project=GCP_PROJECT, location=REGION)

from services.scope_gate import classify, ClassifyResult

_CORPUS = "School handbook covering daily logistics, health, behaviour, curriculum, technology, fees."


def test_school_policy_question_is_answerable():
    result = asyncio.run(classify("What is the fire evacuation procedure?", _CORPUS))
    assert result.in_scope is True
    assert result.query_type == "answerable"


def test_staff_absence_is_answerable():
    result = asyncio.run(classify("What should a teacher do if they are sick?", _CORPUS))
    assert result.in_scope is True
    assert result.query_type == "answerable"


def test_cooking_question_is_out_of_scope():
    result = asyncio.run(classify("How do I bake a chocolate cake?", _CORPUS))
    assert result.in_scope is False


def test_stock_market_is_out_of_scope():
    result = asyncio.run(classify("What is the current price of Tesla stock?", _CORPUS))
    assert result.in_scope is False


def test_vague_question_is_underspecified():
    result = asyncio.run(classify("What are the rules?", _CORPUS))
    assert result.in_scope is True
    assert result.query_type == "underspecified"
    assert result.missing_variable is not None and len(result.missing_variable) > 0


def test_topic_anchor_is_answerable():
    result = asyncio.run(classify("Are balls allowed on the playground?", _CORPUS))
    assert result.in_scope is True
    assert result.query_type == "answerable"


def test_overspecified_query():
    result = asyncio.run(
        classify(
            "What is the sick leave policy for primary teachers hired before 2020 on probation?",
            _CORPUS,
        )
    )
    assert result.in_scope is True
    assert result.query_type == "overspecified"


def test_multiple_questions_extracted():
    result = asyncio.run(
        classify("My son lost his hoodie. Who should I contact?", _CORPUS)
    )
    assert result.in_scope is True
    assert result.query_type == "multiple"
    assert len(result.sub_questions) >= 2


def test_uniform_policy_is_answerable():
    result = asyncio.run(classify("What is the uniform policy?", _CORPUS))
    assert result.in_scope is True
    assert result.query_type == "answerable"
