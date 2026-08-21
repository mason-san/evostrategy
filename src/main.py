import csv
from dataclasses import dataclass

from src.report import generate_report


# =========================================================
# RISK THRESHOLDS
# =========================================================

HIGH_RISK_THRESHOLD = 20000
MEDIUM_RISK_THRESHOLD = 10000


@dataclass(frozen=True)
class DecisionRules:
    """Configurable thresholds used by the EvoStrategy decision engine."""

    high_exposure_threshold: int = HIGH_RISK_THRESHOLD
    medium_exposure_threshold: int = MEDIUM_RISK_THRESHOLD
    multiple_pending_invoice_count: int = 2
    high_average_invoice_threshold: int = MEDIUM_RISK_THRESHOLD

    def __post_init__(self):
        """Prevent rule combinations that would make risk bands ambiguous."""

        if self.medium_exposure_threshold > self.high_exposure_threshold:
            raise ValueError(
                "Medium exposure threshold cannot exceed the high exposure threshold."
            )

        if self.multiple_pending_invoice_count < 1:
            raise ValueError(
                "Multiple pending invoice count must be at least 1."
            )

        if self.high_average_invoice_threshold < 0:
            raise ValueError(
                "High average invoice threshold cannot be negative."
            )


DEFAULT_DECISION_RULES = DecisionRules()


# =========================================================
# INVOICE ANALYSIS
# =========================================================

