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
import httpx
from dotenv import load_dotenv

from utils.config import PROJECT_ROOT

from .tools import TOOL_DEFINITIONS, DataAccess

load_dotenv(PROJECT_ROOT / ".env")

ANTHROPIC_MODELS: list[dict[str, str]] = [
    {"id": "claude-opus-5-5", "label": "Claude Opus 5.5", "note": "Most capable"},
    {"id": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5", "note": "Balanced"},
    {"id": "claude-haiku-5-5", "label": "Claude Haiku 5.5", "note": "Fastest, cheapest"},
]
OLLAMA_PREFIX = "ollama:"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_TIMEOUT = 600.0
OLLAMA_NUM_CTX = 16384
OLLAMA_TOOL_CHARS = 12_000   # local models have small contexts; keep tool results compact
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


def _ollama_models() -> list[str]:
    """Installed Ollama models that can call tools (empty when Ollama is not running)."""
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=1.5).json().get("models", [])
    except Exception:
        return []
    names = []
    for tag in tags:
        try:
            info = httpx.post(f"{OLLAMA_URL}/api/show", json={"model": tag["name"]}, timeout=3).json()
            if "tools" in (info.get("capabilities") or []):
                names.append(tag["name"])
        except Exception:
            continue
    return names


def status() -> dict[str, Any]:
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    models = [{**m, "provider": "anthropic", "available": has_key} for m in ANTHROPIC_MODELS]
    models += [{"id": OLLAMA_PREFIX + name, "label": name, "note": "Local (Ollama)", "provider": "ollama", "available": True}
               for name in _ollama_models()]
    preferred = os.environ.get("ASSISTANT_MODEL", ANTHROPIC_MODELS[0]["id"])
    usable = [m["id"] for m in models if m["available"]]
    default = preferred if preferred in usable else (usable[0] if usable else preferred)
    return {
        "configured": bool(usable),
        "models": models,
        "default_model": default,
        "setup_hint": "Add ANTHROPIC_API_KEY=... to a .env file in the project root and restart the backend, "
                      "or start Ollama (ollama serve) with a tool-capable model.",
    }


def _client() -> anthropic.Anthropic:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AssistantUnavailable(status()["setup_hint"])
    return anthropic.Anthropic()


def _result_text(value: Any, limit: int = MAX_TOOL_CHARS) -> str:
    text = json.dumps(value, default=str)
    if len(text) <= limit:
        return text
    return json.dumps({"truncated": True, "note": "Result too large; narrow the filters.", "preview": text[:limit]})


def _trim(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Prior turns as plain text (tool traffic is not replayed), ending on a user turn."""
    turns = [{"role": m["role"], "content": m["content"]} for m in history if m.get("content")]
    return turns[-MAX_HISTORY_TURNS * 2:]


def _finish(data: DataAccess, text: str, model: str, usage: dict[str, int], request_id: str | None) -> dict[str, Any]:
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


def answer(question: str, history: list[dict[str, str]] | None = None, model: str | None = None,
           client: anthropic.Anthropic | None = None) -> dict[str, Any]:
    model = model or status()["default_model"]
    if model.startswith(OLLAMA_PREFIX) and len(model) > len(OLLAMA_PREFIX):
        return _answer_ollama(question, history or [], model[len(OLLAMA_PREFIX):])
    if model not in {m["id"] for m in ANTHROPIC_MODELS}:
        raise ValueError(f"Unsupported model: {model}")
    return _answer_anthropic(question, history or [], model, client)


def _answer_anthropic(question: str, history: list[dict[str, str]], model: str,
                      client: anthropic.Anthropic | None) -> dict[str, Any]:
    client = client or _client()
    data = DataAccess()
    messages: list[dict[str, Any]] = _trim(history) + [{"role": "user", "content": question}]
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
    return _finish(data, text, model, usage, request_id)


def _ollama_tools() -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in TOOL_DEFINITIONS]


def _answer_ollama(question: str, history: list[dict[str, str]], name: str, http: Any = None) -> dict[str, Any]:
    """Same tool loop against a local model through Ollama's /api/chat."""
    post = http or httpx.post
    data = DataAccess()
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}] + _trim(history) + [{"role": "user", "content": question}]
    usage = {"input_tokens": 0, "output_tokens": 0}
    text = ""

    for _ in range(MAX_STEPS):
        try:
            reply = post(f"{OLLAMA_URL}/api/chat", timeout=OLLAMA_TIMEOUT, json={
                "model": name, "messages": messages, "tools": _ollama_tools(), "stream": False, "think": False,
                "options": {"num_ctx": OLLAMA_NUM_CTX, "temperature": 0.2},
            })
            reply.raise_for_status()
        except httpx.HTTPError as exc:
            raise AssistantUnavailable(f"Could not get an answer from Ollama ({type(exc).__name__}). Is `ollama serve` running with {name} installed?") from exc
        body = reply.json()
        usage["input_tokens"] += body.get("prompt_eval_count", 0)
        usage["output_tokens"] += body.get("eval_count", 0)
        message = body.get("message", {})
        text = (message.get("content") or "").strip()
        calls = message.get("tool_calls") or []
        if not calls:
            break
        messages.append(message)
        for call in calls:
            function = call.get("function", {})
            try:
                args = function.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args)
                content = _result_text(data.run(function.get("name", ""), dict(args)), OLLAMA_TOOL_CHARS)
            except Exception as exc:
                content = f"Error: {type(exc).__name__}: {exc}"
            messages.append({"role": "tool", "tool_name": function.get("name", ""), "content": content})
    else:
        text = text or "I could not finish working that out. Try asking a narrower question."
    return _finish(data, text, OLLAMA_PREFIX + name, usage, None)
