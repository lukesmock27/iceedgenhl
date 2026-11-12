"""NHL pregame moneyline projections: Elo + form + rest, with walk-forward backtest.
Data: public NHL Web API. No authentication or betting account needed.
Run: python nhl_model.py --backtest-season 20252026
"""
from __future__ import annotations
import argparse
import concurrent.futures
import json
import math
from collections import defaultdict, deque
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from moneypuck_data import DEFAULT_CSV, download_csv, load_team_xg, join_games

API = 'https://api-web.nhle.com/v1'
TEAMS = 'ANA BOS BUF CAR CBJ CGY CHI COL DAL DET EDM FLA LAK MIN MTL NJD NSH NYI NYR OTT PHI PIT SEA SJS STL TBL TOR UTA VAN VGK WPG WSH'.split()
SEASONS = ['20232024', '20242025', '20252026', '20262027']
CACHE = Path('nhl_api_cache')
CACHE.mkdir(exist_ok=True)


def api_get(path, refresh=False):
    filename = CACHE / (path.replace('/', '_') + '.json')
    if filename.exists() and not refresh:
        return json.loads(filename.read_text(encoding='utf-8'))
    response = requests.get(f'{API}/{path}', timeout=30, headers={'User-Agent':'NHL-Model-Research/1.0'})
    response.raise_for_status()
    data = response.json()
    filename.write_text(json.dumps(data), encoding='utf-8')
    return data


def fetch_schedule(team_season):
    team, season, current_season = team_season
    data = api_get(f'club-schedule-season/{team}/{season}', refresh=(season == current_season))
    return data.get('games', [])


def load_games(seasons):
    current_season = f"{date.today().year}{date.today().year+1}" if date.today().month >= 7 else f"{date.today().year-1}{date.today().year}"
    tasks = [(team, season, current_season) for season in seasons for team in TEAMS]
    games = {}
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        future_map = {pool.submit(fetch_schedule, task):task for task in tasks}
        for future in concurrent.futures.as_completed(future_map):
            try:
                for g in future.result():
                    if g.get('gameType') != 2:  # regular season only
                        continue
                    gid = g.get('id')
                    if gid and gid not in games:
                        games[gid] = g
            except (requests.RequestException, ValueError, OSError) as exc:
                errors.append((future_map[future], str(exc)))
    if errors:
        print(f'WARNING: {len(errors)} schedule requests failed. Example: {errors[0]}')
    if not games:
        raise RuntimeError('Could not load any NHL games. Check internet connection and API access.')
    rows = []
    for gid, g in games.items():
        home, away = g.get('homeTeam', {}), g.get('awayTeam', {})
        h, a = home.get('abbrev'), away.get('abbrev')
        if not h or not a:
            continue
        hs, aws = home.get('score'), away.get('score')
        completed = g.get('gameState') in ('FINAL','OFF') and isinstance(hs,int) and isinstance(aws,int)
        # The game scores include a shootout deciding goal when applicable.
        rows.append({'id':gid,'date':g.get('gameDate'),'season':str(g.get('season') or (str(gid)[:4] + str(int(str(gid)[:4])+1))),
                     'home':h,'away':a,'home_goals':hs if completed else np.nan,
                     'away_goals':aws if completed else np.nan,'complete':completed})
    df = pd.DataFrame(rows)
    if df.empty:
        raise RuntimeError('The NHL API returned no usable regular-season games.')
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    return df.dropna(subset=['date']).sort_values(['date','id']).drop_duplicates('id').reset_index(drop=True)


def make_features(games):
    """Strictly pregame features; update team statistics only AFTER creating each game's features."""
    elo = defaultdict(lambda:1500.0)
    scored = defaultdict(lambda:deque(maxlen=20))
    conceded = defaultdict(lambda:deque(maxlen=20))
    last_game = {}
    xg_for = defaultdict(lambda: deque(maxlen=20))
    xg_against = defaultdict(lambda: deque(maxlen=20))
    rows = []
    previous_season = None
    for g in games.itertuples(index=False):
        if previous_season is not None and g.season != previous_season:
            for team in list(elo):
                elo[team] = 1500 + .75*(elo[team]-1500)  # offseason regression
        previous_season = g.season
        h, a = g.home, g.away
        def avg_or_baseline(values, baseline=3.0, prior=10):
            return (sum(values) + prior*baseline) / (len(values)+prior)
        rh = (g.date-last_game[h]).days if h in last_game else 4
        ra = (g.date-last_game[a]).days if a in last_game else 4
        # Clamp long off-season rests and explicitly model back-to-back teams.
        record = {'id':g.id,'date':g.date,'season':g.season,'home':h,'away':a,
                  'elo_diff':(elo[h]-elo[a])/100,
                  'goal_for_diff':avg_or_baseline(scored[h])-avg_or_baseline(scored[a]),
                  'goal_against_diff':avg_or_baseline(conceded[a])-avg_or_baseline(conceded[h]),
                  'xg_for_diff':avg_or_baseline(xg_for[h])-avg_or_baseline(xg_for[a]),
                  'xg_against_diff':avg_or_baseline(xg_against[a])-avg_or_baseline(xg_against[h]),
                  'home_b2b':int(rh<=1),'away_b2b':int(ra<=1),
                  'rest_diff':max(-3,min(3,min(rh,5)-min(ra,5))),
                  'home_win':int(g.home_goals>g.away_goals) if g.complete else np.nan,
                  'complete':g.complete}
        rows.append(record)
        if g.complete:
            # Elo already accounts for home ice through fixed 35-point home advantage.
            expected = 1/(1+10**(-((elo[h]+35-elo[a])/400)))
            result = float(g.home_goals>g.away_goals)
            margin_mult = min(1.5, 1 + .12*(abs(g.home_goals-g.away_goals)-1))
            change = 18*margin_mult*(result-expected)
            elo[h]+=change
            elo[a]-=change
            scored[h].append(g.home_goals); conceded[h].append(g.away_goals)
            scored[a].append(g.away_goals); conceded[a].append(g.home_goals)
            last_game[h]=g.date; last_game[a]=g.date
            # Update xG ONLY after this game's pregame row is created.
            # Both team rows must be available to avoid inconsistent updates.
            if getattr(g, "xg_available", False):
                xg_for[h].append(g.home_xgf); xg_against[h].append(g.home_xga)
                xg_for[a].append(g.away_xgf); xg_against[a].append(g.away_xga)
    return pd.DataFrame(rows)