def analyze_invoices(rules=DEFAULT_DECISION_RULES):
    """Analyze invoices using the supplied business decision rules."""

    pending_total = 0
    pending_invoice_count = 0

    vendor_totals = {}
    vendor_invoice_counts = {}

    invoices = []

    # ---------------------------------------------------------
    # READ INVOICE DATA
    # ---------------------------------------------------------

    with open("data/invoice.csv", "r") as file:

        reader = csv.DictReader(file)

        for invoice in reader:

            amount = int(invoice["amount"])

            invoice_data = {
                "invoice_id": invoice["invoice_id"],
                "vendor": invoice["vendor"],
                "amount": amount,
                "status": invoice["status"].strip()
            }

            invoices.append(invoice_data)

            # -------------------------------------------------
            # PENDING INVOICES
            # -------------------------------------------------

            if invoice_data["status"].lower() == "pending":

                pending_total += amount
                pending_invoice_count += 1

                vendor = invoice_data["vendor"]

                # Vendor total exposure
                if vendor not in vendor_totals:
                    vendor_totals[vendor] = 0

                vendor_totals[vendor] += amount

                # Vendor invoice count
                if vendor not in vendor_invoice_counts:
                    vendor_invoice_counts[vendor] = 0

                vendor_invoice_counts[vendor] += 1

    # ---------------------------------------------------------
    # PRINT BASIC ANALYSIS
    # ---------------------------------------------------------

    print("Total pending invoice amount:", pending_total)

    print("Vendor pending totals:")

    for vendor, total in vendor_totals.items():
        print(vendor, ":", total)

    print("Vendor invoice counts:")

    for vendor, count in vendor_invoice_counts.items():
        print(
            vendor,
            ":",
            count,
            "pending invoices"
        )

    # =========================================================
    # NO PENDING INVOICES
    # =========================================================

    if not vendor_totals:

        return {
            "vendor": None,
            "pending_amount": 0,
            "total_pending": 0,
            "pending_invoice_count": 0,

            "decision_score": 0,

            "risk_level": "LOW",

            "recommendation":
                "Continue normal monitoring.",

            "average_pending": 0,

            "risk_distribution": {
                "LOW": len(invoices),
                "MEDIUM": 0,
                "HIGH": 0
            },

            "vendor_totals": {},

            "vendor_invoice_counts": {},

            "invoices": invoices,

            "decision_factors": {
                "exposure_points": 0,
                "concentration_points": 0,
                "average_points": 0
            }
        }

    # =========================================================
    # FIND HIGHEST EXPOSURE VENDOR
    # =========================================================

    highest_vendor = max(
        vendor_totals,
        key=vendor_totals.get
    )

    highest_vendor_amount = vendor_totals[
        highest_vendor
    ]

    highest_vendor_invoice_count = (
        vendor_invoice_counts[
            highest_vendor
        ]
    )

    average_pending = (
        highest_vendor_amount
        / highest_vendor_invoice_count
    )

    print(
        "Highest pending vendor:",
        highest_vendor
    )

    print(
        "Pending amount:",
        highest_vendor_amount
    )

    print(
        "Pending invoices:",
        highest_vendor_invoice_count
    )

    print(
        "Average pending per invoice:",
        average_pending
    )

    # =========================================================
    # DECISION SCORE
    # =========================================================

    exposure_points = 0
    concentration_points = 0
    average_points = 0

    # ---------------------------------------------------------
    # EXPOSURE SCORE
    #
    # >= 20,000  -> 50 points
    # >= 10,000  -> 30 points
    # < 10,000   -> 0 points
    # ---------------------------------------------------------

    if highest_vendor_amount >= rules.high_exposure_threshold:

        exposure_points = 50

    elif highest_vendor_amount >= rules.medium_exposure_threshold:

        exposure_points = 30

    # ---------------------------------------------------------
    # CONCENTRATION SCORE
    # ---------------------------------------------------------

    if (
        highest_vendor_invoice_count
        >= rules.multiple_pending_invoice_count
    ):

        concentration_points = 20

    # ---------------------------------------------------------
    # AVERAGE INVOICE SCORE
    # ---------------------------------------------------------

    if average_pending >= rules.high_average_invoice_threshold:

        average_points = 30

    # ---------------------------------------------------------
    # TOTAL DECISION SCORE
    # ---------------------------------------------------------

    decision_score = (
        exposure_points
        + concentration_points
        + average_points
    )

    print(
        "Decision score:",
        decision_score,
        "/ 100"
    )

    # =========================================================
    # OVERALL RISK
    # =========================================================

    if decision_score >= 80:

        risk_level = "HIGH"

    elif decision_score >= 50:

        risk_level = "MEDIUM"

    else:

        risk_level = "LOW"

    # =========================================================
    # RECOMMENDATION
    # =========================================================

    if risk_level == "HIGH":

        recommendation = (
            "Review payment with this vendor immediately."
        )

    elif risk_level == "MEDIUM":

        recommendation = (
        "Schedule a payment review."
        )
        
    else:

        recommendation = (
            "Continue normal monitoring."
        )

    # =========================================================
    # RISK DISTRIBUTION
    #
    # Risk is assigned using vendor's TOTAL pending exposure.
    # This keeps the dashboard and decision engine consistent.
    # =========================================================

    risk_distribution = {
        "LOW": 0,
        "MEDIUM": 0,
        "HIGH": 0
    }

    for invoice in invoices:

        # Paid / non-pending invoices are LOW risk
        if invoice["status"].lower() != "pending":

            risk_distribution["LOW"] += 1

            continue

        vendor = invoice["vendor"]

        vendor_exposure = vendor_totals.get(
            vendor,
            0
        )

        if vendor_exposure >= rules.high_exposure_threshold:

            risk_distribution["HIGH"] += 1

        elif vendor_exposure >= rules.medium_exposure_threshold:

            risk_distribution["MEDIUM"] += 1

        else:

            risk_distribution["LOW"] += 1

    # =========================================================
    # PRINT FINAL DECISION
    # =========================================================

    print(
        "Risk level:",
        risk_level
    )

    print(
        "Recommendation:",
        recommendation
    )

    if risk_level == "HIGH":

        print(
            "STRATEGIC DECISION: "
            "URGENT PAYMENT REVIEW"
        )

    elif risk_level == "MEDIUM":

        print(
            "STRATEGIC DECISION: "
            "PRIORITY PAYMENT REVIEW"
        )

    else:

        print(
            "STRATEGIC DECISION: "
            "NORMAL MONITORING"
        )

    # =========================================================
    # FINAL RESULT
    # =========================================================

    return {

        "vendor":
            highest_vendor,

        "pending_amount":
            highest_vendor_amount,

        "total_pending":
            pending_total,

        "pending_invoice_count":
            pending_invoice_count,

        "decision_score":
            decision_score,

        "risk_level":
            risk_level,

        "recommendation":
            recommendation,

        "average_pending":
            average_pending,

        "risk_distribution":
            risk_distribution,

        "vendor_totals":
            vendor_totals,

        "vendor_invoice_counts":
            vendor_invoice_counts,

        "invoices":
            invoices,

        "decision_factors": {

            "exposure_points":
                exposure_points,

            "concentration_points":
                concentration_points,

            "average_points":
                average_points
        }
    }


