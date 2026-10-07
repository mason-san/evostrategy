"""Stage 2 orchestration: reconcile a whole set of source documents.

source documents
  -> semantic mapping (rules / similarity / optional LLM)
  -> normalization (amounts, dates, entities, identifiers)
  -> document linking (invoice <-> PO / payment / ledger) + duplicate detection
  -> field comparison per linked pair (amount, date, entity) with tolerances
  -> reconciliation cases (MATCHED / AUTO_RESOLVED / ESCALATED / MISSING)
  -> transactions: groups of linked documents that describe one business event

Nothing here mutates the source documents. Every case keeps the document ids,
field ids, raw values and normalized values it was decided on.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ingestion.schemas.contracts import SourceDocument
from reconciliation.comparator import compare_numeric
from reconciliation.document_linking import LinkStatus, evaluate_link
from reconciliation.entity_resolution import ResolutionStatus, resolve_normalized_entities
from reconciliation.normalization import identifier_match_key
from reconciliation.normalization import NormalizedDocument, normalize_document
from reconciliation.semantic_mapping import (
    DocumentType,
    GeminiSemanticProvider,
    SemanticRole,
    map_document,
    normalize_label,
)
from utils.config import DATE_TOLERANCE_DAYS, KEY_FIELD_REVIEW_THRESHOLD, LOW_CONFIDENCE_THRESHOLD

OPEN_STATUSES = {"ESCALATED", "MISSING", "AMBIGUOUS"}
_SEVERITY = {"MATCHED": 0, "AUTO_RESOLVED": 1, "AMBIGUOUS": 2, "MISSING": 3, "ESCALATED": 4}
_PRIMARY_ORDER = [
    DocumentType.INVOICE, DocumentType.LEDGER, DocumentType.PAYMENT,
    DocumentType.PURCHASE_ORDER, DocumentType.UNKNOWN,
]
_AMOUNT_PRIORITY = {
    DocumentType.INVOICE: [SemanticRole.TRANSACTION_TOTAL, SemanticRole.BALANCE_DUE,
                           SemanticRole.ORDER_TOTAL, SemanticRole.SUBTOTAL],
    DocumentType.PAYMENT: [SemanticRole.AMOUNT_PAID, SemanticRole.TRANSACTION_TOTAL,
                           SemanticRole.BALANCE_DUE],
    DocumentType.LEDGER: [SemanticRole.TRANSACTION_TOTAL, SemanticRole.AMOUNT_PAID,
                          SemanticRole.ORDER_TOTAL],
    DocumentType.PURCHASE_ORDER: [SemanticRole.ORDER_TOTAL, SemanticRole.TRANSACTION_TOTAL],
    DocumentType.UNKNOWN: [SemanticRole.TRANSACTION_TOTAL, SemanticRole.AMOUNT_PAID,
                           SemanticRole.ORDER_TOTAL, SemanticRole.BALANCE_DUE],
}
_IDENTIFIER_ROLES = {SemanticRole.INVOICE_ID, SemanticRole.ORDER_ID,
                     SemanticRole.PAYMENT_ID, SemanticRole.DOCUMENT_ID}
_ENTITY_ROLES = (SemanticRole.CUSTOMER, SemanticRole.VENDOR)
_CATEGORY_LABELS = {"category", "account", "expense category", "revenue category"}
_ENTRY_TYPE_LABELS = {"entry type", "type", "transaction type", "direction"}


@dataclass
class DocumentFacts:
    """Comparison-ready facts for one document, with field provenance."""

    document_id: str
    source_name: str
    document_type: DocumentType
    identifiers: dict[str, str] = field(default_factory=dict)  # value -> field_id
    amount: float | None = None
    amount_field: dict[str, Any] | None = None
    date: str | None = None
    date_field: dict[str, Any] | None = None
    entity: str | None = None
    entity_raw: Any = None
    currency: str | None = None
    category: str | None = None
    entry_type: str | None = None
    extraction_confidence: float = 1.0
    low_confidence: bool = False
    weak_fields: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_name": self.source_name,
            "document_type": self.document_type.value,
            "identifiers": sorted(self.identifiers),
            "amount": self.amount,
            "amount_field": self.amount_field,
            "date": self.date,
            "date_field": self.date_field,
            "entity": self.entity_raw,
            "currency": self.currency,
            "category": self.category,
            "entry_type": self.entry_type,
            "extraction_confidence": self.extraction_confidence,
        }


@dataclass
class RunResult:
    cases: list[dict[str, Any]]
    links: list[dict[str, Any]]
    transactions: list[dict[str, Any]]
    facts: dict[str, DocumentFacts]
    summary: dict[str, Any]


def _field_ref(item) -> dict[str, Any]:
    return {
        "field_id": item.field_id,
        "label": item.raw_label,
        "raw_value": item.raw_value,
        "normalized_value": item.normalized_value,
    }


def _facts(source: SourceDocument, normalized: NormalizedDocument) -> DocumentFacts:
    doc_type = DocumentType(normalized.document_type)
    extras = source.model_extra or {}
    facts = DocumentFacts(
        document_id=source.document_id,
        source_name=str(extras.get("source_name") or source.source_path),
        document_type=doc_type,
        extraction_confidence=float(extras.get("extraction_confidence") or 1.0),
        low_confidence=bool(extras.get("low_confidence")),
    )
    by_role: dict[SemanticRole, list] = {}
    for item in normalized.fields:
        if item.semantic_role and item.normalized_value is not None:
            by_role.setdefault(SemanticRole(item.semantic_role), []).append(item)
        label = normalize_label(item.raw_label)
        if label in _CATEGORY_LABELS and item.raw_value:
            facts.category = str(item.raw_value)
        if label in _ENTRY_TYPE_LABELS and item.raw_value:
            facts.entry_type = str(item.raw_value)
    for role in _IDENTIFIER_ROLES:
        for item in by_role.get(role, []):
            facts.identifiers[str(item.normalized_value)] = item.field_id
    for role in _AMOUNT_PRIORITY[doc_type]:
        if by_role.get(role):
            chosen = by_role[role][0]
            facts.amount = abs(float(chosen.normalized_value))
            facts.amount_field = _field_ref(chosen)
            facts.currency = chosen.currency
            break
    if by_role.get(SemanticRole.DOCUMENT_DATE):
        chosen = by_role[SemanticRole.DOCUMENT_DATE][0]
        facts.date = str(chosen.normalized_value)
        facts.date_field = _field_ref(chosen)
    for role in _ENTITY_ROLES:
        if by_role.get(role):
            chosen = by_role[role][0]
            facts.entity = str(chosen.normalized_value)
            facts.entity_raw = chosen.raw_value
            break
    if by_role.get(SemanticRole.CURRENCY):
        facts.currency = facts.currency or str(by_role[SemanticRole.CURRENCY][0].normalized_value)
    _flag_weak_key_fields(source, facts)
    return facts


def _flag_weak_key_fields(source: SourceDocument, facts: DocumentFacts) -> None:
    """Low-confidence review is decided on the fields reconciliation relies on.

    Stage 1 scores every field; a badly read layout line ("Ship To: ; ;") should
    not send an otherwise clear invoice to review, but a doubtful amount, date or
    identifier must. Documents without per-field scores keep Stage 1's flag.
    """
    confidence = {f.field_id: f.confidence for f in source.fields}
    key_ids = [ref["field_id"] for ref in (facts.amount_field, facts.date_field) if ref]
    key_ids += list(facts.identifiers.values())
    labels = {f.field_id: f.label for f in source.fields}
    scored = [(fid, confidence.get(fid)) for fid in key_ids if confidence.get(fid) is not None]
    if not scored:
        return
    facts.weak_fields = [
        {"field_id": fid, "label": labels.get(fid), "confidence": value}
        for fid, value in scored if value < KEY_FIELD_REVIEW_THRESHOLD
    ]
    facts.low_confidence = bool(facts.weak_fields)


# --------------------------------------------------------------------------- comparisons

def _days_between(left: str | None, right: str | None) -> int | None:
    try:
        return (date.fromisoformat(str(right)) - date.fromisoformat(str(left))).days
    except (TypeError, ValueError):
        return None


def _compare_dates(left: DocumentFacts, right: DocumentFacts) -> dict[str, Any]:
    result = {"field": "date", "left_value": left.date, "right_value": right.date,
              "difference": None, "difference_percent": None, "discrepancy_type": None}
    if left.date is None or right.date is None:
        return {**result, "status": "MISSING", "discrepancy_type": "missing_value"}
    days = _days_between(left.date, right.date)
    result["difference"] = days
    types = {left.document_type, right.document_type}
    if days == 0:
        return {**result, "status": "MATCHED"}
    if DocumentType.PAYMENT in types and DocumentType.INVOICE in types:
        invoice, payment = (left, right) if left.document_type == DocumentType.INVOICE else (right, left)
        lag = _days_between(invoice.date, payment.date)
        if lag is not None and 0 <= lag <= 120:
            return {**result, "status": "MATCHED", "note": f"paid {lag} days after invoice"}
        return {**result, "status": "ESCALATED", "discrepancy_type": "payment_date_out_of_terms"}
    if abs(days) <= DATE_TOLERANCE_DAYS:
        return {**result, "status": "AUTO_RESOLVED", "discrepancy_type": "date_variance"}
    return {**result, "status": "ESCALATED", "discrepancy_type": "date_mismatch"}


def _compare_entities(left: DocumentFacts, right: DocumentFacts) -> dict[str, Any] | None:
    if left.entity is None or right.entity is None:
        return None
    resolution = resolve_normalized_entities(left.entity, right.entity)
    base = {"field": "entity", "left_value": left.entity_raw, "right_value": right.entity_raw,
            "difference": None, "difference_percent": None, "score": resolution.score}
    if resolution.status == ResolutionStatus.RESOLVED:
        return {**base, "status": "MATCHED", "discrepancy_type": None}
    if resolution.status == ResolutionStatus.AMBIGUOUS:
        return {**base, "status": "ESCALATED", "discrepancy_type": "entity_alias"}
    return {**base, "status": "ESCALATED", "discrepancy_type": "entity_mismatch"}


def _compare_pair(left: DocumentFacts, right: DocumentFacts) -> list[dict[str, Any]]:
    results = [compare_numeric("amount", left.amount, right.amount).as_dict()]
    if results[0]["discrepancy_type"] == "amount_mismatch":
        results[0]["discrepancy_type"] = "numerical_mismatch"
    results.append(_compare_dates(left, right))
    entity = _compare_entities(left, right)
    if entity:
        results.append(entity)
    return results


def _worst(statuses: list[str]) -> str:
    return max(statuses, key=lambda status: _SEVERITY.get(status, 0)) if statuses else "MATCHED"


# --------------------------------------------------------------------------- grouping

class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def _kind(group: list[DocumentFacts]) -> str:
    for facts in group:
        if facts.entry_type:
            text = facts.entry_type.casefold()
            if any(word in text for word in ("expense", "cost", "debit", "payable")):
                return "expense"
            if any(word in text for word in ("revenue", "income", "credit", "sale", "receivable")):
                return "revenue"
    types = {facts.document_type for facts in group}
    if types == {DocumentType.PURCHASE_ORDER}:
        return "expense"
    return "revenue"


def _transaction(group: list[DocumentFacts], case_ids: list[str]) -> dict[str, Any]:
    ordered = sorted(
        group,
        key=lambda facts: (_PRIMARY_ORDER.index(facts.document_type), facts.amount is None, facts.document_id),
    )
    primary = ordered[0]
    category = next((facts.category for facts in ordered if facts.category), None)
    counterparty = next((facts.entity_raw for facts in ordered if facts.entity_raw), None)
    identifiers = sorted({value for facts in group for value in facts.identifiers})
    return {
        "transaction_id": "txn:" + min(facts.document_id for facts in group),
        "document_ids": sorted(facts.document_id for facts in group),
        "document_types": sorted({facts.document_type.value for facts in group}),
        "primary_document_id": primary.document_id,
        "kind": _kind(group),
        "category": category or ("Sales" if primary.document_type == DocumentType.INVOICE else "Uncategorised"),
        "counterparty": counterparty,
        "identifiers": identifiers,
        "date": primary.date,
        "amount": primary.amount,
        "currency": primary.currency,
        "case_ids": sorted(set(case_ids)),
        "source_count": len(group),
    }


REFERENCE_FREE_AMOUNT_WINDOW = 0.25  # candidate window only; the 2% tolerance still decides


def _reference_free_ledger_links(
    facts: dict[str, DocumentFacts],
    pairs: list[tuple[str, str, str]],
    cases: list[dict[str, Any]],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Link invoices to ledger postings that were booked without the invoice reference.

    A link is made only when exactly one unreferenced revenue posting lies within
    the date tolerance and a broad amount window of the invoice, and that
    posting has no other such invoice. The normal comparison then decides
    whether the amounts and dates agree, so a wrong-amount posting is still
    escalated. Everything else stays unlinked and is reported as missing.
    """
    paired = {doc_id for left_id, right_id, _ in pairs for doc_id in (left_id, right_id)
              if DocumentType.LEDGER in (facts[left_id].document_type, facts[right_id].document_type)}
    contested = {doc_id for case in cases if case.get("case_type") == "ambiguous_link" for doc_id in case["document_ids"]}
    invoices = [f for f in facts.values() if f.document_type == DocumentType.INVOICE
                and f.document_id not in paired and f.document_id not in contested
                and f.amount is not None and f.date is not None]
    postings = [f for f in facts.values() if f.document_type == DocumentType.LEDGER and not f.identifiers
                and f.document_id not in paired and f.amount is not None and f.date is not None
                and _kind([f]) == "revenue"]

    def close(invoice: DocumentFacts, posting: DocumentFacts) -> bool:
        days = _days_between(invoice.date, posting.date)
        baseline = max(abs(invoice.amount), 1.0)
        return (days is not None and abs(days) <= DATE_TOLERANCE_DAYS
                and abs(invoice.amount - posting.amount) / baseline <= REFERENCE_FREE_AMOUNT_WINDOW)

    candidates = {inv.document_id: [p.document_id for p in postings if close(inv, p)] for inv in invoices}
    claimed: dict[str, int] = {}
    for found in candidates.values():
        for posting_id in found:
            claimed[posting_id] = claimed.get(posting_id, 0) + 1
    links = []
    for invoice_id, found in candidates.items():
        if len(found) == 1 and claimed[found[0]] == 1:
            left_id, right_id = sorted((invoice_id, found[0]))
            links.append((left_id, right_id, {
                "link_id": f"{left_id}|{right_id}", "left_document_id": left_id,
                "right_document_id": right_id, "relationship": "INVOICE_LEDGER",
                "status": "LINKED", "linked": True, "confidence": 0.55,
                "evidence": {"method": "unique_amount_date_match", "shared_identifiers": [],
                             "note": "Ledger posting has no invoice reference; matched on amount and date."},
            }))
    return links


