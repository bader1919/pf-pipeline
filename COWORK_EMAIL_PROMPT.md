# Claude Cowork Email Reminder & Briefing Prompt

**Copy this prompt into Claude Cowork** to set up automated email reminders and briefings for your PropertyFinder pipeline results.

---

## Task Setup

I want you to create an automated system that:

1. **Sends me email reminders** when the PropertyFinder pipeline runs (GitHub Actions)
2. **Checks the results** (quality, new listings, any issues)
3. **Gives me a brief summary** via email

## Context

**Repository:** https://github.com/bader1919/pf-pipeline

**Pipeline runs:**
- **Currently:** Timing study every 4 hours (June 2-9, 2026)
- **Normally:** Daily at optimal time (TBD)

**Key files to check:**
- `data/latest/quality_report.md` - Quality gate results
- `data/latest_report.json` - Pipeline statistics
- `data/timing_study/daily_log.jsonl` - Timing study progress

**What I care about in each email:**
1. ✓/✗ Quality gate passed or failed
2. Total listings count
3. New listings added
4. Any quality violations
5. Quick summary (1-2 sentences)

## What I Need You to Do

### Step 1: Create Email Notification Script

Create a Python script `scripts/email_notification.py` that:

**Inputs:**
- Quality report path (`data/latest/quality_report.md`)
- Pipeline report path (`data/latest_report.json`)
- Recipient email (my email)

**Does:**
1. Reads quality report
2. Checks if quality gate passed/failed
3. Extracts key metrics (total listings, quality score, violations)
4. Formats brief summary
5. Sends email via:
   - Option A: Gmail SMTP (provide setup instructions)
   - Option B: SendGrid API (provide setup instructions)
   - Option C: GitHub Actions email notification

**Email Format:**
```
Subject: [PropertyFinder] Pipeline Run - [PASS/FAIL] - [Date]

Pipeline run completed: [timestamp]

Status: [PASS/FAIL]
Quality Score: [X]%
Total Listings: [X]
New Listings: [X]
Removed Listings: [X]

Summary:
[1-2 sentence summary]

[If violations, list them here]

[Link to workflow run]
```

### Step 2: Integrate into GitHub Actions

Update `.github/workflows/daily_scrape.yml` and `.github/workflows/timing_study.yml`:

**Add after quality gate step:**
```yaml
- name: Send Email Notification
  if: always()
  run: python scripts/email_notification.py
  env:
    RECIPIENT_EMAIL: ${{ secrets.EMAIL_ADDRESS }}
    SMTP_PASSWORD: ${{ secrets.SMTP_PASSWORD }}
```

**Provide instructions for:**
1. Setting up GitHub Secrets (EMAIL_ADDRESS, SMTP_PASSWORD)
2. Which email service to use (Gmail/SendGrid/other)
3. App password generation if using Gmail

### Step 3: Create Briefing Script

Create `scripts/generate_briefing.py` that:

**Does:**
1. Checks latest pipeline results
2. Compares to previous run (if available)
3. Generates 2-3 bullet points:
   - What changed
   - Any issues
   - Recommendations

**Output:** Markdown briefing saved to `briefing/latest.md`

### Step 4: Schedule Briefing

Set up a schedule:
- **Option A:** Daily briefing at 9 AM Bahrain time
- **Option B:** Weekly briefing on Mondays
- **Option C:** On-demand (I trigger manually)

**What I want in the briefing:**
```
# PropertyFinder Pipeline Briefing
Generated: [Date]

## This Week's Summary
- [Bullet 1: What happened]
- [Bullet 2: Any issues]
- [Bullet 3: Recommendations]

## Quality Trends
- Current quality: [X]%
- Trend: [improving/stable/degrading]

## Next Steps
- [What to do next]

## Timing Study Status
- Day [X] of 7
- Best window so far: [time window]
```

### Step 5: Test the System

1. Run email notification script locally (test mode)
2. Verify email sends correctly
3. Check briefing generation
4. Monitor next GitHub Actions run

## Requirements

**Email Script Requirements:**
- ✅ Read quality_report.md and latest_report.json
- ✅ Parse quality status (PASS/FAIL)
- ✅ Extract key metrics (total listings, quality score, violations)
- ✅ Format brief email (max 200 words)
- ✅ Send via SMTP or API
- ✅ Include workflow run link
- ✅ Handle failures gracefully

**Briefing Script Requirements:**
- ✅ Compare current vs previous run
- ✅ Generate 2-3 bullet points
- ✅ Show quality trends
- ✅ Include timing study status
- ✅ Provide recommendations

**GitHub Actions Integration:**
- ✅ Add email step after quality gate
- ✅ Use secrets for credentials
- ✅ Run on both success and failure
- ✅ Not block pipeline if email fails

## Testing Checklist

- [ ] Email script sends test email successfully
- [ ] Briefing generates correctly
- [ ] GitHub Actions integration works
- [ ] Secrets configured properly
- [ ] Monitored actual pipeline run
- [ ] Email received with correct information
- [ ] Briefing is useful and concise

## Important Notes

- **Don't expose credentials** - use GitHub Secrets
- **Keep emails brief** - I want quick summaries, not reports
- **Include actionable info** - tell me if something needs attention
- **Test thoroughly** - don't wait for actual pipeline failure to test
- **Provide fallback** - if email fails, log error but don't block pipeline

## Deliverables

Please create:
1. `scripts/email_notification.py` - Email sending script
2. `scripts/generate_briefing.py` - Briefing generation script
3. Updated GitHub Actions workflows with email integration
4. Setup instructions for GitHub Secrets
5. Testing instructions
6. Example email output

---

**When ready, implement and test the complete system. Show me example emails and briefings before we deploy to production.**
