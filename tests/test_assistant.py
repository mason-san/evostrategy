"""Assistant tool layer and tool-use loop, with a scripted stand-in for the Anthropic client."""

from types import SimpleNamespace
import os

import pytest
from google.genai import types

from assistant import agent
from assistant.tools import TOOL_DEFINITIONS, DataAccess
from pipeline import run_demo  # noqa: F401  (demo loader used below)


def _response(parts):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=parts))],
        response_id="req_test",
        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=5),
    )


class ScriptedClient:
    def __init__(self, *responses):
        self.calls = []
        self.models = self
        self._responses = list(responses)

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    provider = os.environ.get("LLM_PROVIDER")
    key = os.environ.pop("GEMINI_API_KEY", None)
    os.environ["LLM_PROVIDER"] = "rules"
    run_demo()
    yield
    if provider is None:
        os.environ.pop("LLM_PROVIDER", None)
    else:
        os.environ["LLM_PROVIDER"] = provider
    if key is not None:
        os.environ["GEMINI_API_KEY"] = key


def test_tools_only_expose_verified_transactions():
    data = DataAccess()
    assert data.verified and all(t["verified"] for t in data.verified)
    overview = data.run("get_data_overview", {})
    assert overview["verified_records"] == len(data.verified)
    assert overview["total_records"] >= overview["verified_records"]


def test_every_declared_tool_runs_with_no_arguments_or_defaults():
    data = DataAccess()
    for tool in TOOL_DEFINITIONS:
        args = {k: v["enum"][0] for k, v in tool["input_schema"]["properties"].items() if "enum" in v and k in tool["input_schema"]["required"]}
        data.run(tool["name"], args)


def test_find_transactions_totals_cover_all_matches_and_track_evidence():
    data = DataAccess()
    result = data.run("find_transactions", {"kind": "expense", "limit": 3, "unknown_arg": 1})
    assert result["shown"] <= 3 and result["matched"] >= result["shown"]
    assert data.supporting_ids == [t["transaction_id"] for t in result["transactions"]]


def test_unknown_tool_is_rejected():
    with pytest.raises(ValueError):
        DataAccess().run("delete_everything", {})


def test_loop_runs_tools_returns_all_results_in_one_message_and_reports_evidence():
    first = _response([
        types.Part(function_call=types.FunctionCall(name="get_time_series", args={"granularity": "quarterly"})),
        types.Part(function_call=types.FunctionCall(name="get_data_overview", args={})),
    ])
    final = _response([types.Part(text="Revenue was **X**.")])
    client = ScriptedClient(first, final)
    out = agent.answer("What was our revenue last quarter?", [{"role": "user", "content": "hi"}],
                       model="gemini-2.5-pro", client=client)
    assert out["answer"] == "Revenue was **X**."
    assert [t["name"] for t in out["tools_used"]] == ["get_time_series", "get_data_overview"]
    assert out["visual"]["labels"] and out["evidence"]["verified_records"] > 0
    tool_turn = next(turn for turn in client.calls[1]["contents"] if any(part.function_response for part in turn.parts))
    assert tool_turn.role == "user" and [r.function_response.name for r in tool_turn.parts] == ["get_time_series", "get_data_overview"]
    assert out["usage"] == {"input_tokens": 20, "output_tokens": 10}


def test_tool_errors_are_reported_to_the_model_not_raised():
    bad = _response([types.Part(function_call=types.FunctionCall(name="nope", args={}))])
    client = ScriptedClient(bad, _response([types.Part(text="Sorry.")]))
    out = agent.answer("q", model="gemini-2.5-pro", client=client)
    response = next(part.function_response for turn in client.calls[1]["contents"] for part in turn.parts if part.function_response)
    assert "error" in response.response["result"]
    assert out["answer"] == "Sorry."


def test_unsupported_model_and_missing_key(monkeypatch):
    with pytest.raises(ValueError):
        agent.answer("q", model="gpt-4", client=ScriptedClient())
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(agent.AssistantUnavailable):
        agent.answer("q", model="gemini-2.5-pro")


