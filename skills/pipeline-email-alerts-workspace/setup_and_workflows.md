# PropertyFinder Email Notifications — Setup Guide

---

## 1. Gmail App Password (one-time setup)

You need a **Gmail App Password**, not your regular Gmail password.

1. Go to https://myaccount.google.com/security
2. Enable **2-Step Verification** (required)
3. Go to https://myaccount.google.com/apppasswords
4. Create a new app password → Name: "PropertyFinder Pipeline"
5. Copy the 16-character password (e.g. `abcd efgh ijkl mnop`)

---

## 2. Add GitHub Secrets

In your repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name      | Value                                                      |
|------------------|------------------------------------------------------------|
| `EMAIL_ADDRESS`  | `bader.abdulrahim@gmail.com`                               |
| `SMTP_PASSWORD`  | The 16-char App Password from step 1 (no spaces)           |

The `SMTP_FROM` defaults to `EMAIL_ADDRESS`, so you'll receive mail from yourself — that's fine.

---

## 3. GitHub Actions Workflow Patches

### For `.github/workflows/timing_study.yml`

Add this step **after** your quality gate step (and after any artifact upload):

```yaml
      - name: Send Email Notification
        if: always()
        env:
          RECIPIENT_EMAIL: ${{ secrets.EMAIL_ADDRESS }}
          SMTP_PASSWORD:   ${{ secrets.SMTP_PASSWORD }}
          SMTP_FROM:       ${{ secrets.EMAIL_ADDRESS }}
        run: python scripts/email_notification.py

      - name: Generate Briefing
        if: always()
        run: python scripts/generate_briefing.py

      - name: Upload Briefing
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: pipeline-briefing
          path: briefing/latest.md
```

### For `.github/workflows/daily_scrape.yml`

Same block — paste it after the quality gate step.

---

## 4. Full step example in context

```yaml
      - name: Quality Gate
        run: python scripts/quality_gate.py   # your existing step

      - name: Send Email Notification         # ← ADD THIS
        if: always()
        env:
          RECIPIENT_EMAIL: ${{ secrets.EMAIL_ADDRESS }}
          SMTP_PASSWORD:   ${{ secrets.SMTP_PASSWORD }}
          SMTP_FROM:       ${{ secrets.EMAIL_ADDRESS }}
        run: python scripts/email_notification.py

      - name: Generate Briefing               # ← ADD THIS
        if: always()
        run: python scripts/generate_briefing.py
```

`if: always()` means the email fires whether the quality gate passed or failed. The script itself never raises a non-zero exit code, so it can't block the pipeline.

---

## 5. Local testing

```bash
# Preview email without sending
python scripts/email_notification.py --test

# Generate briefing (writes briefing/latest.md)
python scripts/generate_briefing.py
```

Expected output from `--test`:

```
============================================================
SUBJECT: [TEST MODE] [PropertyFinder] Pipeline Run — ✅ PASS — 2026-06-02
============================================================
Pipeline run completed: 2026-06-02T10:30:00Z

Status:           ✅ PASS
Quality Score:    97.3%
Total Listings:   1,248
New Listings:     14
Removed Listings: 3

Summary:
Pipeline completed successfully with 1248 total listings (14 new). Quality score: 97.3%.

Workflow run: https://github.com/bader1919/pf-pipeline/actions
============================================================
[Test mode] Email NOT sent.
```

---

## 6. History tracking (enables trend diffs in briefing)

The briefing script compares current vs previous run if you archive reports. Add this step to your workflow:

```yaml
      - name: Archive Pipeline Report
        if: always()
        run: |
          mkdir -p data/history
          cp data/latest_report.json "data/history/$(date -u +%Y%m%d_%H%M%S)_report.json"
```

---

## 7. Files to commit to your repo

```
scripts/
  email_notification.py
  generate_briefing.py
briefing/
  .gitkeep            # so the directory exists
data/
  history/
    .gitkeep
```

Add to `.gitignore`:
```
briefing/latest.md    # generated — don't commit
```

---

## 8. Testing checklist

- [ ] Created Gmail App Password
- [ ] Added `EMAIL_ADDRESS` and `SMTP_PASSWORD` secrets
- [ ] Ran `python scripts/email_notification.py --test` → correct output
- [ ] Ran `python scripts/generate_briefing.py` → `briefing/latest.md` created
- [ ] Committed scripts and updated workflow YAMLs
- [ ] Triggered a manual workflow run and received the email
- [ ] Confirmed email subject, status, and metrics are correct
