import streamlit as st

from auth import login_screen, logout_button
from audit_log import init_db, log_action, get_all_logs
from mock_data import MOCK_RECORDS

st.set_page_config(page_title="EvoStrategy — Verification Dashboard", layout="wide")

init_db()

# ---- auth gate ----
if not login_screen():
    st.stop()

user = st.session_state["user"]

# ---- track per-record status locally for this demo ----
if "record_status" not in st.session_state:
    st.session_state["record_status"] = {r["record_id"]: "PENDING" for r in MOCK_RECORDS}

# ---- sidebar: queue ----
st.sidebar.markdown(f"**Signed in as** {user['username']} ({user['role']})")
logout_button()
st.sidebar.divider()

pending = [
    r for r in MOCK_RECORDS
    if st.session_state["record_status"][r["record_id"]] == "PENDING"
]
st.sidebar.subheader(f"Queue ({len(pending)})")

if "selected_record" not in st.session_state and pending:
    st.session_state["selected_record"] = pending[0]["record_id"]

for r in pending:
    label = f"{r['record_id']} — {r['discrepancy_type']}"
    if st.sidebar.button(label, use_container_width=True):
        st.session_state["selected_record"] = r["record_id"]

if user["role"] == "admin":
    st.sidebar.divider()
    show_audit = st.sidebar.checkbox("View audit log")
else:
    show_audit = False

# ---- main panel ----
st.title("Verification dashboard")

if show_audit:
    st.subheader("Audit log — all reviewers")
    logs = get_all_logs()
    if logs:
        st.table(
            [
                {"Record": l[0], "Action": l[1], "Reviewer": l[2], "Reason": l[3], "Time": l[4]}
                for l in logs
            ]
        )
    else:
        st.info("No actions logged yet.")
    st.stop()

if not pending:
    st.success("Queue is empty — nothing left to review.")
    st.stop()

record = next(r for r in MOCK_RECORDS if r["record_id"] == st.session_state["selected_record"])

st.subheader(f"Record {record['record_id']} — {record['discrepancy_type']}")
st.caption(
    f"Status: {record['status']} · Match confidence: {record['match_confidence']} "
    f"· Flagged {record['flagged_hours_ago']}h ago"
)

col1, col2 = st.columns(2)

with col1:
    st.markdown("**Invoice**")
    inv = record["documents"]["invoice"]
    st.write(inv)

with col2:
    st.markdown("**Ledger entry**")
    led = record["documents"]["ledger"]
    if led is None:
        st.error("No matching ledger entry found.")
    else:
        st.write(led)

if record["difference"]:
    st.warning(
        f"₹{record['difference']} difference — exceeds {record['tolerance_pct']}% tolerance"
    )

st.divider()

action_col1, action_col2, action_col3 = st.columns(3)

with action_col1:
    if st.button("Accept", use_container_width=True):
        log_action(record["record_id"], "ACCEPT", user["username"])
        st.session_state["record_status"][record["record_id"]] = "ACCEPTED"
        st.rerun()

with action_col2:
    if st.button("Reject", use_container_width=True):
        reason = st.session_state.get("reject_reason", "")
        log_action(record["record_id"], "REJECT", user["username"], reason=reason)
        st.session_state["record_status"][record["record_id"]] = "REJECTED"
        st.rerun()

with action_col3:
    if st.button("Correct", use_container_width=True):
        st.session_state["show_correct_form"] = True

if st.session_state.get("show_correct_form"):
    with st.form("correct_form"):
        field = st.text_input("Field to correct", value=record.get("mismatch_field", ""))
        value = st.text_input("Corrected value")
        confirmed = st.form_submit_button("Save correction")
    if confirmed:
        log_action(
            record["record_id"], "CORRECT", user["username"],
            corrected_field=field, corrected_value=value,
        )
        st.session_state["record_status"][record["record_id"]] = "CORRECTED"
        st.session_state["show_correct_form"] = False
        st.rerun()
