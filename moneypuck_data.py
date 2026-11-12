"""Read MoneyPuck's explicitly published game-level all-teams CSV.
MoneyPuck: https://www.moneypuck.com/data.htm (noncommercial use with credit).
"""
from pathlib import Path
import pandas as pd
import requests

URL = 'https://moneypuck.com/moneypuck/playerData/careers/gameByGame/all_teams.csv'
DEFAULT_CSV = Path('data') / 'all_teams.csv'


def download_csv(path=DEFAULT_CSV, refresh=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not refresh:
        print(f'Using saved MoneyPuck CSV: {path} (use --refresh-moneypuck for an updated copy)')
        return path
    print('Downloading MoneyPuck game-level team data from its published download link...')
    tmp = path.with_suffix('.download')
    try:
        with requests.get(URL, stream=True, timeout=(20, 120), headers={'User-Agent':'NHL-Research-Model/1.1 (personal non-commercial research)'}) as response:
            response.raise_for_status()
            with tmp.open('wb') as f:
                for block in response.iter_content(chunk_size=1024*1024):
                    if block:
                        f.write(block)
        if tmp.stat().st_size < 100:
            raise ValueError('MoneyPuck returned an unexpectedly small file.')
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return path


def load_team_xg(path, seasons):
    """Return one row per game/team, filtering 'all' situation.

    Only official game-level data is consumed. 'all' includes special teams.
    xG can be updated by MoneyPuck after the game; historical xG is used only
    as information about PRIOR games, never the game being predicted.
    """
    columns = pd.read_csv(path, nrows=0).columns.tolist()
    required = ['gameId','team','situation','xGoalsFor','xGoalsAgainst']
    missing = [c for c in required if c not in columns]
    if missing:
        raise ValueError(f'MoneyPuck CSV is missing expected columns {missing}. Has: {columns[:18]}')
    extra = ['season'] if 'season' in columns else []
    usecols = required + extra
    parts = []
    seasons_short = {str(s)[:4] for s in seasons}
    for chunk in pd.read_csv(path, usecols=usecols, chunksize=100_000, low_memory=False):
        chunk = chunk[chunk['situation'].astype(str).str.lower().eq('all')]
        if extra:
            chunk = chunk[chunk['season'].astype(str).str[:4].isin(seasons_short)]
        if len(chunk):
            parts.append(chunk[required])
    if not parts:
        raise ValueError('No situation=all rows found in MoneyPuck CSV for selected seasons.')
    df = pd.concat(parts,ignore_index=True)
    df['id'] = pd.to_numeric(df['gameId'],errors='coerce').astype('Int64').astype('string')
    df['team'] = df['team'].astype(str).str.upper().str.strip()
    for c in ['xGoalsFor','xGoalsAgainst']:
        df[c] = pd.to_numeric(df[c],errors='coerce')
    df = df.dropna(subset=['id','xGoalsFor','xGoalsAgainst'])
    if df.duplicated(['id','team']).any():
        # Better to fail than silently join multiple situations / corrupt data.
        examples = df.loc[df.duplicated(['id','team'],keep=False),['id','team']].head(5).to_dict('records')
        raise ValueError(f'Unexpected duplicate MoneyPuck game/team rows: {examples}')
    return df[['id','team','xGoalsFor','xGoalsAgainst']].rename(columns={
        'xGoalsFor':'xgf','xGoalsAgainst':'xga'})


def join_games(games, team_xg):
    """Join BOTH teams via official game ID; require both sides' xG to use a game."""
    d = games.copy()
    d['id'] = d['id'].astype(str)
    home = team_xg.rename(columns={'team':'home','xgf':'home_xgf','xga':'home_xga'})
    away = team_xg.rename(columns={'team':'away','xgf':'away_xgf','xga':'away_xga'})
    d = d.merge(home,on=['id','home'],how='left',validate='one_to_one')
    d = d.merge(away,on=['id','away'],how='left',validate='one_to_one')
    valid = d['complete'] & d[['home_xgf','home_xga','away_xgf','away_xga']].notna().all(axis=1)
    print(f'MoneyPuck xG matched {int(valid.sum())} / {int(d.complete.sum())} completed NHL games.')
    if int(valid.sum()) == 0:
        raise ValueError('No MoneyPuck games match NHL schedule IDs. Check the CSV and seasons.')
    if int(valid.sum()) / max(int(d.complete.sum()),1) < 0.5:
        print('WARNING: MoneyPuck xG match coverage is below 50%; review CSV data and season coverage.')
    d['xg_available'] = valid
    return d
