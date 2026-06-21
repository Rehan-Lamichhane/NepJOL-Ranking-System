# NepJOL Ranking System

Minor Project - NepJOL Ranking System

## Overview
This project scrapes NepJOL journal metadata, compiles article-level metrics, computes an unsupervised clustering-based ranking of journals and exposes a small Flask API to view the results.

## Quickstart
1. Create and activate a virtual environment (recommended):
   python -m venv .venv
   source .venv/bin/activate   # Linux/macOS
   .venv\Scripts\activate    # Windows

2. Install dependencies:
   pip install -r requirements.txt

3. Run the scraper to gather data (this will create the `data/` folder):
   python -m "Core.Scraper"
   # or
   python "NepJOL Ranking System/Core/Scraper.py"

4. Run the pipeline to compute rankings and generate pickled model artifacts:
   python -m "Core.Pipeline"
   # or
   python "NepJOL Ranking System/Core/Pipeline.py"

5. Start the Flask app:
   python "NepJOL Ranking System/app.py"

6. Open http://127.0.0.1:5000/ in your browser. API endpoints:
   - GET /api/rankings
   - GET /api/articles?journal=<Journal Name>

## Notes
- Set environment variable `USER_EMAIL` to a valid contact email before running the scraper to provide a polite user-agent string for CrossRef API queries.
- Add `data/` and `models/` to .gitignore (already added).