def _fold_duplicate_symptoms(
    cases: list[dict[str, Any]],
    pairs: list[tuple[str, str, str]],
    facts: dict[str, DocumentFacts],
) -> list[dict[str, Any]]:
    """Merge "ledger vs duplicate copy" mismatches into the duplicate case.

    When two invoices share an identifier and the ledger agrees with one of
    them, the ledger necessarily disagrees with the other. That second mismatch
    is a symptom of the duplicate, not a separate problem, so instead of asking
    the reviewer twice it is attached to the (still escalated) duplicate case as
    evidence. Nothing is hidden: the duplicate case stays open and the
    transaction stays out of analytics until a reviewer decides.
    """
    by_id = {case["case_id"]: case for case in cases}

    def pair_case(a: str, b: str) -> dict[str, Any] | None:
        left, right = sorted((a, b))
        return by_id.get(f"pair:{left}|{right}")

    partners: dict[str, set[str]] = {}
    for left_id, right_id, relationship in pairs:
        if relationship != "DUPLICATE":
            partners.setdefault(left_id, set()).add(right_id)
            partners.setdefault(right_id, set()).add(left_id)

    folded: set[str] = set()
    for left_id, right_id, relationship in pairs:
        if relationship != "DUPLICATE":
            continue
        duplicate = pair_case(left_id, right_id)
        if duplicate is None:
            continue
        for other in partners.get(left_id, set()) & partners.get(right_id, set()):
            first, second = pair_case(other, left_id), pair_case(other, right_id)
            if not first or not second:
                continue
            for agrees, disagrees, copy_id in ((first, second, right_id), (second, first, left_id)):
                if agrees["status"] in {"MATCHED", "AUTO_RESOLVED"} and disagrees["status"] == "ESCALATED":
                    folded.add(disagrees["case_id"])
                    duplicate.setdefault("related_evidence", []).append({
                        "folded_case_id": disagrees["case_id"],
                        "document_ids": disagrees["document_ids"],
                        "results": disagrees["results"],
                        "explanation": disagrees["explanation"],
                    })
                    duplicate["explanation"] += (
                        f" The {facts[other].document_type.value.lower()} entry agrees with "
                        f"{facts[left_id if copy_id == right_id else right_id].source_name}; "
                        f"{facts[copy_id].source_name} differs ({disagrees['explanation']})"
                    )
    return [case for case in cases if case["case_id"] not in folded]


