from types import SimpleNamespace

import pytest

from backend.app import services


@pytest.mark.asyncio
async def test_generate_stream_parses_gemini_sse(monkeypatch):
    settings = SimpleNamespace(
        trading_providers="gemini",
        trading_gemini_api_key="test-key",
        trading_gemini_model="test-model",
        gemini_models="",
        llm_max_model_attempts=1,
    )
    monkeypatch.setattr(services, "get_settings", lambda: settings)

    class Response:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield 'data: {"candidates":[{"content":{"parts":[{"text":"Hello from Gemini."}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":1}}'
            yield "data: [DONE]"

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        def stream(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(services.httpx, "AsyncClient", Client)
    tokens = []

    async def on_token(token):
        tokens.append(token)

    answer, metadata = await services.generate_stream("trading", "nova", "Hi", [], on_token)

    assert answer == "Hello from Gemini."
    assert tokens == ["Hello from Gemini."]
    assert metadata["provider"] == "gemini"
    assert metadata["usage"]["promptTokenCount"] == 1
