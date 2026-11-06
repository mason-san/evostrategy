"""Question answering over verified EvoStrategy data with Groq tool use.

The model never sees raw documents or the database. It gets the read-only tools
in ``assistant.tools`` and must ground every number in a tool result, so an
answer can only be as wrong as the verified data it was computed from.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import asdict
from typing import Any

from groq import Groq
from google.genai import types
from dotenv import load_dotenv

from utils.config import PROJECT_ROOT

from .tools import TOOL_DEFINITIONS, DataAccess
from rag import generation as rag_generation

load_dotenv(PROJECT_ROOT / ".env")

GROQ_MODELS: list[dict[str, str]] = [
    {"id": "llama-3.3-70b-versatile", "label": "Llama 3.3 70B", "note": "Most capable"},
]
MAX_STEPS = 8
MAX_TOOL_CHARS = 40_000
MAX_HISTORY_TURNS = 12

_DOCUMENT_TERMS = (
    "invoice", "invoices", "document", "documents", "uploaded", "receipt", "receipts",
    "bill", "bills", "payment terms", "purchase order", "supplier",
)

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
    """Raised when the configured LLM provider cannot be used."""


def is_document_question(question: str) -> bool:
    """Return whether a question explicitly asks about uploaded documents."""
    normalized = question.casefold()
    return any(term in normalized for term in _DOCUMENT_TERMS)


def _without_source_section(answer: str) -> str:
    """Keep generated source attribution in structured fields, not answer prose."""
    lines = answer.splitlines()
    kept: list[str] = []
    for line in lines:
        if line.strip().casefold() in {"source:", "sources:", "source"} or line.strip().casefold().startswith(("source:", "sources:")):
            break
        kept.append(line)
    return "\n".join(kept).strip() or answer


def _answer_rag(question: str) -> dict[str, Any]:
    """Run the Step 6 grounded generator and adapt it to the assistant contract."""
    result = rag_generation.answer_question(question)
    chunks = [
        {
            "chunk_id": chunk.get("chunk_id"),
            "document_id": chunk.get("document_id"),
            "document_type": chunk.get("document_type"),
            "chunk_text": str(chunk.get("chunk_text") or "")[:1600],
            "similarity_score": chunk.get("similarity_score"),
        }
        for chunk in result.get("retrieved_chunks", [])
    ]
    evidence = DataAccess().evidence()
    return {
        "answer": _without_source_section(str(result.get("answer") or "")),
        "answer_kind": "document",
        "model": result.get("model", ""),
        "tools_used": [],
        "visual": None,
        "supporting_transaction_ids": [],
        "evidence": evidence,
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "request_id": None,
        "rag": {
            "generation_status": result.get("generation_status"),
            "sources": result.get("sources", []),
            "retrieved_chunks": chunks,
        },
    }


def status() -> dict[str, Any]:
    provider = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
    if provider == "auto":
        provider = "groq" if os.environ.get("GROQ_API_KEY") else "ollama"
    is_ollama = provider == "ollama"
    configured = bool(os.environ.get("OLLAMA_MODEL") or os.environ.get("ASSISTANT_MODEL")) if is_ollama else bool(os.environ.get("GROQ_API_KEY"))
    preferred = os.environ.get("ASSISTANT_MODEL", GROQ_MODELS[0]["id"]).strip()
    configured_models = [{**m, "provider": "groq", "available": configured} for m in GROQ_MODELS]
    if is_ollama:
        preferred = os.environ.get("OLLAMA_MODEL", os.environ.get("ASSISTANT_MODEL", "")).strip()
        configured_models = [{
            "id": preferred,
            "label": preferred or "Ollama model",
            "note": "Local Ollama model",
            "provider": "ollama",
            "available": configured,
        }] if preferred else []
    if preferred not in {m["id"] for m in configured_models}:
        configured_models.insert(0, {
            "id": preferred,
            "label": preferred,
            "note": "Configured model",
            "provider": provider,
            "available": configured,
        })
    models = configured_models
    usable = [m["id"] for m in models if m["available"]]
    default = preferred if configured else (usable[0] if usable else preferred)
    return {
        "configured": bool(usable),
        "models": models,
        "default_model": default,
        "setup_hint": (
            "Set LLM_PROVIDER=ollama and OLLAMA_MODEL=... in the project .env."
            if is_ollama else
            "Add GROQ_API_KEY=... to a .env file in the project root and restart the backend."
        ),
    }


def _client() -> Groq:
    if not os.environ.get("GROQ_API_KEY"):
        raise AssistantUnavailable(status()["setup_hint"])
    return Groq(api_key=os.environ["GROQ_API_KEY"])


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
    desk: dict[str, Any] = {}
    if hasattr(data, "scenario"):   # what-if desk: hand the final levers and numbers back to the screen
        desk = {"scenario": asdict(data.scenario), "simulation": data.simulation}
    return {
        **desk,
        "answer": text or "I did not get an answer back. Please try again.",
        "model": model,
        "tools_used": data.tools_used,
        "visual": data.visual,
        "supporting_transaction_ids": data.supporting_ids,
        "evidence": data.evidence(),
        "usage": usage,
        "request_id": request_id,
    }


def _setup(data: DataAccess | None) -> tuple[DataAccess, str, list[dict[str, Any]]]:
    """The data snapshot, system prompt and tool list for one question (a session may extend them)."""
    data = data or DataAccess()
    return data, SYSTEM_PROMPT + getattr(data, "system_extra", ""), getattr(data, "tool_definitions", TOOL_DEFINITIONS)


def answer(question: str, history: list[dict[str, str]] | None = None, model: str | None = None,
           client: Any | None = None, session: DataAccess | None = None) -> dict[str, Any]:
    provider = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
    if provider == "auto":
        provider = "groq" if os.environ.get("GROQ_API_KEY") else "ollama"
    model = model or status()["default_model"]
    # Keep injected legacy clients working for deterministic tests and integrations.
    legacy_models = {"gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"}
    if model not in {m["id"] for m in GROQ_MODELS} and model not in legacy_models:
        configured_model = os.environ.get("ASSISTANT_MODEL", "").strip()
        ollama_model = os.environ.get("OLLAMA_MODEL", "").strip()
        if model not in {configured_model, ollama_model}:
            raise ValueError(f"Unsupported model: {model}")
    if session is None and is_document_question(question):
        return _answer_rag(question)
    if client is None and model in legacy_models:
        raise AssistantUnavailable(status()["setup_hint"])
    if client is not None and hasattr(client, "models"):
        return _answer_legacy(question, history or [], model, client, session, types)
    if provider == "ollama":
        return _answer_ollama(question, history or [], model, session)
    return _answer_groq(question, history or [], model, client, session)


def _groq_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {
        "name": tool["name"], "description": tool["description"], "parameters": tool["input_schema"],
    }} for tool in tools]


def _groq_messages(history: list[dict[str, str]], question: str, system: str) -> list[dict[str, Any]]:
    return [{"role": "system", "content": system}, *[
        {"role": "assistant" if turn["role"] == "assistant" else "user", "content": turn["content"]}
        for turn in _trim(history)
    ], {"role": "user", "content": question}]


def _groq_assistant_message(message: Any) -> dict[str, Any]:
    """Keep only fields supported when replaying a Groq assistant response."""
    result: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in message.tool_calls
        ]
    return result


def _answer_groq(question: str, history: list[dict[str, str]], model: str,
                 client: Groq | None, session: DataAccess | None = None) -> dict[str, Any]:
    """Answer a question with Groq's OpenAI-compatible function-calling API."""
    client = client or _client()
    data, system, tools = _setup(session)
    messages = _groq_messages(history, question, system)
    usage = {"input_tokens": 0, "output_tokens": 0}
    text, request_id = "", None
    for _ in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=model, messages=messages, tools=_groq_tools(tools), temperature=0.2
        )
        request_id = getattr(response, "id", None)
        metadata = getattr(response, "usage", None)
        usage["input_tokens"] += getattr(metadata, "prompt_tokens", 0) or 0
        usage["output_tokens"] += getattr(metadata, "completion_tokens", 0) or 0
        message = response.choices[0].message
        calls = message.tool_calls or []
        messages.append(_groq_assistant_message(message))
        text = message.content or ""
        if not calls:
            break
        for call in calls:
            try:
                result = data.run(call.function.name, json.loads(call.function.arguments or "{}"))
            except Exception as exc:  # report to the model so it can recover
                result = {"error": f"{type(exc).__name__}: {exc}"}
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({"result": result})})
    return _finish(data, text.strip(), model, usage, request_id)


