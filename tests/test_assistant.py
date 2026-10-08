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
    out = agent.answer("What was our revenue last quarter?", [{"role": "user", "content": "hi"}], client=client)
    assert out["answer"] == "Revenue was **X**."
    assert [t["name"] for t in out["tools_used"]] == ["get_time_series", "get_data_overview"]
    assert out["visual"]["labels"] and out["evidence"]["verified_records"] > 0
    tool_turn = client.calls[1]["messages"][-1]
    assert tool_turn["role"] == "user" and [r["tool_use_id"] for r in tool_turn["content"]] == ["t1", "t2"]
    assert out["usage"] == {"input_tokens": 20, "output_tokens": 10}


def test_tool_errors_are_reported_to_the_model_not_raised():
    bad = _response([_block("tool_use", id="t1", name="nope", input={})], "tool_use")
    client = ScriptedClient(bad, _response([_block("text", text="Sorry.")], "end_turn"))
    out = agent.answer("q", client=client)
    assert client.calls[1]["messages"][-1]["content"][0]["is_error"] is True
    assert out["answer"] == "Sorry."


def test_unsupported_model_and_missing_key(monkeypatch):
    with pytest.raises(ValueError):
        agent.answer("q", model="gpt-4", client=ScriptedClient())
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(agent.AssistantUnavailable):
        agent.answer("q")
