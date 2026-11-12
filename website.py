"""Public read-only NHL MoneyPuck projection and odds dashboard."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='IceEdge | NHL Projections', page_icon='🏒', layout='wide', initial_sidebar_state='expanded')
st.markdown('''<style>
.stApp {background: #07121e; color: #eaf3ff;}
[data-testid="stSidebar"] {background: #0b1b2b; border-right: 1px solid #234056;}
h1,h2,h3 {letter-spacing: -.025em;}
[data-testid="stMetric"] {background: #102439; padding: 16px; border: 1px solid #24455d; border-radius: 14px;}
[data-testid="stMetricLabel"] {color:#a4bbcd;}
div.stButton > button[kind="primary"] {background: #32c8a6; color:#031923; border:0;}
.block {background:#102439;border:1px solid #24455d;border-radius:16px;padding:18px;margin:12px 0;}
.kicker {color:#42daba;font-weight:800;letter-spacing: .12em;font-size:12px;}
.muted {color:#a4bbcd;font-size:14px;}
.hero {font-size:36px;font-weight:850;letter-spacing:-.04em;}
</style>''', unsafe_allow_html=True)

def load(name):
    path=ROOT/name
    if not path.exists():return pd.DataFrame(),None
    try:
        df=pd.read_csv(path, dtype={'event_id':'string'})
        return df,datetime.fromtimestamp(path.stat().st_mtime).strftime('%b %d, %Y %I:%M %p')
    except Exception as e:
        st.error(f'Could not read {name}: {e}')
        return pd.DataFrame(),None

def pct(x):
    try:
        if pd.isna(x):return '—'
        return f'{float(x)*100:.1f}%'
    except (ValueError,TypeError):return '—'

def odds_display(x):
    try:
        if pd.isna(x):return '—'
        n=round(float(x));return f'+{n}' if n>0 else str(n)
    except (ValueError,TypeError):return '—'

st.sidebar.markdown('<div class="kicker">ICEEDGE // RESEARCH TERMINAL</div>',unsafe_allow_html=True)
st.sidebar.title('🏒 NHL projections')
page=st.sidebar.radio('Navigate', ['Game projections','Sportsbook comparison','CLV history','Model validation'])
st.sidebar.divider()
st.sidebar.caption('Public research dashboard • MoneyPuck xG + NHL results')
st.sidebar.caption('Read-only. No real orders, implied guaranteed returns, or fabricated quotes.')
if st.sidebar.button('↻ Reload saved data',use_container_width=True):st.rerun()

proj,proj_time=load('nhl_projections.csv')
quotes,quote_time=load('nhl_odds_comparison.csv')
backtest,back_time=load('nhl_backtest_predictions.csv')
st.markdown('<div class="kicker">MONEYPUCK-POWERED NHL ANALYTICS</div>',unsafe_allow_html=True)
st.markdown('<div class="hero">IceEdge <span style="color:#42daba">/ NHL</span></div>',unsafe_allow_html=True)
st.caption('Public research dashboard • full-game winners including OT/shootouts • odds subject to provider access')

if page == 'Game projections':
    st.subheader('Upcoming games')
    a,b,c=st.columns(3)
    a.metric('Upcoming projected games',len(proj))
    b.metric('Projection file updated',proj_time or 'Not generated')
    c.metric('Odds file updated',quote_time or 'Not collected')
    if proj.empty:
        st.info('No published projections yet. The scheduled data update has not completed, or there are no upcoming games. Check back after the next update.')
    else:
        tmp=proj.copy()
        for key in ('home_win_probability','away_win_probability'):
            if key not in tmp:tmp[key]=float('nan')
        if 'date' in tmp.columns:
            tmp['date']=pd.to_datetime(tmp['date'],errors='coerce')
            dates=sorted(tmp['date'].dt.date.dropna().unique().tolist())
            if dates:
                selected=st.selectbox('Game date', ['All dates']+[str(d) for d in dates])
                if selected!='All dates':tmp=tmp[tmp['date'].dt.strftime('%Y-%m-%d')==selected]
        tmp['Home win %']=tmp['home_win_probability'].map(pct)
        tmp['Away win %']=tmp['away_win_probability'].map(pct)
        tmp['Model favorite']=tmp.apply(lambda r: r['home'] if r['home_win_probability']>=.5 else r['away'],axis=1)
        cols={'date':'Date','away':'Away','home':'Home'}
        tmp=tmp.rename(columns=cols)
        st.dataframe(tmp[[k for k in ['Date','Away','Home','Away win %','Home win %','Model favorite'] if k in tmp]],hide_index=True,use_container_width=True)
        st.caption('Model probabilities are estimates, not verified betting edges. MoneyPuck data may be revised after games.')
        st.download_button('Download projections CSV',(ROOT/'nhl_projections.csv').read_bytes(),file_name='nhl_projections.csv',mime='text/csv')

elif page == 'Sportsbook comparison':
    st.subheader('Sportsbook prices vs. our model')
    if quotes.empty:
        st.info('No public sportsbook odds dataset has been published. This site never exposes your API credentials. Odds comparison requires a separately approved data publishing pipeline.')
    else:
        q=quotes.copy()
        q['model_vs_fair_pp']=pd.to_numeric(q.get('model_vs_fair_pp'),errors='coerce')
        q['model_vs_entry_pp']=pd.to_numeric(q.get('model_vs_entry_pp'),errors='coerce')
        books=sorted(q['benchmark_book'].dropna().unique().tolist()) if 'benchmark_book' in q else []
        sel=st.selectbox('Benchmark sportsbook',['All available']+[x for x in books if x])
        if sel!='All available':q=q[q['benchmark_book']==sel]
        threshold=st.slider('Minimum model advantage (percentage points)',0.0,10.0,2.0,.5)
        only_edge=st.checkbox('Only show positive model-vs-book edges',value=False)
        if only_edge:q=q[q['model_vs_fair_pp']>=threshold]
        a,b,c=st.columns(3)
        a.metric('Tracked outcome rows',len(q))
        b.metric('With model projections',int(q['model_vs_fair_pp'].notna().sum()))
        c.metric('Above edge threshold',int((q['model_vs_fair_pp']>=threshold).sum()))
        view=pd.DataFrame({
            'Home':q.get('home'),'Away':q.get('away'),'Side':q.get('side'),
            'Book':q.get('benchmark_book'),
            'Model win %':q.get('model_prob',pd.Series(index=q.index,dtype=float)).map(pct),
            'Book no-vig %':q.get('benchmark_no_vig_prob',pd.Series(index=q.index,dtype=float)).map(pct),
            'Current quoted odds':q.get('benchmark_odds',pd.Series(index=q.index,dtype=float)).map(odds_display),
            'Edge vs no-vig (pp)':q['model_vs_fair_pp'].round(2),
            'Latest quote (UTC)':q.get('latest_quote_utc',pd.Series(index=q.index,dtype=object)),
        })
        st.dataframe(view,hide_index=True,use_container_width=True)
        st.caption('A positive model/book difference is only a candidate signal; it does not prove positive EV or fillable betting value. No Pinnacle CLV without Pinnacle data.')
        st.download_button('Download sportsbook comparisons',(ROOT/'nhl_odds_comparison.csv').read_bytes(),file_name='nhl_odds_comparison.csv',mime='text/csv')

elif page=='CLV history':
    st.subheader('Closing line value')
    if quotes.empty or 'reference_clv_pp' not in quotes:
        st.info('No CLV dataset available. The tracker must save pregame snapshots first.')
    else:
        q=quotes.copy()
        q['reference_clv_pp']=pd.to_numeric(q['reference_clv_pp'],errors='coerce')
        q=q[q['reference_clv_pp'].notna()].copy()
        if q.empty:st.info('No qualifying closing snapshots yet. Keep collecting pregame odds; CLV requires a fresh pregame close.')
        else:
            books=sorted(q['benchmark_book'].dropna().unique())
            choice=st.selectbox('Reference sportsbook',list(books))
            q=q[q['benchmark_book']==choice]
            a,b,c=st.columns(3)
            a.metric('CLV observation rows',len(q))
            b.metric('Average reference CLV',f"{q['reference_clv_pp'].mean():+.2f} pp")
            c.metric('Positive CLV share',f"{(q['reference_clv_pp']>0).mean():.0%}")
            plot=q.sort_values('start_utc').reset_index(drop=True)
            plot['Cumulative CLV (pp)']=plot['reference_clv_pp'].cumsum()
            st.line_chart(plot[['Cumulative CLV (pp)']])
            st.dataframe(q[['start_utc','home','away','side','benchmark_book','reference_entry_odds','closing_benchmark_no_vig_prob','reference_clv_pp']],hide_index=True,use_container_width=True)
            st.warning('This is reference CLV from first observed odds, not actual bet-fill CLV. Both sides of each game may appear; observations are not independent bets.')

elif page=='Model validation':
    st.subheader('Historical backtest')
    if backtest.empty:st.info('No public backtest file has been published yet. The automated model update will create one after it succeeds.')
    else:
        df=backtest.copy()
        df['pred_home_win']=pd.to_numeric(df['pred_home_win'],errors='coerce')
        df['home_win']=pd.to_numeric(df['home_win'],errors='coerce')
        df=df.dropna(subset=['pred_home_win','home_win'])
        if df.empty:st.warning('No valid backtest predictions found.')
        else:
            brier=((df['pred_home_win']-df['home_win'])**2).mean()
            eps=1e-12
            import numpy as np
            p=df['pred_home_win'].clip(eps,1-eps)
            logloss=-(df['home_win']*np.log(p)+(1-df['home_win'])*np.log(1-p)).mean()
            a,b,c=st.columns(3)
            a.metric('Held-out games',len(df));b.metric('Brier score',f'{brier:.4f}');c.metric('Log loss',f'{logloss:.4f}')
            df['Confidence bin']=(df['pred_home_win']*10).clip(0,9.999).astype(int).map(lambda x:f'{x*10}–{(x+1)*10}%')
            calibration=df.groupby('Confidence bin',sort=True,observed=True).agg(Predicted=('pred_home_win','mean'),Actual=('home_win','mean'),Games=('home_win','size')).reset_index()
            st.markdown('**Home-team win calibration**')
            st.dataframe(calibration,hide_index=True,use_container_width=True)
            st.caption('Held-out results do not establish profitability. MoneyPuck historical files can include revisions made after the games.')
            st.download_button('Download backtest',(ROOT/'nhl_backtest_predictions.csv').read_bytes(),file_name='nhl_backtest_predictions.csv',mime='text/csv')


st.divider()
st.caption("Data attribution: MoneyPuck.com (expected-goals data) and the NHL Web API (schedules/results). Research estimates, not betting advice. No API keys or automated order execution on this site.")