def _answer_ollama(question: str, history: list[dict[str, str]], model: str,
                   session: DataAccess | None = None) -> dict[str, Any]:
    """Answer a question with Ollama's local chat API and function calling."""
    data, system, tools = _setup(session)
    messages = _groq_messages(history, question, system)
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "tools": _groq_tools(tools),
        "stream": False,
        "options": {"temperature": 0.2},
    }).encode()
    request = urllib.request.Request(
        f"{os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    usage = {"input_tokens": 0, "output_tokens": 0}
    text, request_id = "", None
    for _ in range(MAX_STEPS):
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read())
        message = body.get("message", {})
        request_id = body.get("created_at")
        messages.append({
            "role": "assistant",
            "content": message.get("content", ""),
            **({"tool_calls": message["tool_calls"]} if message.get("tool_calls") else {}),
        })
        text = message.get("content", "")
        calls = message.get("tool_calls") or []
        if not calls:
            break
        for call in calls:
            function = call.get("function", {})
            arguments = function.get("arguments", {})
            try:
                result = data.run(function["name"], arguments)
            except Exception as exc:  # report to the model so it can recover
                result = {"error": f"{type(exc).__name__}: {exc}"}
            messages.append({"role": "tool", "content": json.dumps({"result": result})})
        payload = json.dumps({**json.loads(payload), "messages": messages}).encode()
        request = urllib.request.Request(
            request.full_url, data=payload, headers={"Content-Type": "application/json"}
        )
    return _finish(data, text.strip(), model, usage, request_id)


