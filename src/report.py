def generate_report(result):

    print()
    print("================================")


def build_management_report(
    result,
    rules,
    intelligence,
    priority_queue,
    scenario_result=None,
    scenario_rules=None,
):
    """Build a downloadable Markdown management summary."""

    lines = [
        "# EvoStrategy Management Report",
        "",
        "## Executive decision",
        f"- **Decision score:** {result['decision_score']} / 100",
        f"- **Risk level:** {result['risk_level']}",
        f"- **Priority vendor:** {result['vendor'] or 'None'}",
        f"- **Total pending exposure:** ₹{result['total_pending']:,.0f}",
        f"- **Recommendation:** {result['recommendation']}",
        "",
        "## Active decision rules",
        f"- High vendor exposure: ₹{rules.high_exposure_threshold:,.0f}",
        f"- Medium vendor exposure: ₹{rules.medium_exposure_threshold:,.0f}",
        f"- Multiple pending invoices: {rules.multiple_pending_invoice_count}+",
        f"- High average invoice value: ₹{rules.high_average_invoice_threshold:,.0f}",
        "",
        "## Management insights",
    ]

    lines.extend(f"- {insight}" for insight in intelligence["insights"])

    if scenario_result is not None and scenario_rules is not None:
        score_change = (
            scenario_result["decision_score"]
            - result["decision_score"]
        )
        lines.extend(
            [
                "",
                "## What-if policy scenario",
                f"- Proposed decision score: {scenario_result['decision_score']} / 100 "
                f"({score_change:+d} points)",
                f"- Proposed risk level: {scenario_result['risk_level']}",
                f"- Proposed high vendor exposure: "
                f"₹{scenario_rules.high_exposure_threshold:,.0f}",
                f"- Proposed medium vendor exposure: "
                f"₹{scenario_rules.medium_exposure_threshold:,.0f}",
                f"- Proposed multiple pending invoices: "
                f"{scenario_rules.multiple_pending_invoice_count}+",
                f"- Proposed high average invoice value: "
                f"₹{scenario_rules.high_average_invoice_threshold:,.0f}",
            ]
        )

    lines.extend(["", "## Vendor payment-priority queue"])

    if priority_queue.empty:
        lines.append("- No pending vendors are available for prioritization.")
    else:
        for item in priority_queue.to_dict("records"):
            lines.append(
                f"{item['Priority']}. **{item['Vendor']}** — "
                f"{item['Risk level']} risk; "
                f"₹{item['Pending exposure']:,.0f} pending; "
                f"{item['Recommended action']}. "
                f"{item['Reason']}"
            )

    return "\n".join(lines) + "\n"
    print("        EVOSTRATEGY REPORT")
    print("================================")

    print("Vendor:", result["vendor"])

    print(
        "Pending Amount:",
        result["pending_amount"]
    )

    print(
        "Total Pending Amount:",
        result["total_pending"]
    )

    print(
        "Pending Invoices:",
        result["pending_invoice_count"]
    )

    print(
        "Average Pending Invoice:",
        round(result["average_pending"], 2)
    )

    print(
        "Decision Score:",
        result["decision_score"],
        "/ 100"
    )

    print(
        "Risk Level:",
        result["risk_level"]
    )

    print(
        "Recommendation:",
        result["recommendation"]
    )

    if result["risk_level"] == "HIGH":

        print(
            "Priority: IMMEDIATE ATTENTION"
        )

    elif result["risk_level"] == "MEDIUM":

        print(
            "Priority: HIGH"
        )

    else:

        print(
            "Priority: NORMAL"
        )

    print("================================")
