# EvoStrategy — Guide for Finance Reviewers

EvoStrategy reads your business documents, checks them against each other, asks
you about anything that does not add up, and only then builds reports and
forecasts. Nothing leaves your computer.

## 1. Starting

Open **http://localhost:8000** (ask whoever installed it if that does not load).

- First time: click **Get started**, then either drop in your files or choose
  **Use a sample company's invoices, payments and ledger** to explore.
- Accepted files: PDF, scanned images (PNG, JPG, TIFF), Word (DOCX), and
  spreadsheets (CSV, XLSX — one row per entry, first row = column names).
- Up to 50 MB per file. Processing shows live progress; scanned pages take
  roughly 5 seconds each on a laptop, spreadsheets are near-instant.

> Loading the sample data starts a fresh workspace. Your previous workspace is
> not deleted — it is kept in `backups/` next to the database and can be
> restored by whoever runs the system.

Type your **name in the Reviewer box** (bottom left) before reviewing. Every
decision is recorded under that name.

## 2. The screens

| Screen | What it is for |
|---|---|
| Overview | Totals, revenue vs expenses, how many records passed the checks, what needs you |
| Review queue | Every discrepancy the system could not settle by itself |
| Documents | Every extracted record, with its source file and confidence |
| Audit log | Every decision ever made, who made it, when, and why; plus a tamper check |
| Analytics | Monthly or quarterly P&L, categories, vendor spend, budget use |
| Forecast | Next 3–12 months, with an 85% range and how accurate the method has been |
| Cash runway | How long cash lasts at the current verified trend |
| What-if | Try a decision (prices, people, vendors) and see its effect before making it |
| Evaluation | How well the system itself performs, measured |
| Settings | Budgets, cash on hand and headcount — things documents cannot tell |

## 3. Reviewing a case

Open **Review queue**. Each case says what is wrong in plain words, for example
*"Amounts differ by 4.5% (2,847.18 vs 2,724.57), beyond tolerance."*

Click a case to see **both source documents side by side**: the original page
image and the values read from it, with the compared fields highlighted.

Then choose one decision:

| Decision | When to use it | What happens |
|---|---|---|
| **Accept** | The records are fine as they are (e.g. a known re-issue) | The transaction enters the reports |
| **Correct** | One value is wrong and you know the right one | Pick the field (amount, date, category, counterparty), type the correct value and a reason. Reports use your value; the original stays visible |
| **Reject** | The records should not be trusted at all | The transaction is quarantined and kept out of all reports |

A reason is required for Correct and Reject. Decisions are final for that case
and are never overwritten when documents are re-processed.

### What the case types mean

| Case | Meaning | Usual check |
|---|---|---|
| Numerical mismatch | Two documents for the same order disagree by more than 2% | Open both; which figure is printed on the invoice? |
| Missing document | An invoice is not in the ledger, or a payment has no invoice | Was it booked under a different reference? |
| Duplicate entry | Two invoices carry the same order number | Re-issue, correction, or double entry? |
| Entity alias | The company names look related but not identical | Same supplier under two names? |
| Low-confidence extraction | The scan was hard to read for an amount, date or reference | Compare the value with the page image |
| Ambiguous link | Documents partly agree but not enough to link automatically | Do they belong together? |

Differences within tolerance (amounts within 2%, ledger dates within 7 days) are
**auto-resolved** and listed, but do not need you.

## 4. Reading the reports

Every chart states what it is built from, for example:

> ● Built from 270 verified records (280 source documents) · 2011-01-05 → 2013-09-30 · 11 records excluded until reviewed

- **Only verified records are used.** Anything waiting for review or rejected is
  left out and counted, so you always know what is missing.
- If the data is the **sample company**, an orange *Demo data* note says so.
- Budgets: if you set none, each category's budget is last year's spend for the
  same months plus 5%. Set real annual budgets in **Settings**.

### Forecast

The forecast combines two methods (a straight-line trend and ARIMA, which also
learns seasonal patterns). The shaded band is the range the next months should
fall in 85% of the time. *Model accuracy* shows how wrong the method was when
we hid the last months and asked it to predict them (MAPE = average % error;
the project's goal is 15% or less). If there is not enough history, it says so
instead of guessing.

### Cash runway

Enter your current bank balance in **Settings** once. The system rebuilds the
month-end cash from verified cash flow and projects it forward with an 85%
range. If you are making more than you spend, it says *not burning cash*.

### What-if

Move the sliders; results update immediately. Scenarios **never change stored
records**. The page shows the effect on revenue, expenses, profit, the budget
for the period and your cash/runway, and lists the assumptions used (for
example, the cost of one person = recent payroll ÷ headcount).

## 5. Good practice

- Review the queue before reading the reports — the reports tell you how many
  records are still waiting.
- Prefer **Correct** over **Accept** when one figure is wrong; it keeps the
  original and your fix side by side in the audit log.
- Use the reason box for what you checked ("matched against bank statement
  12 Mar"), not just "ok". Auditors read it.
- The **Audit log** shows a green *Tamper check passed* line. If it ever shows
  a failure, an entry was changed outside the application — report it.
