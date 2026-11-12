# Publish IceEdge online (Windows-friendly)

The public dashboard is READ-ONLY. Public visitors cannot run jobs, use your SportsGameOdds key, or place bets. No sample/fake projections are included.

## One-time deployment
1. Go to https://github.com/signup (or sign in).
2. Create a repository named `iceedge-nhl` (public is simplest). Don't add starter files.
3. Click **uploading an existing file**. Unzip this package first and upload all the files including `website.py`, `nhl_model.py`, `moneypuck_data.py`, and `requirements.txt`. GitHub's browser uploader may skip hidden directories like `.github` / `.streamlit`. If so use GitHub Desktop to upload the entire directory, or create `.github/workflows/update_projections.yml` using GitHub's **Add file > Create new file** and paste it from this folder. **Do not upload any `.env`, secrets, or API key.**
4. Go to https://share.streamlit.io and sign in with GitHub.
5. **Create app** > **Yup, I have an app**, choose the repository, main branch and `website.py` as entrypoint. Choose Python **3.12** and deploy.
6. Your site will get a `https://<chosen-name>.streamlit.app` URL. Make sure the app's sharing setting is **Public**.
7. In GitHub, open **Actions** > **Refresh NHL projections** > **Run workflow** once to generate `nhl_projections.csv` and `nhl_backtest_predictions.csv`. GitHub may ask you to enable actions; workflow must have repository contents write permission. This workflow runs daily at 12:20 UTC; the schedule is best-effort, not exact. Streamlit re-deploys when the CSV commit arrives.

## If the website initially says "no projections"
Check the GitHub Actions logs. Until the workflow successfully downloads datasets, no projections can be shown. If the workflow can't write to the repository, under GitHub Settings > Actions > General > Workflow permissions select **Read and write permissions** (if available), then re-run. Hosted environments can fail or be rate-limited; revisit logs.

## Sportsbook/CLV support
The site intentionally does not call SportsGameOdds from public visitors and does not have your API key. Odds & CLV tabs will show no data until a separate server-side licensed odds-collection system publishes safe data (e.g., an exported `nhl_odds_comparison.csv`). Check provider licensing before redistributing commercial odds. The public site does NOT automatically collect sportsbook odds.

## Data / rights / safety
MoneyPuck's publicly downloadable datasets are offered for **non-commercial use**, with clear attribution (https://moneypuck.com/data.htm). Contact MoneyPuck for commercial use or other permission questions. No wagers, wallet keys, credentials, or real-time fill assertions. Do not upload your private odds database or API key. Data updates may be delayed and the model is not validated as profitable.