FEATURES=['elo_diff','goal_for_diff','goal_against_diff','home_b2b','away_b2b','rest_diff','xg_for_diff','xg_against_diff']

def fitted_model(train):
    if train['home_win'].nunique()<2:
        raise ValueError('Not enough completed games to fit the model')
    # Regularized logistic model. Intercept learns average home advantage.
    model=LogisticRegression(C=0.4,max_iter=300)
    model.fit(train[FEATURES],train['home_win'].astype(int))
    return model


def report_backtest(features, season):
    train=features[(features['complete']) & (features['season']<season)]
    test=features[(features['complete']) & (features['season']==season)]
    if len(train)<500 or len(test)<100:
        print(f'Backtest skipped: insufficient completed training ({len(train)}) or test ({len(test)}) games.')
        return
    model=fitted_model(train)
    predictions=model.predict_proba(test[FEATURES])[:,1]
    outcomes=test['home_win'].astype(int)
    base=float(train['home_win'].mean())
    print(f'BACKTEST SEASON {season} | train: {len(train)} games | test: {len(test)} games')
    print(f'Model Brier: {brier_score_loss(outcomes,predictions):.4f} | baseline: {brier_score_loss(outcomes,np.full(len(test),base)):.4f}')
    print(f'Model log loss: {log_loss(outcomes,predictions):.4f} | baseline: {log_loss(outcomes,np.full(len(test),base)):.4f}')
    print('These are forecasting metrics, NOT evidence of betting profitability.')
    out=test[['date','home','away','home_win']].copy()
    out['pred_home_win']=predictions
    out.to_csv('nhl_backtest_predictions.csv',index=False)


def project_games(features, today):
    played=features[features['complete'] & (features['date']<today)]
    upcoming=features[~features['complete'] & (features['date']>=today)]
    if len(played)<500 or upcoming.empty:
        print('No upcoming games or insufficient historical data to predict.')
        return
    model=fitted_model(played)
    upcoming=upcoming.copy()
    upcoming['home_win_probability']=model.predict_proba(upcoming[FEATURES])[:,1]
    upcoming['away_win_probability']=1-upcoming['home_win_probability']
    upcoming=upcoming[['date','away','home','away_win_probability','home_win_probability']]
    upcoming=upcoming.sort_values('date').head(60)
    upcoming.to_csv('nhl_projections.csv',index=False)
    print('\nNEXT GAMES — regulation/OT/shootout-inclusive moneyline probabilities')
    print(upcoming.head(15).to_string(index=False,formatters={
        'away_win_probability':lambda x:f'{100*x:.1f}%',
        'home_win_probability':lambda x:f'{100*x:.1f}%'}))
    print('Saved nhl_projections.csv')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--seasons',nargs='+',default=SEASONS)
    parser.add_argument('--backtest-season',default='20252026')
    parser.add_argument('--today',default=date.today().isoformat(),help='YYYY-MM-DD (defaults to today)')
    parser.add_argument('--moneypuck-file',default=str(DEFAULT_CSV),help='Path to downloaded MoneyPuck all_teams.csv')
    parser.add_argument('--refresh-moneypuck',action='store_true',help='Download a fresh CSV before running')
    parser.add_argument('--no-moneypuck',action='store_true',help='Run baseline features without downloading xG')
    args=parser.parse_args()
    games=load_games(args.seasons)
    print(f'Loaded {len(games)} unique regular-season games; {int(games.complete.sum())} final')
    if not args.no_moneypuck:
        path=download_csv(args.moneypuck_file,args.refresh_moneypuck)
        xg=load_team_xg(path,args.seasons)
        games=join_games(games,xg)
    else:
        games['xg_available']=False
    features=make_features(games)
    report_backtest(features,args.backtest_season)
    project_games(features,pd.Timestamp(args.today))
    print('\nWARNING: First-pass benchmark, not a calibrated or validated profitable trading strategy.')
    print('MoneyPuck team xG is included unless --no-moneypuck was specified.')
    print('Future: confirmed goalies, injuries, sharp-market odds and timestamped CLV.')

if __name__=='__main__':
    main()
