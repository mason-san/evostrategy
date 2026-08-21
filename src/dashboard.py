"""Streamlit user interface for the EvoStrategy invoice analysis."""

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from src.main import (
    DEFAULT_DECISION_RULES,
    DecisionRules,
    analyze_invoices,
    generate_intelligence,
)
from src.report import build_management_report


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVOICE_FILE = PROJECT_ROOT / "data" / "invoice.csv"

RISK_ORDER = ["LOW", "MEDIUM", "HIGH"]


# ============================================================
# DATA LOADING
# ============================================================

def load_invoices():
    """Load and validate the invoice dataset used by the dashboard."""

    invoices = pd.read_csv(INVOICE_FILE)

    required_columns = {
        "invoice_id",
        "vendor",
        "amount",
        "status",
    }

    missing_columns = required_columns - set(invoices.columns)

    if missing_columns:
        missing = ", ".join(sorted(missing_columns))

        raise ValueError(
            "Invoice data is missing required column(s): "
            f"{missing}"
        )

    invoices = invoices.copy()

    invoices["invoice_id"] = (
        invoices["invoice_id"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    invoices["vendor"] = (
        invoices["vendor"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    invoices["amount"] = pd.to_numeric(
        invoices["amount"],
        errors="raise",
    )

    invoices["status"] = (
        invoices["status"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    invoices["status_normalized"] = (
        invoices["status"]
        .str.casefold()
    )

    invoices["status_display"] = (
        invoices["status"]
        .str.title()
    )

    return invoices


# ============================================================
# DASHBOARD HELPERS
# ============================================================

def priority_for(risk_level):
    """Return the management priority for an overall risk level."""

    priorities = {
        "HIGH": "Immediate attention",
        "MEDIUM": "High priority",
        "LOW": "Normal monitoring",
    }

    return priorities.get(
        risk_level,
        "Normal monitoring",
    )


def calculate_invoice_risk(row, vendor_totals, rules):
    """
    Match src.main invoice-risk logic.

    Risk is based on each vendor's total pending exposure,
    not an individual invoice amount.
    """

    if row["status_normalized"] != "pending":
        return "LOW"

    vendor_exposure = vendor_totals.get(
        row["vendor"],
        0,
    )

    if vendor_exposure >= rules.high_exposure_threshold:
        return "HIGH"

    if vendor_exposure >= rules.medium_exposure_threshold:
        return "MEDIUM"

    return "LOW"


def filtered_vendor_summary(filtered_pending):
    """Return pending-exposure information for the current filters."""

    if filtered_pending.empty:
        return pd.Series(dtype="float64"), "None", 0

    totals = (
        filtered_pending
        .groupby("vendor")["amount"]
        .sum()
        .sort_values(ascending=False)
    )

    return totals, totals.index[0], totals.iloc[0]


def build_vendor_priority_queue(pending_invoices, rules):
    """Rank vendors using the active exposure rules and explain each action."""

    columns = [
        "Priority",
        "Vendor",
        "Risk level",
        "Pending exposure",
        "Pending invoices",
        "Recommended action",
        "Reason",
    ]

    if pending_invoices.empty:
        return pd.DataFrame(columns=columns)

    queue = (
        pending_invoices
        .groupby("vendor")
        .agg(
            **{
                "Pending exposure": ("amount", "sum"),
                "Pending invoices": ("invoice_id", "count"),
            }
        )
        .reset_index()
        .rename(columns={"vendor": "Vendor"})
    )

    def vendor_risk(exposure):
        if exposure >= rules.high_exposure_threshold:
            return "HIGH"

        if exposure >= rules.medium_exposure_threshold:
            return "MEDIUM"

        return "LOW"

    queue["Risk level"] = queue["Pending exposure"].apply(vendor_risk)

    action_by_risk = {
        "HIGH": "Review payment immediately",
        "MEDIUM": "Schedule a payment review",
        "LOW": "Continue normal monitoring",
    }
    queue["Recommended action"] = queue["Risk level"].map(action_by_risk)

    def reason_for_vendor(row):
        exposure = row["Pending exposure"]
        invoice_count = row["Pending invoices"]

        if row["Risk level"] == "HIGH":
            threshold = rules.high_exposure_threshold
            level = "high"
        elif row["Risk level"] == "MEDIUM":
            threshold = rules.medium_exposure_threshold
            level = "medium"
        else:
            return (
                f"₹{exposure:,.0f} across {invoice_count} pending invoice(s) "
                f"is below the medium exposure threshold."
            )

        return (
            f"₹{exposure:,.0f} across {invoice_count} pending invoice(s) "
            f"meets the ₹{threshold:,.0f} {level}-exposure threshold."
        )

    queue["Reason"] = queue.apply(reason_for_vendor, axis=1)

    risk_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    queue["_risk_rank"] = queue["Risk level"].map(risk_rank)
    queue = queue.sort_values(
        ["_risk_rank", "Pending exposure"],
        ascending=[True, False],
    ).reset_index(drop=True)
    queue["Priority"] = queue.index + 1

    return queue[columns]


def message_for_risk(risk_level, message):
    """Display a Streamlit status message based on risk level."""

    if risk_level == "HIGH":
        st.error(message)

    elif risk_level == "MEDIUM":
        st.warning(message)

    else:
        st.success(message)


# ============================================================
# MAIN DASHBOARD
# ============================================================

def run_dashboard():
    """Run the EvoStrategy Streamlit dashboard."""

    st.set_page_config(
        page_title="EvoStrategy",
        page_icon="📊",
        layout="wide",
    )

    st.title("EvoStrategy")
    st.caption(
        "Invoice risk and payment-priority dashboard"
    )

    # --------------------------------------------------------
    # LOAD INVOICE DATA
    # --------------------------------------------------------

    try:
        invoices = load_invoices()

    except (
        FileNotFoundError,
        ValueError,
        KeyError,
        OSError,
        pd.errors.ParserError,
    ) as error:
        st.error(f"Unable to load invoice data: {error}")
        st.stop()

    # ========================================================
    # SIDEBAR FILTERS
    # ========================================================

    st.sidebar.title("Dashboard Filters")

    st.sidebar.caption(
        "Use the filters below to explore invoice data."
    )

    vendors = sorted(
        vendor
        for vendor in invoices["vendor"].unique().tolist()
        if vendor
    )

    selected_vendor = st.sidebar.selectbox(
        "Vendor",
        ["All Vendors"] + vendors,
    )

    statuses = sorted(
        status
        for status in invoices["status_display"].unique().tolist()
        if status
    )

    selected_status = st.sidebar.selectbox(
        "Invoice Status",
        ["All Statuses"] + statuses,
    )

    selected_risk = st.sidebar.selectbox(
        "Risk Level",
        ["All Risk Levels"] + RISK_ORDER,
    )

    st.sidebar.divider()

    st.sidebar.subheader("Decision rules")
    st.sidebar.caption(
        "Adjust thresholds to model the current business policy."
    )

    high_exposure_threshold = int(
        st.sidebar.number_input(
            "High vendor exposure threshold (₹)",
            min_value=1_000,
            value=DEFAULT_DECISION_RULES.high_exposure_threshold,
            step=1_000,
        )
    )

    medium_exposure_threshold = int(
        st.sidebar.number_input(
            "Medium vendor exposure threshold (₹)",
            min_value=0,
            max_value=high_exposure_threshold,
            value=min(
                DEFAULT_DECISION_RULES.medium_exposure_threshold,
                high_exposure_threshold,
            ),
            step=1_000,
        )
    )

    multiple_pending_invoice_count = int(
        st.sidebar.number_input(
            "Multiple pending-invoice threshold",
            min_value=1,
            value=DEFAULT_DECISION_RULES.multiple_pending_invoice_count,
            step=1,
        )
    )

    high_average_invoice_threshold = int(
        st.sidebar.number_input(
            "High average invoice threshold (₹)",
            min_value=0,
            value=DEFAULT_DECISION_RULES.high_average_invoice_threshold,
            step=1_000,
        )
    )

    rules = DecisionRules(
        high_exposure_threshold=high_exposure_threshold,
        medium_exposure_threshold=medium_exposure_threshold,
        multiple_pending_invoice_count=multiple_pending_invoice_count,
        high_average_invoice_threshold=high_average_invoice_threshold,
    )

    st.sidebar.info(
        "The overall decision score and strategic risk "
        "assessment are generated from the complete invoice "
        "portfolio by EvoStrategy's core analysis engine."
    )

    try:
        result = analyze_invoices(rules)
        intelligence = generate_intelligence(result)

    except (
        FileNotFoundError,
        ValueError,
        KeyError,
        OSError,
        pd.errors.ParserError,
    ) as error:
        st.error(f"Unable to analyze invoice data: {error}")
        st.stop()

    # --------------------------------------------------------
    # ASSIGN EACH INVOICE A RISK LEVEL
    #
    # This mirrors src.main using the currently selected rules.
    # --------------------------------------------------------

    pending_invoices = invoices[
        invoices["status_normalized"] == "pending"
    ].copy()

    vendor_totals = (
        pending_invoices
        .groupby("vendor")["amount"]
        .sum()
        .to_dict()
    )

    invoices["risk_level"] = invoices.apply(
        lambda row: calculate_invoice_risk(
            row,
            vendor_totals,
            rules,
        ),
        axis=1,
    )

    # ========================================================
    # APPLY FILTERS
    # ========================================================

    filtered_invoices = invoices.copy()

    if selected_vendor != "All Vendors":
        filtered_invoices = filtered_invoices[
            filtered_invoices["vendor"] == selected_vendor
        ]

    if selected_status != "All Statuses":
        filtered_invoices = filtered_invoices[
            filtered_invoices["status_display"] == selected_status
        ]

    if selected_risk != "All Risk Levels":
        filtered_invoices = filtered_invoices[
            filtered_invoices["risk_level"] == selected_risk
        ]

    filtered_pending = filtered_invoices[
        filtered_invoices["status_normalized"] == "pending"
    ].copy()

    (
        filtered_vendor_totals,
        filtered_highest_vendor,
        filtered_highest_amount,
    ) = filtered_vendor_summary(filtered_pending)

    filtered_total_pending = filtered_pending["amount"].sum()
    filtered_pending_count = len(filtered_pending)

    # ========================================================
    # KEY PERFORMANCE INDICATORS
    # ========================================================

    st.subheader("Key performance indicators")
    st.caption("The first three KPIs reflect the current filters.")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Total pending amount",
        f"₹{filtered_total_pending:,.0f}",
    )

    col2.metric(
        "Pending invoices",
        filtered_pending_count,
    )

    col3.metric(
        "Highest pending vendor",
        filtered_highest_vendor,
        help=(
            "Highest pending vendor within the currently "
            "filtered invoice data."
        ),
    )

    col4.metric(
        "Decision score",
        f"{result['decision_score']} / 100",
        help=(
            "Calculated by the core engine from the complete "
            "invoice dataset."
        ),
    )

    # ========================================================
    # RISK ASSESSMENT
    # ========================================================

    st.divider()

    risk_col, recommendation_col = st.columns([1, 2])

    with risk_col:
        st.subheader("Risk assessment")

        st.metric(
            "Risk level",
            result["risk_level"],
        )

        st.write(
            f"**Management priority:** "
            f"{priority_for(result['risk_level'])}"
        )

        st.write(
            f"**Average pending invoice:** "
            f"₹{result['average_pending']:,.0f}"
        )

        st.write(
            f"**Highest vendor pending amount:** "
            f"₹{result['pending_amount']:,.0f}"
        )

    with recommendation_col:
        st.subheader("Strategic recommendation")

        message_for_risk(
            result["risk_level"],
            result["recommendation"],
        )

        st.caption(
            "This assessment is based on the complete invoice "
            "portfolio, not the selected dashboard filters."
        )

    # ========================================================
    # WHY EVOSTRATEGY MADE THIS DECISION
    # ========================================================

    st.divider()

    st.subheader("Why EvoStrategy made this decision")

    st.caption(
        "The recommendation is generated from the overall "
        "invoice portfolio analysis performed by the "
        "EvoStrategy decision engine."
    )

    explanation_col1, explanation_col2 = st.columns(2)

    with explanation_col1:
        st.markdown("### Decision factors")

        st.write(
            f"• **Pending exposure:** "
            f"₹{result['total_pending']:,.0f}"
        )

        st.write(
            f"• **Pending invoices:** "
            f"{result['pending_invoice_count']}"
        )

        st.write(
            f"• **Average pending invoice:** "
            f"₹{result['average_pending']:,.0f}"
        )

    with explanation_col2:
        st.markdown("### Decision outcome")

        st.write(
            f"• **Priority vendor:** "
            f"{result['vendor'] or 'None'}"
        )

        st.write(
            f"• **Overall risk:** "
            f"{result['risk_level']}"
        )

        st.write(
            f"• **Recommended action:** "
            f"{result['recommendation']}"
        )

    # ========================================================
    # AI-POWERED MANAGEMENT INSIGHTS
    # ========================================================

    st.divider()
    st.subheader("AI-powered management insights")
    st.caption(
        "EvoStrategy translates the decision-engine output "
        "into concise management actions."
    )

    insight_col1, insight_col2 = st.columns([2, 1])

    with insight_col1:
        for insight in intelligence["insights"]:
            st.info(f"💡 {insight}")

    with insight_col2:
        st.metric(
            "Priority vendor",
            intelligence["priority_vendor"] or "None",
        )
        st.metric(
            "Vendor exposure share",
            f"{intelligence['vendor_share_percent']:.1f}%",
        )
        st.metric(
            "Priority level",
            intelligence["priority_level"],
        )

    # ========================================================
    # RISK DRIVERS
    # ========================================================

    st.divider()
    st.subheader("Risk drivers")
    st.caption(
        "These rule-based factors make up the decision score."
    )

    factors = result["decision_factors"]
    driver_data = pd.DataFrame(
        {
            "Risk driver": [
                "Highest vendor exposure",
                "Multiple pending invoices",
                "Average pending invoice value",
            ],
            "Points": [
                factors["exposure_points"],
                factors["concentration_points"],
                factors["average_points"],
            ],
            "Maximum": [50, 20, 30],
        }
    )
    driver_data["Contribution"] = (
        driver_data["Points"].astype(str)
        + " / "
        + driver_data["Maximum"].astype(str)
    )

    scenario_result = None
    scenario_rules = None

    with st.expander("Active decision rules"):
        active_rules = pd.DataFrame(
            {
                "Rule": [
                    "High vendor exposure",
                    "Medium vendor exposure",
                    "Multiple pending invoices",
                    "High average invoice value",
                ],
                "Current setting": [
                    f"₹{rules.high_exposure_threshold:,.0f}",
                    f"₹{rules.medium_exposure_threshold:,.0f}",
                    f"{rules.multiple_pending_invoice_count}+ invoices",
                    f"₹{rules.high_average_invoice_threshold:,.0f}",
                ],
            }
        )

        st.dataframe(
            active_rules,
            hide_index=True,
            width="stretch",
        )

    with st.expander("What-if policy scenario"):
        st.caption(
            "Test a proposed policy without changing the active dashboard rules."
        )

        scenario_col1, scenario_col2 = st.columns(2)

        with scenario_col1:
            scenario_high_exposure = int(
                st.number_input(
                    "Proposed high exposure threshold (₹)",
                    min_value=1_000,
                    value=rules.high_exposure_threshold,
                    step=1_000,
                    key="scenario_high_exposure",
                )
            )
            scenario_pending_count = int(
                st.number_input(
                    "Proposed multiple pending-invoice threshold",
                    min_value=1,
                    value=rules.multiple_pending_invoice_count,
                    step=1,
                    key="scenario_pending_count",
                )
            )

        with scenario_col2:
            scenario_medium_exposure = int(
                st.number_input(
                    "Proposed medium exposure threshold (₹)",
                    min_value=0,
                    value=rules.medium_exposure_threshold,
                    step=1_000,
                    key="scenario_medium_exposure",
                )
            )
            scenario_average_invoice = int(
                st.number_input(
                    "Proposed high average invoice threshold (₹)",
                    min_value=0,
                    value=rules.high_average_invoice_threshold,
                    step=1_000,
                    key="scenario_average_invoice",
                )
            )

        try:
            scenario_rules = DecisionRules(
                high_exposure_threshold=scenario_high_exposure,
                medium_exposure_threshold=scenario_medium_exposure,
                multiple_pending_invoice_count=scenario_pending_count,
                high_average_invoice_threshold=scenario_average_invoice,
            )
            scenario_result = analyze_invoices(scenario_rules)

        except ValueError as error:
            st.warning(f"Proposed policy needs adjustment: {error}")

        else:
            scenario_comparison = pd.DataFrame(
                {
                    "Measure": [
                        "Decision score",
                        "Risk level",
                        "Priority vendor",
                        "Recommended action",
                    ],
                    "Active policy": [
                        f"{result['decision_score']} / 100",
                        result["risk_level"],
                        result["vendor"] or "None",
                        result["recommendation"],
                    ],
                    "Proposed policy": [
                        f"{scenario_result['decision_score']} / 100",
                        scenario_result["risk_level"],
                        scenario_result["vendor"] or "None",
                        scenario_result["recommendation"],
                    ],
                }
            )

            st.dataframe(
                scenario_comparison,
                hide_index=True,
                width="stretch",
            )

            score_change = (
                scenario_result["decision_score"]
                - result["decision_score"]
            )

            if score_change == 0:
                st.info("The proposed policy produces the same decision score.")
            else:
                st.info(
                    "The proposed policy changes the decision score by "
                    f"{score_change:+d} points."
                )

    st.dataframe(
        driver_data[["Risk driver", "Contribution"]],
        hide_index=True,
        width="stretch",
    )

    # ========================================================
    # DECISION CALCULATION
    # ========================================================

    st.divider()
    st.subheader("Decision calculation")

    calculation_col1, calculation_col2 = st.columns([2, 1])

    with calculation_col1:
        decision_chart = alt.Chart(driver_data).mark_bar().encode(
            x=alt.X(
                "Risk driver:N",
                sort=None,
                title=None,
            ),
            y=alt.Y(
                "Points:Q",
                scale=alt.Scale(domain=[0, 50]),
                title="Decision-score points",
            ),
            tooltip=[
                alt.Tooltip("Risk driver:N", title="Risk driver"),
                alt.Tooltip("Points:Q", title="Points"),
                alt.Tooltip("Maximum:Q", title="Maximum points"),
            ],
        ).properties(height=260)

        st.altair_chart(
            decision_chart,
            width="stretch",
        )

    with calculation_col2:
        st.metric("Decision score", f"{result['decision_score']} / 100")
        st.metric("Risk classification", result["risk_level"])

    # ========================================================
    # RISK DISTRIBUTION
    # ========================================================

    st.divider()
    st.subheader("Risk distribution")
    st.caption("Invoice risk is determined from vendor-level pending exposure.")

    distribution = (
        filtered_invoices["risk_level"]
        .value_counts()
        .reindex(RISK_ORDER, fill_value=0)
        .rename("Invoices")
        .to_frame()
        .reset_index(names="Risk level")
    )

    risk_chart = alt.Chart(distribution).mark_bar().encode(
        x=alt.X(
            "Risk level:N",
            sort=RISK_ORDER,
            title=None,
        ),
        y=alt.Y(
            "Invoices:Q",
            title="Invoice count",
        ),
        color=alt.Color(
            "Risk level:N",
            sort=RISK_ORDER,
            scale=alt.Scale(
                domain=RISK_ORDER,
                range=["#2E8B57", "#F4A261", "#D1495B"],
            ),
            legend=None,
        ),
        tooltip=[
            alt.Tooltip("Risk level:N", title="Risk level"),
            alt.Tooltip("Invoices:Q", title="Invoices"),
        ],
    ).properties(height=260)

    st.altair_chart(risk_chart, width="stretch")

    # ========================================================
    # HIGH-RISK INVOICES
    # ========================================================

    st.divider()
    st.subheader("High-risk invoices")

    high_risk_invoices = filtered_invoices[
        filtered_invoices["risk_level"] == "HIGH"
    ].copy()

    if high_risk_invoices.empty:
        st.info("No high-risk invoices match the current filters.")
    else:
        st.dataframe(
            high_risk_invoices[
                ["invoice_id", "vendor", "amount", "status_display", "risk_level"]
            ].rename(
                columns={
                    "invoice_id": "Invoice ID",
                    "vendor": "Vendor",
                    "amount": "Amount",
                    "status_display": "Status",
                    "risk_level": "Risk level",
                }
            ),
            hide_index=True,
            width="stretch",
            column_config={"Amount": st.column_config.NumberColumn(format="₹%,.0f")},
        )

    # ========================================================
    # VENDOR PAYMENT-PRIORITY QUEUE
    # ========================================================

    st.divider()
    st.subheader("Vendor payment-priority queue")
    st.caption(
        "Ranked from the complete pending portfolio using the active decision rules."
    )

    priority_queue = build_vendor_priority_queue(
        pending_invoices,
        rules,
    )

    if priority_queue.empty:
        st.info("No pending vendors are available for prioritization.")
    else:
        st.dataframe(
            priority_queue,
            hide_index=True,
            width="stretch",
            column_config={
                "Pending exposure": st.column_config.NumberColumn(
                    format="₹%,.0f"
                ),
            },
        )

    st.subheader("Management report")
    st.caption(
        "Download a current summary of the decision, rules, scenario, and priorities."
    )

    management_report = build_management_report(
        result=result,
        rules=rules,
        intelligence=intelligence,
        priority_queue=priority_queue,
        scenario_result=scenario_result,
        scenario_rules=scenario_rules,
    )

    st.download_button(
        "Download management report (Markdown)",
        data=management_report.encode("utf-8"),
        file_name="evostrategy_management_report.md",
        mime="text/markdown",
        width="content",
    )

    # ========================================================
    # VENDOR EXPOSURE ANALYSIS
    # ========================================================

    st.divider()
    st.subheader("Vendor exposure analysis")

    if filtered_vendor_totals.empty:
        st.info("No pending vendor exposure matches the current filters.")
    else:
        vendor_chart, vendor_table = st.columns([2, 1])

        with vendor_chart:
            vendor_exposure = (
                filtered_vendor_totals
                .rename("Pending amount")
                .rename_axis("Vendor")
                .reset_index()
            )

            vendor_exposure_chart = alt.Chart(
                vendor_exposure
            ).mark_bar().encode(
                x=alt.X(
                    "Vendor:N",
                    sort="-y",
                    title=None,
                ),
                y=alt.Y(
                    "Pending amount:Q",
                    title="Pending amount (₹)",
                ),
                tooltip=[
                    alt.Tooltip("Vendor:N", title="Vendor"),
                    alt.Tooltip(
                        "Pending amount:Q",
                        title="Pending amount",
                        format=",.0f",
                    ),
                ],
            ).properties(height=260)

            st.altair_chart(
                vendor_exposure_chart,
                width="stretch",
            )

        with vendor_table:
            st.dataframe(
                filtered_vendor_totals.rename("Pending amount").reset_index().rename(
                    columns={"vendor": "Vendor"}
                ),
                hide_index=True,
                width="stretch",
                column_config={
                    "Pending amount": st.column_config.NumberColumn(format="₹%,.0f")
                },
            )

    # ========================================================
    # INVOICE DETAILS AND EXPORT
    # ========================================================

    st.divider()
    st.subheader("Invoice details")
    st.caption("The table and download reflect the currently selected filters.")

    display_invoices = filtered_invoices[
        ["invoice_id", "vendor", "amount", "status_display", "risk_level"]
    ].rename(
        columns={
            "invoice_id": "Invoice ID",
            "vendor": "Vendor",
            "amount": "Amount",
            "status_display": "Status",
            "risk_level": "Risk level",
        }
    )

    st.dataframe(
        display_invoices,
        hide_index=True,
        width="stretch",
        column_config={"Amount": st.column_config.NumberColumn(format="₹%,.0f")},
    )

    st.subheader("Data export")
    st.download_button(
        "Download filtered invoices (CSV)",
        data=display_invoices.to_csv(index=False).encode("utf-8"),
        file_name="evostrategy_filtered_invoices.csv",
        mime="text/csv",
        width="content",
    )

    # ========================================================
    # FILTER SUMMARY
    # ========================================================

    st.divider()
    st.subheader("Filter summary")
    st.write(
        f"Showing **{len(filtered_invoices)}** of **{len(invoices)}** invoices "
        f"with Vendor: **{selected_vendor}** · Status: **{selected_status}** "
        f"· Risk: **{selected_risk}**."
    )


if __name__ == "__main__":
    run_dashboard()
