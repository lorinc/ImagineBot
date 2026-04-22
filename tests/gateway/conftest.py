"""Reset scope_gate model singleton before each test.

gRPC aio channels bind to the event loop they are created on.
asyncio.run() closes the loop after each call, so the cached GenerativeModel
becomes unusable after the first test. Resetting _model forces a fresh client
per asyncio.run() call.
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src/gateway"))


@pytest.fixture(autouse=True)
def reset_scope_gate_model():
    import services.scope_gate as sg
    sg._model = None
    yield
    sg._model = None
