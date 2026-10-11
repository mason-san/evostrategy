"""Assistant tool layer and tool-use loop, with a scripted stand-in for the Anthropic client."""

from types import SimpleNamespace

import pytest

from assistant import agent
from assistant.tools import TOOL_DEFINITIONS, DataAccess
from pipeline import run_demo  # noqa: F401  (demo loader used below)


def _block(type_, **kw):
    return SimpleNamespace(type=type_, **kw)


def _response(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason, _request_id="req_test",
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


class ScriptedClient:
    def __init__(self, *responses):
        self.calls = []
        self.messages = self
        self._responses = list(responses)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    run_demo()


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
    first = _response([_block("tool_use", id="t1", name="get_time_series", input={"granularity": "quarterly"}),
                       _block("tool_use", id="t2", name="get_data_overview", input={})], "tool_use")
    final = _response([_block("text", text="Revenue was **X**.")], "end_turn")
    client = ScriptedClient(first, final)
    out = agent.answer("What was our revenue last quarter?", [{"role": "user", "content": "hi"}], model="claude-opus-5-5", client=client)
    assert out["answer"] == "Revenue was **X**."
    assert [t["name"] for t in out["tools_used"]] == ["get_time_series", "get_data_overview"]
    assert out["visual"]["labels"] and out["evidence"]["verified_records"] > 0
    tool_turn = client.calls[1]["messages"][-1]
    assert tool_turn["role"] == "user" and [r["tool_use_id"] for r in tool_turn["content"]] == ["t1", "t2"]
    assert out["usage"] == {"input_tokens": 20, "output_tokens": 10}


def test_tool_errors_are_reported_to_the_model_not_raised():
    bad = _response([_block("tool_use", id="t1", name="nope", input={})], "tool_use")
    client = ScriptedClient(bad, _response([_block("text", text="Sorry.")], "end_turn"))
    out = agent.answer("q", model="claude-opus-5-5", client=client)
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True
    assert out["answer"] == "Sorry."


def test_unsupported_model_and_missing_key(monkeypatch):
    with pytest.raises(ValueError):
        agent.answer("q", model="gpt-4", client=ScriptedClient())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(agent.AssistantUnavailable):
        agent.answer("q", model="claude-opus-5-5")


def test_ollama_loop_uses_same_tools_and_reports_evidence():
    replies = [
        {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "get_time_series", "arguments": {"granularity": "quarterly"}}}]},
         "prompt_eval_count": 100, "eval_count": 10},
        {"message": {"role": "assistant", "content": "Revenue was **X**."}, "prompt_eval_count": 120, "eval_count": 8},
    ]
    sent = []

    def fake_post(url, json, timeout):
        sent.append(json)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: replies.pop(0))

    out = agent._answer_ollama("revenue last quarter?", [], "qwen3.5:9b", http=fake_post)
    assert out["answer"] == "Revenue was **X**." and out["model"] == "ollama:qwen3.5:9b"
    assert out["visual"]["labels"] and out["evidence"]["verified_records"] > 0
    tool_msg = sent[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_name"] == "get_time_series"
    assert sent[0]["tools"][0]["type"] == "function" and sent[0]["think"] is False
    assert out["usage"] == {"input_tokens": 220, "output_tokens": 18}


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
