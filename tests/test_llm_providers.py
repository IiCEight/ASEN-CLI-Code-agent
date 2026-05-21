import json

import httpx
import pytest

from asen_cli.config import AsenConfig
from asen_cli.llm.factory import create_llm_client, resolve_provider_base_url
from asen_cli.llm.ollama_client import OllamaClient
from asen_cli.llm.openai_client import OpenAICompatibleClient
from asen_cli.utils.errors import ConfigError


@pytest.mark.asyncio
async def test_openai_compatible_client_complete():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = request.read().decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"final":"ok"}'}}]},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        llm = OpenAICompatibleClient(
            AsenConfig(api_key="sk-test", base_url="https://example.test/v1"),
            client=client,
        )
        result = await llm.complete(
            [{"role": "user", "content": "hi"}],
            [{"name": "read_file", "parameters": {"type": "object"}}],
        )

    assert result == '{"final":"ok"}'
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-test"
    assert "Available tools" in captured["payload"]


@pytest.mark.asyncio
async def test_openai_compatible_client_stream_complete():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = request.read().decode()
        body = "\n".join(
            [
                "data: "
                + json.dumps({"choices": [{"delta": {"content": '{\"final\":\"he'}}]}),
                "data: "
                + json.dumps({"choices": [{"delta": {"content": 'llo\"}'}}]}),
                "data: [DONE]",
                "",
            ]
        )
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        llm = OpenAICompatibleClient(
            AsenConfig(api_key="sk-test", base_url="https://example.test/v1"),
            client=client,
        )
        chunks = [
            chunk
            async for chunk in llm.stream_complete([{"role": "user", "content": "hi"}], [])
        ]

    assert chunks == ['{"final":"he', 'llo"}']
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert '"stream":true' in captured["payload"].replace(" ", "")


@pytest.mark.asyncio
async def test_openai_compatible_client_requires_api_key():
    llm = OpenAICompatibleClient(AsenConfig(api_key=None))

    with pytest.raises(ConfigError):
        await llm.complete([{"role": "user", "content": "hi"}], [])


@pytest.mark.asyncio
async def test_ollama_client_complete():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = request.read().decode()
        return httpx.Response(200, json={"message": {"content": '{"final":"local"}'}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        llm = OllamaClient(
            AsenConfig(provider="ollama", model="llama3.1"),
            base_url="http://localhost:11434",
            client=client,
        )
        result = await llm.complete([{"role": "user", "content": "hi"}], [])

    assert result == '{"final":"local"}'
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert '"model":"llama3.1"' in captured["payload"].replace(" ", "")


@pytest.mark.asyncio
async def test_ollama_client_stream_complete():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = request.read().decode()
        body = "\n".join(
            [
                json.dumps({"message": {"content": '{\"final\":\"lo'}}),
                json.dumps({"message": {"content": 'cal\"}'}}),
                "",
            ]
        )
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        llm = OllamaClient(
            AsenConfig(provider="ollama", model="llama3.1"),
            base_url="http://localhost:11434",
            client=client,
        )
        chunks = [
            chunk
            async for chunk in llm.stream_complete([{"role": "user", "content": "hi"}], [])
        ]

    assert chunks == ['{"final":"lo', 'cal"}']
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert '"stream":true' in captured["payload"].replace(" ", "")


def test_factory_creates_ollama_client():
    client = create_llm_client(AsenConfig(provider="ollama", model="llama3.1"))

    assert isinstance(client, OllamaClient)


def test_factory_creates_openai_compatible_for_deepseek():
    client = create_llm_client(
        AsenConfig(provider="deepseek", api_key="sk-test", model="deepseek-chat")
    )

    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "https://api.deepseek.com"


def test_provider_base_url_override_wins():
    cfg = AsenConfig(provider="deepseek", base_url="https://proxy.example/v1")

    assert resolve_provider_base_url(cfg) == "https://proxy.example/v1"
