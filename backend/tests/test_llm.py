"""OpenAI integration paths, exercised with a scripted fake client (no network)."""

import json
from types import SimpleNamespace

import pytest

from app.ai import llm
from app.core.config import get_settings


def _msg(content: str | None = None, tool_calls: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def _tool_call(name: str, args: dict, id_: str = "call_1") -> SimpleNamespace:
    return SimpleNamespace(id=id_, type="function", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeOpenAI:
    """Records requests; returns scripted responses (or raises scripted exceptions)."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.requests.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_openai(monkeypatch):  # type: ignore[no-untyped-def]
    settings = get_settings()
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_model", "test-model")

    def install(script: list) -> FakeOpenAI:
        fake = FakeOpenAI(script)
        monkeypatch.setattr(llm, "_client", fake)
        return fake

    yield install
    monkeypatch.setattr(llm, "_client", None)


async def test_analysis_narrative_uses_llm_with_grounded_facts(auth_client, fake_openai) -> None:  # type: ignore[no-untyped-def]
    fake = fake_openai([_msg("BTC is trending up (estimate).")])
    resp = await auth_client.post("/api/v1/analysis", json={"symbol": "BTC-USD", "timeframe": "1h"})
    assert resp.status_code == 201, resp.text
    a = resp.json()
    assert a["narrative"] == "BTC is trending up (estimate)."
    assert a["narrative_source"] == "openai:test-model"
    req = fake.requests[0]
    assert "max_completion_tokens" in req and "max_tokens" not in req
    system, user = req["messages"][0]["content"], req["messages"][1]["content"]
    assert "Never invent" in system
    facts = json.loads(user.split("\n", 1)[1])
    # The LLM receives the computed numbers; it does not produce them.
    assert facts["signal"]["action"] == a["signal"]["action"]
    assert facts["indicators"]["close"] == pytest.approx(a["indicators"]["latest"]["close"])


async def test_retries_without_temperature_for_models_that_reject_it(auth_client, fake_openai) -> None:  # type: ignore[no-untyped-def]
    fake = fake_openai([Exception("Unsupported value: 'temperature' does not support 0.2"), _msg("ok")])
    resp = await auth_client.post("/api/v1/analysis", json={"symbol": "ETH-USD", "timeframe": "1h"})
    assert resp.json()["narrative"] == "ok"
    assert "temperature" in fake.requests[0] and "temperature" not in fake.requests[1]


async def test_llm_failure_falls_back_to_rule_based(auth_client, fake_openai) -> None:  # type: ignore[no-untyped-def]
    fake_openai([Exception("rate limited")])
    resp = await auth_client.post("/api/v1/analysis", json={"symbol": "SOL-USD", "timeframe": "1h"})
    a = resp.json()
    assert a["narrative_source"] == "rule_based"
    assert "rule-based summary" in a["narrative"]


async def test_assistant_tool_loop_feeds_real_data_to_model(auth_client, fake_openai) -> None:  # type: ignore[no-untyped-def]
    fake = fake_openai(
        [
            _msg(tool_calls=[_tool_call("get_asset_analysis", {"symbol": "BTC", "timeframe": "1h"})]),
            _msg("BTC-USD summary grounded in tool data."),
        ]
    )
    resp = await auth_client.post("/api/v1/assistant/chat", json={"message": "Explain the BTC trend"})
    assert resp.status_code == 200, resp.text
    m = resp.json()["message"]
    assert m["content"] == "BTC-USD summary grounded in tool data."
    assert m["meta"]["engine"] == "openai:test-model"
    assert m["meta"]["tools"] == ["get_asset_analysis"]
    # Second request must carry the tool result computed from platform data.
    tool_msgs = [x for x in fake.requests[1]["messages"] if x["role"] == "tool"]
    payload = json.loads(tool_msgs[0]["content"])
    assert payload["symbol"] == "BTC-USD"
    assert payload["signal"]["action"] in {"buy", "sell", "hold"}
    assert fake.requests[0]["tools"]  # tool specs were offered


async def test_assistant_unknown_tool_and_bad_args_are_contained(auth_client, fake_openai) -> None:  # type: ignore[no-untyped-def]
    fake = fake_openai(
        [
            _msg(tool_calls=[_tool_call("drop_database", {}), _tool_call("get_latest_signal", {"wrong": 1}, "call_2")]),
            _msg("Done."),
        ]
    )
    resp = await auth_client.post("/api/v1/assistant/chat", json={"message": "anything"})
    assert resp.status_code == 200
    tool_msgs = [json.loads(x["content"]) for x in fake.requests[1]["messages"] if x["role"] == "tool"]
    assert "Unknown tool" in tool_msgs[0]["error"]
    assert "Bad arguments" in tool_msgs[1]["error"]


async def test_assistant_llm_outage_falls_back(auth_client, fake_openai) -> None:  # type: ignore[no-untyped-def]
    fake_openai([Exception("connection reset")])
    resp = await auth_client.post("/api/v1/assistant/chat", json={"message": "What is happening in the market?"})
    m = resp.json()["message"]
    assert m["meta"]["engine"] == "rule_based"
    assert "Market overview" in m["content"]