def _gemini_tools(tools: list[dict[str, Any]]) -> list[types.Tool]:
    def schema(value: Any) -> Any:
        if isinstance(value, list):
            return [schema(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "anyOf" in value:
            choices = [choice for choice in value["anyOf"] if choice.get("type") != "null"]
            return schema(choices[0] if choices else {"type": "string"})
        result = {key: schema(item) for key, item in value.items() if key != "additionalProperties"}
        if isinstance(result.get("type"), list):
            result["type"] = next((item for item in result["type"] if item != "null"), "string")
        return result

    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=schema(tool["input_schema"]),
        )
        for tool in tools
    ])]


def _gemini_contents(history: list[dict[str, str]], question: str) -> list[types.Content]:
    return [
        types.Content(role="model" if turn["role"] == "assistant" else "user",
                      parts=[types.Part.from_text(text=turn["content"])])
        for turn in _trim(history)
    ] + [types.Content(role="user", parts=[types.Part.from_text(text=question)])]


def _answer_legacy(question: str, history: list[dict[str, str]], model: str,
                   client: Any, session: DataAccess | None, _types: Any) -> dict[str, Any]:
    """Run the legacy injected client adapter used by deterministic tests."""
    client = client or _client()
    data, system, tools = _setup(session)
    contents = _gemini_contents(history, question)
    usage = {"input_tokens": 0, "output_tokens": 0}
    text, request_id = "", None

    for _ in range(MAX_STEPS):
        response = client.models.generate_content(
            model=model, contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=_gemini_tools(tools),
                temperature=0.2,
            ),
        )
        request_id = getattr(response, "response_id", None)
        metadata = getattr(response, "usage_metadata", None)
        usage["input_tokens"] += getattr(metadata, "prompt_token_count", 0) or 0
        usage["output_tokens"] += getattr(metadata, "candidates_token_count", 0) or 0
        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content:
            break
        contents.append(candidate.content)
        calls = [part.function_call for part in candidate.content.parts if part.function_call]
        text = "".join(part.text for part in candidate.content.parts if part.text).strip()
        if not calls:
            break
        results = []
        for call in calls:
            try:
                result = data.run(call.name, dict(call.args or {}))
            except Exception as exc:  # report to the model so it can recover
                result = {"error": f"{type(exc).__name__}: {exc}"}
            results.append(types.Part.from_function_response(
                name=call.name, response={"result": result},
            ))
        contents.append(types.Content(role="user", parts=results))
    else:
        text = text or "I could not finish working that out. Try asking a narrower question."
    return _finish(data, text, model, usage, request_id)