def test_chat_history_persists_and_survives_registry_reset():
    from storage import chats, registry

    conversation = chats.create("What was our revenue last quarter? " * 5)
    assert len(conversation["title"]) <= chats.TITLE_LENGTH
    chats.add_message(conversation["id"], "user", "q1")
    chats.add_message(conversation["id"], "assistant", "a1", result={"answer": "a1", "evidence": {"verified_records": 3}})
    chats.add_message(conversation["id"], "user", "q2")
    chats.add_message(conversation["id"], "assistant", error="boom")

    registry.reset_registry()   # loading demo data / resetting must not touch chats

    loaded = chats.get(conversation["id"])
    assert [m["role"] for m in loaded["messages"]] == ["user", "assistant", "user", "assistant"]
    assert loaded["messages"][1]["result"]["evidence"]["verified_records"] == 3
    assert chats.history(conversation["id"]) == [
        {"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}, {"role": "user", "content": "q2"}]
    assert chats.list_all()[0]["message_count"] == 4
    assert chats.rename(conversation["id"], "Revenue") and chats.get(conversation["id"])["title"] == "Revenue"
    assert chats.delete(conversation["id"]) and chats.get(conversation["id"]) is None and not chats.delete("nope")


def test_chat_endpoint_saves_exchange_and_failures(monkeypatch):
    from fastapi.testclient import TestClient

    from evostrategy_backend.main import app

    run_demo()
    client = TestClient(app)
    monkeypatch.setattr(agent, "answer", lambda q, h, m: {"answer": f"echo {q} / history={len(h)}", "evidence": {}, "model": "x"})
    first = client.post("/api/assistant/chat", json={"question": "hello"}).json()
    second = client.post("/api/assistant/chat", json={"question": "again", "conversation_id": first["conversation_id"]}).json()
    assert second["conversation_id"] == first["conversation_id"] and second["answer"].endswith("history=2")

    def fail(*_):
        raise agent.AssistantUnavailable("no key")
    monkeypatch.setattr(agent, "answer", fail)
    response = client.post("/api/assistant/chat", json={"question": "x", "conversation_id": first["conversation_id"]})
    assert response.status_code == 503
    saved = client.get(f"/api/chats/{first['conversation_id']}").json()
    assert saved["messages"][-1]["error"] and len(saved["messages"]) == 6
    assert client.post("/api/assistant/chat", json={"question": "x", "conversation_id": "missing"}).status_code == 404
    assert client.delete(f"/api/chats/{first['conversation_id']}").status_code == 200


def test_whatif_desk_moves_levers_clamps_and_matches_simulate():
    from analytics.whatif import Scenario, simulate
    from assistant.tools import WhatIfDesk

    desk = WhatIfDesk(Scenario())
    assert "set_scenario" in {t["name"] for t in desk.tool_definitions} and "run_what_if" not in {t["name"] for t in desk.tool_definitions}
    out = desk.run("set_scenario", {"pricing_adjustment_pct": 50, "headcount_change": 3})
    assert desk.scenario.pricing_adjustment_pct == 20 and desk.scenario.headcount_change == 3
    assert out["capped"] == ["pricing_adjustment_pct 50 capped to 20"]
    expected = simulate(desk.verified, desk.scenario, budgets=desk.budgets, finance=desk.finance)
    assert out["totals"] == expected["totals"] and desk.simulation["totals"] == expected["totals"]

    desk.run("set_scenario", {"volume_change_pct": 10})          # partial update keeps earlier levers
    assert desk.scenario.pricing_adjustment_pct == 20 and desk.scenario.volume_change_pct == 10
    desk.run("set_scenario", {"reset": True, "horizon": 12})
    assert desk.scenario.pricing_adjustment_pct == 0 and desk.scenario.horizon == 12


def test_whatif_assistant_endpoint_returns_final_scenario(monkeypatch):
    from fastapi.testclient import TestClient

    from evostrategy_backend.main import app

    run_demo()
    seen = {}

    def fake_answer(question, history, model, session=None):
        seen["scenario"] = session.scenario.headcount_change
        session.run("set_scenario", {"headcount_change": 2})
        return agent._finish(session, "Hired 2.", "x", {}, None)

    monkeypatch.setattr(agent, "answer", fake_answer)
    body = {"question": "hire 2", "scenario": {"headcount_change": 1, "baseline_headcount": 20},
            "history": [{"role": "user", "content": "hi"}]}
    out = TestClient(app).post("/api/whatif/assistant", json=body).json()
    assert seen["scenario"] == 1 and out["scenario"]["headcount_change"] == 2 and out["scenario"]["baseline_headcount"] == 20
    assert out["simulation"]["totals"]["delta"]["profit"] != 0
