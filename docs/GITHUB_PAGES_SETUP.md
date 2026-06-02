# GitHub Pages Setup Instructions

## Quick Setup (One-Time)

1. Go to your repository settings: https://github.com/bader1919/pf-pipeline/settings/pages

2. Under "Source", select:
   - **Branch:** `master`
   - **Folder:** `/dashboard`
   - Click **Save**

3. Wait ~1-2 minutes for GitHub to deploy

4. Your dashboard will be available at: https://bader1919.github.io/pf-pipeline/

## What You'll See

- **Green "Healthy" status** - Pipeline is running smoothly
- **Last run time** - When the pipeline last ran
- **Quality score** - Current data quality percentage
- **Total listings** - How many properties in database
- **Recent runs** - Last few pipeline runs with status
- **Quick action buttons** - Links to GitHub Actions, data, etc.

## Automatic Updates

The dashboard updates automatically after every pipeline run:
- Timing study runs (every 4 hours)
- Daily scrape runs (when re-enabled)
- Manual workflow triggers

No manual refresh needed - just bookmark the URL and check anytime!