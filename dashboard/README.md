# Verification dashboard — starter

Stage 3 of EvoStrategy. Currently runs against mock data in
`mock_data.py`; swap for the real reconciliation registry once
Adham's engine has output (Week 7+).

## Run it locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Opens at `http://localhost:8501`. Log in with:
- `ayushi` / `changeme123` (admin — can also see the audit log)
- `reviewer1` / `changeme123` (reviewer)

Change these passwords before anyone else uses it — see the bottom
of `auth.py` for how to generate a new hash.

## Files

- `app.py` — main dashboard: queue, side-by-side comparison, actions
- `auth.py` — login screen and session handling
- `audit_log.py` — SQLite-backed audit trail
- `mock_data.py` — placeholder records, same shape as the planned
  per-transaction JSON schema

## Push this to the team repo

```bash
git clone <your-team-repo-url>
cd <repo-name>
git checkout -b ayushi/verification-dashboard

# copy these files into a dashboard/ folder in the repo, then:
git add dashboard/
git commit -m "Add verification dashboard skeleton: login, queue, review actions"
git push origin ayushi/verification-dashboard
```

Then open a pull request on GitHub so the team can see it before it
merges into `main`.

## Next steps (matches the Week 5–11 plan)

- Wire real reconciliation registry once available (Week 7)
- Side-by-side viewer polish, discrepancy magnitude display (Week 7)
- Quarantine flow for rejected records with reason capture (Week 10) —
  reason field already logs, just needs a UI prompt before reject
- Usability test with a non-technical reviewer (Week 11)
