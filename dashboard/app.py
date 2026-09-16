"""Streamlit dashboard for testing real extraction reconciliation cases."""

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.service import load_extraction_files, reconcile_files
from storage.registry import get_cases, get_review_actions, log_review_action
from utils.config import EXTRACTION_DIR, REGISTRY_DB

st.set_page_config(page_title="EvoStrategy Reconciliation", layout="wide")
st.title("EvoStrategy Reconciliation Dashboard")
st.caption("Loads real Stage 1 JSON output and runs the Phase 2 reconciliation engine.")

documents = load_extraction_files()
if len(documents) < 1:
    st.warning(f"No extracted JSON files found in {EXTRACTION_DIR}. Run pipeline.py first.")
    st.stop()

document_names = list(documents)
left_name = st.selectbox("Left document", document_names)
right_name = st.selectbox(
    "Right document", document_names, index=min(1, len(document_names) - 1)
)

if st.button("Run reconciliation", type="primary"):
    case = reconcile_files(left_name, right_name, documents)
    st.session_state["selected_case_id"] = case["case_id"]
    st.success(f"Saved case {case['case_id']} with status {case['status']}.")

cases = get_cases()
selected_case_id = st.session_state.get("selected_case_id")
selected_case = next(
    (case for case in cases if case["case_id"] == selected_case_id), None
)

if selected_case:
    st.subheader(f"Case: {selected_case['case_id']}")
    st.metric("Status", selected_case["status"])
    results = selected_case["results"]
    st.dataframe(results, width="stretch")

    st.subheader("Canonical values")
    left_column, right_column = st.columns(2)
    left_column.json(selected_case["mapping"]["left"])
    right_column.json(selected_case["mapping"]["right"])

    with st.form("review_form"):
        reviewer = st.text_input("Reviewer", value="local-reviewer")
        action = st.selectbox("Action", ["ACCEPT", "REJECT", "CORRECT"])
        reason = st.text_area("Reason", disabled=action == "ACCEPT")
        corrected_value = st.text_input("Corrected value", disabled=action != "CORRECT")
        submitted = st.form_submit_button("Save review action")
    if submitted:
        if action != "ACCEPT" and not reason.strip():
            st.error("A reason is required for REJECT and CORRECT.")
        else:
            log_review_action(
                selected_case["case_id"],
                action,
                reviewer.strip() or "local-reviewer",
                reason.strip() or None,
                corrected_value.strip() or None,
            )
            st.success("Review action saved to the audit log.")
            st.rerun()

st.subheader("Persisted cases")
st.dataframe(
    [
        {
            "case_id": case["case_id"],
            "status": case["status"],
            "left": case["left_document"],
            "right": case["right_document"],
        }
        for case in cases
    ],
    width="stretch",
)

if selected_case:
    st.subheader("Review audit")
    st.dataframe(get_review_actions(selected_case["case_id"]), width="stretch")

st.caption(f"Registry: {REGISTRY_DB}")