# =========================================================
# KPI GENERATION
# =========================================================

def generate_kpis(result):

    return {

        "total_pending_amount":
            result["total_pending"],

        "pending_invoice_count":
            result["pending_invoice_count"],

        "highest_risk_vendor":
            result["vendor"],

        "highest_vendor_pending_amount":
            result["pending_amount"],

        "risk_level":
            result["risk_level"],

        # FIX:
        # Some unit tests provide a minimal result dictionary
        # without decision_score.
        "decision_score":
            result.get("decision_score", 0)
    }


# =========================================================
# RISK DISTRIBUTION HELPER
# =========================================================

def generate_risk_distribution(risk_data):

    return {

        "LOW":
            risk_data.count("LOW"),

        "MEDIUM":
            risk_data.count("MEDIUM"),

        "HIGH":
            risk_data.count("HIGH")
    }


# =========================================================
# MANAGEMENT INTELLIGENCE
# =========================================================

def generate_intelligence(result):
    """
    Generate management-level insights from the
    existing EvoStrategy decision results.
    """

    vendor = result["vendor"]

    pending_amount = result["pending_amount"]

    total_pending = result["total_pending"]

    invoice_count = (
        result["pending_invoice_count"]
    )

    risk_level = result["risk_level"]

    decision_score = result["decision_score"]

    insights = []

    # =========================================================
    # INSIGHT 1 — OVERALL EXPOSURE
    # =========================================================

    if total_pending >= 50000:

        insights.append(
            f"High overall payment exposure detected: "
            f"₹{total_pending:,.0f} remains pending."
        )

    elif total_pending >= 25000:

        insights.append(
            f"Moderate payment exposure detected: "
            f"₹{total_pending:,.0f} remains pending."
        )

    else:

        insights.append(
            f"Overall pending exposure is relatively low at "
            f"₹{total_pending:,.0f}."
        )

    # =========================================================
    # INSIGHT 2 — VENDOR CONCENTRATION
    # =========================================================

    if vendor and total_pending > 0:

        vendor_share = (
            pending_amount
            / total_pending
        ) * 100

        if vendor_share >= 40:

            insights.append(
                f"{vendor} represents "
                f"{vendor_share:.1f}% of total pending "
                f"exposure, indicating significant "
                f"vendor concentration."
            )

        else:

            insights.append(
                f"{vendor} represents "
                f"{vendor_share:.1f}% of total pending "
                f"exposure."
            )

    # =========================================================
    # INSIGHT 3 — RISK
    # =========================================================

    if risk_level == "HIGH":

        insights.append(
            f"The portfolio is classified as HIGH risk "
            f"with a decision score of "
            f"{decision_score}/100."
        )

    elif risk_level == "MEDIUM":

        insights.append(
            f"The portfolio is classified as MEDIUM risk "
            f"with a decision score of "
            f"{decision_score}/100."
        )

    else:

        insights.append(
            f"The portfolio is classified as LOW risk "
            f"with a decision score of "
            f"{decision_score}/100."
        )

    # =========================================================
    # INSIGHT 4 — PAYMENT PRIORITY
    # =========================================================

    if vendor:

        if risk_level == "HIGH":

            insights.append(
                f"Management should prioritize payment "
                f"review for {vendor}."
            )

        elif risk_level == "MEDIUM":

            insights.append(
                f"Management should schedule a payment "
                f"review for {vendor}."
            )

        else:

            insights.append(
                f"{vendor} can remain under normal "
                f"payment monitoring."
            )

    # =========================================================
    # RETURN INTELLIGENCE
    # =========================================================

    return {

        "insights":
            insights,

        "vendor_share_percent":
            round(
                (
                    pending_amount
                    / total_pending
                ) * 100,
                1
            )
            if total_pending > 0
            else 0,

        "priority_vendor":
            vendor,

        "priority_level":
            risk_level,

        "decision_score":
            decision_score,

        "pending_invoice_count":
            invoice_count
    }


# =========================================================
# MAIN EXECUTION
# =========================================================

if __name__ == "__main__":

    result = analyze_invoices()

    generate_report(result)
