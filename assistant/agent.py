"""Question answering over verified EvoStrategy data with Claude tool use.

The model never sees raw documents or the database. It gets the read-only tools
in ``assistant.tools`` and must ground every number in a tool result, so an
answer can only be as wrong as the verified data it was computed from.
"""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
from dotenv import load_dotenv

from utils.config import PROJECT_ROOT

from .tools import TOOL_DEFINITIONS, DataAccess

load_dotenv(PROJECT_ROOT / ".env")

MODELS: list[dict[str, str]] = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "Most capable"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "Balanced"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "note": "Fastest, cheapest"},
]
DEFAULT_MODEL = os.environ.get("ASSISTANT_MODEL", MODELS[0]["id"])
MAX_STEPS = 8
MAX_TOOL_CHARS = 40_000
MAX_HISTORY_TURNS = 12

SYSTEM_PROMPT = """You are EvoAssistant, the question-answering layer of EvoStrategy, a system that ingests a company's \
documents (invoices, payments, ledgers), reconciles them against each other, has a human review the discrepancies, and \
only then releases the numbers to analytics.

Your tools read that verified data and nothing else. Follow these rules:

1. Ground every figure in a tool result from this conversation. Never estimate, recall or invent numbers. If the tools \
cannot answer, say what is missing and, if useful, what the user could do (upload documents, review open cases, enter a \
cash balance in Settings).
2. Call get_data_overview first when you need to know what period or categories exist. "Last quarter" or "latest" means the \
latest COMPLETE period in the data, not the calendar today; say which period you used. Do not present a partial quarter as complete.
3. Records that are pending review or quarantined are excluded from every verified number. If that could change the answer \
(open cases, excluded records), mention it briefly.
4. Report amounts as stored; do not assume or convert currency. When the data source is demo/synthetic, say so once if the \
user could mistake it for real results.
5. For forecasts give the range and the holdout error, not only the point value. For what-if results state the assumptions \
you used (including any default you chose, such as price elasticity).
6. You answer questions; you cannot change data, accept or reject cases, or edit settings.

Style: lead with the answer in one or two sentences, then at most a short paragraph or a few bullets of the drivers. \
Use **bold** for key figures. Plain text only: no headings, tables or emoji. Be direct; no preamble."""


class AssistantUnavailable(RuntimeError):
    """Raised when the Anthropic API cannot be used (no key configured)."""


def status() -> dict[str, Any]:
    return {
        "configured": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "models": MODELS,
        "default_model": DEFAULT_MODEL,
        "setup_hint": "Add ANTHROPIC_API_KEY=... to a .env file in the project root and restart the backend.",
    }


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AssistantUnavailable(status()["setup_hint"])
    return anthropic.Anthropic()


def _result_text(value: Any) -> str:
    text = json.dumps(value, default=str)
    if len(text) <= MAX_TOOL_CHARS:
        return text
    return json.dumps({"truncated": True, "note": "Result too large; narrow the filters.", "preview": text[:MAX_TOOL_CHARS]})


def _trim(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Prior turns as plain text (tool traffic is not replayed), ending on a user turn."""
    turns = [{"role": m["role"], "content": m["content"]} for m in history if m.get("content")]
    return turns[-MAX_HISTORY_TURNS * 2:]


def answer(question: str, history: list[dict[str, str]] | None = None, model: str | None = None,
           client: anthropic.Anthropic | None = None) -> dict[str, Any]:
    model = model or DEFAULT_MODEL
    if model not in {m["id"] for m in MODELS}:
        raise ValueError(f"Unsupported model: {model}")
    client = client or _client()
    data = DataAccess()
    messages: list[dict[str, Any]] = _trim(history or []) + [{"role": "user", "content": question}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    text, request_id, stop = "", None, None

    for _ in range(MAX_STEPS):
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},
        )
        request_id = getattr(response, "_request_id", None)
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        stop = response.stop_reason
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        if stop != "tool_use":
            break

        messages.append({"role": "assistant", "content": response.content})   # keep thinking/tool_use blocks intact
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": _result_text(data.run(block.name, dict(block.input)))})
            except Exception as exc:  # report to the model so it can recover
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": f"{type(exc).__name__}: {exc}"})
        messages.append({"role": "user", "content": results})   # all results in ONE message
    else:
        text = text or "I could not finish working that out. Try asking a narrower question."

    if stop == "refusal":
        text = "The model declined to answer this request."
    elif stop == "max_tokens":
        text = (text + "\n\n(The answer was cut off; ask a narrower question.)").strip()

    return {
        "answer": text or "I did not get an answer back. Please try again.",
        "model": model,
        "tools_used": data.tools_used,
        "visual": data.visual,
        "supporting_transaction_ids": data.supporting_ids,
        "evidence": data.evidence(),
        "usage": usage,
        "request_id": request_id,
    }
