@echo off
cd /d %~dp0
echo ============================================
echo  PropertyFinder BH - Full Pipeline Run
echo ============================================
echo.

echo [1/3] Scraping all categories...
python scraper\pf_scraper.py
if errorlevel 1 (
    echo ERROR: Scraper failed. Check output above.
    pause
    exit /b 1
)

echo.
echo [2/3] Cleaning and flattening data...
python scraper\cleaner.py
if errorlevel 1 (
    echo ERROR: Cleaner failed. Check output above.
    pause
    exit /b 1
)

echo.
echo [3/3] Running change comparator...
python scraper\comparator.py
if errorlevel 1 (
    echo ERROR: Comparator failed. Check output above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Pushing to GitHub...
echo ============================================
git add data\latest\ data\previous\ data\changes\
git diff --staged --quiet && (
    echo No data changes to commit.
) || (
    git commit -m "data: pipeline run"
    git push
    echo SUCCESS - Data pushed to GitHub.
)

echo.
echo ============================================
echo  Done. Check data\latest\all_listings.csv
echo ============================================
pause
