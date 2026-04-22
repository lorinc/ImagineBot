"""Integration test — calls real Gemini API. Requires GCP credentials (ADC)."""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/gateway"))

import vertexai
from config import GCP_PROJECT, REGION

vertexai.init(project=GCP_PROJECT, location=REGION)

from services.scope_gate import is_in_scope


def test_school_policy_question_is_in_scope():
    assert asyncio.run(is_in_scope("What is the fire evacuation procedure?")) is True


def test_staff_absence_is_in_scope():
    assert asyncio.run(is_in_scope("What should a teacher do if they are sick?")) is True


def test_cooking_question_is_out_of_scope():
    assert asyncio.run(is_in_scope("How do I bake a chocolate cake?")) is False


def test_stock_market_is_out_of_scope():
    assert asyncio.run(is_in_scope("What is the current price of Tesla stock?")) is False
