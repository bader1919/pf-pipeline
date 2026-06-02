# PropertyFinder Pipeline Dashboard - Design Document

## Overview
Simple auto-updating dashboard for pipeline monitoring that provides visibility and control without technical complexity.

## Goal
User can check `https://bader1919.github.io/pf-pipeline/` anytime to see:
- Current pipeline status (Healthy/Issues)
- Last run time and results
- Basic metrics (listings, quality score)
- Recent run history
- One-click access to detailed info

## Architecture

### Dashboard Components
1. **`dashboard/index.html`** - Main dashboard page (static HTML/JavaScript)
2. **`dashboard/data.json`** - Pipeline status data (auto-generated)
3. **`scripts/update_dashboard.py`** - Generates dashboard data from pipeline reports
4. **`.github/workflows/update_dashboard.yml`** - Auto-runs after pipeline to update dashboard

### Data Flow
```
Pipeline Run → Pipeline Reports → update_dashboard.py → dashboard/data.json → GitHub Pages → User sees dashboard
```

### Dashboard Layout
```
┌─────────────────────────────────────────┐
│  PropertyFinder Pipeline Dashboard      │
├─────────────────────────────────────────┤
│  STATUS: ✅ HEALTHY                     │
│  Last run: 2 hours ago                  │
│  Quality: 100%                          │
│  Listings: 24,607                       │
├─────────────────────────────────────────┤
│  Recent Runs:                           │
│  ✅ Today 08:00 - 24,607 listings       │
│  ✅ Today 04:00 - 24,589 listings       │
│  ✅ Yesterday 20:00 - 24,601 listings   │
├─────────────────────────────────────────┤
│  Quick Actions:                         │
│  [View Latest Logs] [View Quality Report]│
│  [Run Pipeline Now] [View Trends]       │
└─────────────────────────────────────────┘
```

## Implementation Plan

### Phase 1: Dashboard Files
- Create `dashboard/index.html` with simple, clean layout
- Create `scripts/update_dashboard.py` to extract data from existing reports
- Setup GitHub Pages to serve dashboard

### Phase 2: Auto-Update System  
- Create `.github/workflows/update_dashboard.yml` 
- Integrate into existing pipeline workflows
- Test automatic updates

### Phase 3: Claude Code Action
- Verify Claude Code Action installation
- Create basic PR review workflow
- Test automation

## Success Criteria
- Dashboard shows current pipeline status accurately
- Updates automatically after each pipeline run
- User can check status without searching logs
- One URL provides all essential information
