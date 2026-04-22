"""Integration test — calls real Gemini API. Requires GCP credentials (ADC)."""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/gateway"))

import vertexai
from config import GCP_PROJECT, REGION

vertexai.init(project=GCP_PROJECT, location=REGION)

from services.scope_gate import classify

_CORPUS = "School handbook covering daily logistics, health, behaviour, curriculum, technology, fees."


def test_school_policy_question_is_in_scope_and_specific():
    in_scope, specific_enough = asyncio.run(classify("What is the fire evacuation procedure?", _CORPUS))
    assert in_scope is True
    assert specific_enough is True


def test_staff_absence_is_in_scope_and_specific():
    in_scope, specific_enough = asyncio.run(classify("What should a teacher do if they are sick?", _CORPUS))
    assert in_scope is True
    assert specific_enough is True


def test_cooking_question_is_out_of_scope():
    in_scope, _specific = asyncio.run(classify("How do I bake a chocolate cake?", _CORPUS))
    assert in_scope is False


def test_stock_market_is_out_of_scope():
    in_scope, _specific = asyncio.run(classify("What is the current price of Tesla stock?", _CORPUS))
    assert in_scope is False


def test_vague_question_is_not_specific_enough():
    in_scope, specific_enough = asyncio.run(classify("What are the rules?", _CORPUS))
    assert in_scope is True
    assert specific_enough is False


def test_topic_anchor_is_specific_enough():
    in_scope, specific_enough = asyncio.run(classify("What about balls?", _CORPUS))
    assert in_scope is True
    assert specific_enough is True