# --------------------------------------------------------------------------- run

def reconcile_documents(
    sources: list[SourceDocument], *, use_llm: bool | None = None
) -> RunResult:
    """Run the full Stage 2 reconciliation over every stored source document."""
    if use_llm is None:
        use_llm = bool(os.environ.get("GEMINI_API_KEY"))
    provider = GeminiSemanticProvider() if use_llm else None

    normalized: dict[str, NormalizedDocument] = {}
    facts: dict[str, DocumentFacts] = {}
    for source in sources:
        doc = normalize_document(map_document(source, llm_provider=provider))
        normalized[source.document_id] = doc
        facts[source.document_id] = _facts(source, doc)

    ids = sorted(facts)
    union = _UnionFind(ids)
    links: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    pairs: list[tuple[str, str, str]] = []  # (left, right, relationship)

    # 1. cross-type links (invoice <-> PO / payment / ledger)
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1:]:
            left, right = facts[left_id], facts[right_id]
            if left.document_type == right.document_type:
                left_keys = {identifier_match_key(value): value for value in left.identifiers}
                shared = {left_keys[identifier_match_key(value)] for value in right.identifiers
                          if identifier_match_key(value) in left_keys}
                if shared and left.document_type != DocumentType.UNKNOWN:
                    union.union(left_id, right_id)
                    pairs.append((left_id, right_id, "DUPLICATE"))
                    links.append({
                        "link_id": f"{left_id}|{right_id}", "left_document_id": left_id,
                        "right_document_id": right_id, "relationship": "DUPLICATE",
                        "status": "LINKED", "confidence": 1.0,
                        "evidence": {"shared_identifiers": sorted(shared)},
                    })
                continue
            try:
                result = evaluate_link(normalized[left_id], normalized[right_id])
            except ValueError:
                continue  # unsupported relationship
            if result.status == LinkStatus.UNLINKED:
                continue
            link = {**result.model_dump(), "link_id": f"{left_id}|{right_id}"}
            links.append(link)
            if result.status == LinkStatus.LINKED:
                union.union(left_id, right_id)
                pairs.append((left_id, right_id, result.relationship.value))
            else:
                cases.append({
                    "case_id": f"link:{left_id}|{right_id}",
                    "case_type": "ambiguous_link",
                    "status": "ESCALATED",
                    "document_ids": [left_id, right_id],
                    "relationship": result.relationship.value,
                    "discrepancy_types": ["ambiguous_link"],
                    "confidence": result.confidence,
                    "evidence": result.evidence.model_dump(),
                    "results": [],
                    "explanation": "These documents partly agree but the evidence is not strong enough to link them automatically.",
                })

    # 1b. ledger postings that carry no reference: link only on a unique amount + date match
    for left_id, right_id, link in _reference_free_ledger_links(facts, pairs, cases):
        union.union(left_id, right_id)
        pairs.append((left_id, right_id, "INVOICE_LEDGER"))
        links.append(link)

    # 2. field comparisons for linked pairs and duplicates
    for left_id, right_id, relationship in pairs:
        results = _compare_pair(facts[left_id], facts[right_id])
        if relationship == "DUPLICATE":
            status = "ESCALATED"
            types = ["duplicate_entry"] + [r["discrepancy_type"] for r in results if r.get("discrepancy_type")]
            explanation = (
                f"Two {facts[left_id].document_type.value.lower().replace('_', ' ')}s carry the same "
                f"identifier. Confirm whether this is a re-issue, a correction or a double entry."
            )
        else:
            status = _worst([r["status"] for r in results])
            types = [r["discrepancy_type"] for r in results if r.get("discrepancy_type")]
            explanation = _explain(results)
        cases.append({
            "case_id": f"pair:{left_id}|{right_id}",
            "case_type": "duplicate_entry" if relationship == "DUPLICATE" else "document_pair",
            "status": status,
            "document_ids": [left_id, right_id],
            "relationship": relationship,
            "discrepancy_types": sorted(set(types)),
            "results": results,
            "explanation": explanation,
        })

    cases = _fold_duplicate_symptoms(cases, pairs, facts)

    # 3. per-document checks: extraction confidence, missing counterparts
    linked_ids = {doc_id for left_id, right_id, _ in pairs for doc_id in (left_id, right_id)}
    ledger_linked = {
        doc_id
        for left_id, right_id, _ in pairs
        if DocumentType.LEDGER in (facts[left_id].document_type, facts[right_id].document_type)
        for doc_id in (left_id, right_id)
    }
    has_ledger = any(f.document_type == DocumentType.LEDGER for f in facts.values())
    duplicate_partners: dict[str, set[str]] = {}
    for left_id, right_id, relationship in pairs:
        if relationship == "DUPLICATE":
            duplicate_partners.setdefault(left_id, set()).add(right_id)
            duplicate_partners.setdefault(right_id, set()).add(left_id)
    for doc_id in ids:
        booked_copy = duplicate_partners.get(doc_id, set()) & ledger_linked
        if has_ledger and facts[doc_id].document_type == DocumentType.INVOICE and doc_id not in ledger_linked and booked_copy:
            # the duplicate case already asks the reviewer about this copy
            duplicate = next((c for c in cases if c["case_type"] == "duplicate_entry" and doc_id in c["document_ids"]), None)
            if duplicate is not None:
                duplicate["explanation"] += f" Only {facts[sorted(booked_copy)[0]].source_name} is booked in the ledger."
        elif has_ledger and facts[doc_id].document_type == DocumentType.INVOICE and doc_id not in ledger_linked:
            cases.append({
                "case_id": f"doc:{doc_id}:missing-ledger",
                "case_type": "missing_document",
                "status": "MISSING",
                "document_ids": [doc_id],
                "discrepancy_types": ["missing_document"],
                "results": [],
                "explanation": "This invoice has no matching entry in the general ledger — it may not have been booked.",
            })
        doc = facts[doc_id]
        missing = [name for name, value in (("amount", doc.amount), ("date", doc.date)) if value is None]
        if doc.document_type != DocumentType.UNKNOWN and (doc.low_confidence or missing):
            if doc.low_confidence and doc.weak_fields:
                reason = "Read with low OCR confidence: " + ", ".join(
                    f"{w['label']} ({w['confidence']:.0%})" for w in doc.weak_fields
                ) + f" — below the {KEY_FIELD_REVIEW_THRESHOLD:.0%} key-field review threshold."
            elif doc.low_confidence:
                reason = (f"Extraction confidence {doc.extraction_confidence:.1%} is below the "
                          f"{LOW_CONFIDENCE_THRESHOLD:.0%} review threshold.")
            else:
                reason = ""
            if missing:
                reason = (reason + " " if reason else "") + f"Could not read: {', '.join(missing)}."
            cases.append({
                "case_id": f"doc:{doc_id}:extraction",
                "case_type": "low_confidence_extraction",
                "status": "ESCALATED",
                "document_ids": [doc_id],
                "discrepancy_types": ["low_confidence_extraction"],
                "results": [],
                "explanation": reason,
            })
        if doc.document_type == DocumentType.PAYMENT and doc_id not in linked_ids:
            cases.append({
                "case_id": f"doc:{doc_id}:missing-invoice",
                "case_type": "missing_document",
                "status": "MISSING",
                "document_ids": [doc_id],
                "discrepancy_types": ["missing_document"],
                "results": [],
                "explanation": "This payment does not match any invoice on file.",
            })

    # 4. transactions = connected groups of documents
    groups: dict[str, list[DocumentFacts]] = {}
    for doc_id in ids:
        groups.setdefault(union.find(doc_id), []).append(facts[doc_id])
    group_of = {doc_id: union.find(doc_id) for doc_id in ids}
    case_ids_by_group: dict[str, list[str]] = {}
    for case in cases:
        case_ids_by_group.setdefault(group_of[case["document_ids"][0]], []).append(case["case_id"])
    transactions = []
    for root, group in groups.items():
        transaction = _transaction(group, case_ids_by_group.get(root, []))
        transactions.append(transaction)
        for case in cases:
            if case["case_id"] in transaction["case_ids"]:
                case["transaction_id"] = transaction["transaction_id"]
    for case in cases:
        case.setdefault("transaction_id", "txn:" + group_of[case["document_ids"][0]])
        case["documents"] = [facts[doc_id].as_dict() for doc_id in case["document_ids"]]

    status_counts: dict[str, int] = {}
    for case in cases:
        status_counts[case["status"]] = status_counts.get(case["status"], 0) + 1
    summary = {
        "documents": len(ids),
        "fields": sum(len(doc.fields) for doc in normalized.values()),
        "mapped_fields": sum(1 for doc in normalized.values() for f in doc.fields if f.semantic_role),
        "links": sum(1 for link in links if link["status"] == "LINKED"),
        "transactions": len(transactions),
        "cases": len(cases),
        "case_status_counts": status_counts,
        "document_types": _count(facts[doc_id].document_type.value for doc_id in ids),
    }
    return RunResult(cases, links, transactions, facts, summary)


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _explain(results: list[dict[str, Any]]) -> str:
    messages = []
    for result in results:
        if result["status"] in {"MATCHED"}:
            continue
        if result["field"] == "amount" and result["status"] == "AUTO_RESOLVED":
            messages.append(f"Amounts differ by {result['difference_percent']}% — within tolerance, auto-resolved.")
        elif result["field"] == "amount" and result["status"] == "ESCALATED":
            messages.append(f"Amounts differ by {result['difference_percent']}% ({result['left_value']} vs {result['right_value']}), beyond tolerance.")
        elif result["status"] == "MISSING":
            messages.append(f"{result['field'].capitalize()} is missing on one side.")
        elif result["field"] == "date":
            messages.append(f"Dates differ by {abs(result['difference'] or 0)} days.")
        elif result["field"] == "entity":
            messages.append(f"Counterparty names differ ({result['left_value']} vs {result['right_value']}).")
    return " ".join(messages) or "All compared fields agree."
