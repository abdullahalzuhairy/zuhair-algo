import os
import json
import time
import threading
import warnings
import datetime
import numpy as np
import pandas as pd
import requests
from flask import Flask, jsonify
import yfinance as yf

warnings.filterwarnings("ignore")
app = Flask(__name__)

# --- Trade History Manager ---
HISTORY_FILE = 'trade_history.json'

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {'total_closed': 0, 'won': 0, 'lost': 0, 'active': []}

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(history, f)

def evaluate_active_trades(current_prices):
    history = load_history()
    still_active = []
    
    for trade in history['active']:
        symbol = trade['asset']
        if symbol in current_prices:
            curr_price = current_prices[symbol]
            if trade['type'] == 'BUY':
                if curr_price >= trade['tp']:
                    history['won'] += 1
                    history['total_closed'] += 1
                    continue
                elif curr_price <= trade['sl']:
                    history['lost'] += 1
                    history['total_closed'] += 1
                    continue
            elif trade['type'] == 'SELL':
                if curr_price <= trade['tp']:
                    history['won'] += 1
                    history['total_closed'] += 1
                    continue
                elif curr_price >= trade['sl']:
                    history['lost'] += 1
                    history['total_closed'] += 1
                    continue
        still_active.append(trade)
        
    history['active'] = still_active
    save_history(history)
    return history

# --- HTML Frontend ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zuhair Algo — Pro Trader 24/5</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0d1117; --panel: #161b22; --border: #30363d;
  --text: #c9d1d9; --text-muted: #8b949e;
  --up: #3fb950; --down: #f85149; --neutral: #d2a8ff; --poi: #58a6ff; --gold: #e3b341;
  --header-bg: #21262d; 
  --font-mono: 'Consolas', 'Courier New', monospace;
  --font-sans: 'Tajawal', sans-serif;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background-color: var(--bg); color: var(--text); font-family: var(--font-sans); padding: 15px; font-size: 13px; line-height: 1.6; }

/* Top Header */
.header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 15px; border-bottom: 2px solid var(--border); margin-bottom: 20px; }
.title { font-size: 26px; font-weight: 800; text-transform: uppercase; letter-spacing: 1px; color: #fff; }
.title span { color: var(--gold); }
.sys-info { display: flex; gap: 20px; font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); align-items: center;}
.status-indicator { color: var(--up); font-weight: bold; display: flex; align-items: center; gap: 6px; }
.live-dot { width: 10px; height: 10px; background-color: var(--up); border-radius: 50%; box-shadow: 0 0 10px var(--up); animation: blink 1.5s infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

/* Layout Grids */
.dashboard-top { display: grid; grid-template-columns: 1fr 2fr; gap: 20px; margin-bottom: 20px; }
@media (max-width: 900px) { .dashboard-top { grid-template-columns: 1fr; } }

/* Cards & Panels */
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.panel-header { background: var(--header-bg); padding: 12px 15px; border-bottom: 1px solid var(--border); font-size: 16px; font-weight: 800; color: #fff; display: flex; justify-content: space-between; align-items: center;}
.panel-body { padding: 15px; }

/* Stats Board */
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; text-align: center; }
.stat-box { background: rgba(255,255,255,0.03); border: 1px solid var(--border); padding: 15px; border-radius: 6px; }
.stat-val { font-size: 24px; font-weight: 800; font-family: var(--font-mono); color: #fff; margin-bottom: 5px;}
.stat-lbl { font-size: 11px; color: var(--text-muted); text-transform: uppercase; }

/* Signals Grid */
.signals-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px; }
.signal-card { background: #0d1117; border: 1px solid var(--border); border-radius: 8px; padding: 15px; position: relative; display: flex; flex-direction: column; gap: 12px;}
.signal-card::before { content: ''; position: absolute; top: 0; right: 0; width: 4px; height: 100%; border-radius: 0 8px 8px 0;}
.signal-card.buy::before { background: var(--up); }
.signal-card.sell::before { background: var(--down); }
.signal-card.wait::before { background: var(--text-muted); }

.sig-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px dashed var(--border); padding-bottom: 8px; }
.sig-asset { font-size: 20px; font-weight: 800; color: #fff; font-family: var(--font-mono); display:flex; align-items:center; gap: 10px;}
.strength-badge { background: rgba(255,255,255,0.1); font-size: 12px; padding: 3px 8px; border-radius: 12px; border: 1px solid var(--border); color: #fff; }
.strength-badge.high { background: rgba(63, 185, 80, 0.2); border-color: var(--up); color: var(--up); }
.sig-type { font-weight: 800; padding: 6px 12px; border-radius: 4px; font-size: 13px; letter-spacing: 1px; }
.type-buy { background: rgba(63, 185, 80, 0.15); color: var(--up); border: 1px solid var(--up); }
.type-sell { background: rgba(248, 81, 73, 0.15); color: var(--down); border: 1px solid var(--down); }
.type-wait { background: rgba(139, 148, 158, 0.15); color: var(--text-muted); border: 1px solid var(--text-muted); }

.sig-levels { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; text-align: center; }
.level-box { background: rgba(255,255,255,0.03); padding: 10px 5px; border-radius: 6px; border: 1px solid var(--border);}
.level-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin-bottom: 5px; font-weight: bold;}
.level-val { font-family: var(--font-mono); font-weight: bold; font-size: 14px; }

/* Table */
table { width: 100%; border-collapse: collapse; font-family: var(--font-mono); font-size: 13px; text-align: center; }
th, td { border: 1px solid var(--border); padding: 12px; }
th { background-color: rgba(0,0,0,0.2); color: var(--text-muted); font-family: var(--font-sans); text-transform: uppercase; font-weight: 700; }
tr:hover { background-color: rgba(255,255,255,0.03); }
.txt-up { color: var(--up); font-weight: bold; }
.txt-down { color: var(--down); font-weight: bold; }
.txt-neutral { color: var(--neutral); font-weight: bold; }
</style>
</head>
<body>

<div class="header">
  <div class="title">Zuhair <span>Ultimate</span> 24/5</div>
  <div class="sys-info">
    <div class="status-indicator" id="apiStatus"><div class="live-dot"></div> ENGINE ONLINE</div>
    <div>REFRESH: <span id="countdown">60</span>s (Cached)</div>
    <div id="clock">--:--:-- UTC</div>
  </div>
</div>

<div class="dashboard-top">
  <div class="panel" style="grid-column: span 2;">
    <div class="panel-header">📈 أداء النظام وسجل الصفقات (Live Win Rate)</div>
    <div class="panel-body">
      <div class="stats-grid" id="statsGrid">
        <div class="stat-box"><div class="stat-val">0</div><div class="stat-lbl">إجمالي الصفقات</div></div>
        <div class="stat-box"><div class="stat-val" style="color:var(--up)">0</div><div class="stat-lbl">أهداف متحققة (TP)</div></div>
        <div class="stat-box"><div class="stat-val" style="color:var(--down)">0</div><div class="stat-lbl">ضرب ستوب (SL)</div></div>
        <div class="stat-box"><div class="stat-val" style="color:var(--gold)">0%</div><div class="stat-lbl">نسبة النجاح (Win Rate)</div></div>
      </div>
      <div style="margin-top: 15px; font-size: 12px; color: var(--text-muted); text-align: center;">
        * يتم مراقبة الصفقات المفتوحة التي حققت قوة إشارة 80% فما فوق وتسجيل نتائجها تلقائياً. 
        <br><span style="color:var(--poi)">تم تفعيل وضع مضاد الحظر وتوفير الـ CPU لضمان استقرار السيرفر.</span>
      </div>
    </div>
  </div>
</div>

<div class="panel" style="margin-bottom: 20px;">
  <div class="panel-header" style="background: rgba(227, 179, 65, 0.1); color: var(--gold); border-bottom: 1px solid var(--gold);">
    🎯 التوصيات المفلترة (قوة الإشارة > 80%)
  </div>
  <div class="panel-body">
    <div class="signals-grid" id="signalsContainer">
      <div style="color:var(--text-muted); text-align:center; width:100%; padding:20px;">جاري الفحص... بانتظار إشارات قوية.</div>
    </div>
  </div>
</div>

<div class="panel">
  <div class="panel-header">📊 المصفوفة التحليلية (جميع الأزواج)</div>
  <div style="overflow-x: auto;">
    <table id="matrixTable">
      <thead>
        <tr>
          <th>Asset</th>
          <th>HTF Direction</th>
          <th>Signal Strength</th>
          <th>Golden Zone (POI)</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody id="matrixBody">
        <tr><td colspan="5" style="padding: 20px; text-align:center;">جاري جلب البيانات بأمان...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<script>
const ASSETS = [
  { id: 'EURUSD', name: 'EUR/USD', dec: 5 },
  { id: 'GBPUSD', name: 'GBP/USD', dec: 5 },
  { id: 'AUDUSD', name: 'AUD/USD', dec: 5 },
  { id: 'USDJPY', name: 'USD/JPY', dec: 3 },
  { id: 'XAUUSD', name: 'XAU/USD', dec: 2 },
  { id: 'BTCUSD', name: 'BTC/USD', dec: 2 }
];

async function fetchSystemData() {
  try {
    const response = await fetch('/api/data');
    const data = await response.json();
    if(data.error) {
        console.error("Backend Error:", data.error);
    }
    renderStats(data.history);
    renderMatrixAndSignals(data.assets);
  } catch (error) { console.error("Error:", error); }
}

function renderStats(hist) {
    if(!hist) return;
    let winRate = hist.total_closed > 0 ? ((hist.won / hist.total_closed) * 100).toFixed(1) : 0;
    document.getElementById('statsGrid').innerHTML = `
        <div class="stat-box"><div class="stat-val">${hist.total_closed}</div><div class="stat-lbl">صفقات مغلقة</div></div>
        <div class="stat-box"><div class="stat-val" style="color:var(--up)">${hist.won}</div><div class="stat-lbl">أهداف متحققة (TP)</div></div>
        <div class="stat-box"><div class="stat-val" style="color:var(--down)">${hist.lost}</div><div class="stat-lbl">ضرب ستوب (SL)</div></div>
        <div class="stat-box"><div class="stat-val" style="color:var(--gold)">${winRate}%</div><div class="stat-lbl">Win Rate</div></div>
    `;
}

function getCls(val) {
    if (val === 'UP' || val === 'BUY') return 'txt-up';
    if (val === 'DOWN' || val === 'SELL') return 'txt-down';
    return 'txt-neutral';
}

function renderMatrixAndSignals(assetsData) {
  let tableHtml = '';
  let signalsHtml = '';

  ASSETS.forEach(a => {
    let d = assetsData[a.id];
    if(!d) return;
    
    let p = d.price.toFixed(a.dec);
    let str = d.strength;
    let sBadge = str >= 80 ? 'strength-badge high' : 'strength-badge';
    
    tableHtml += `<tr>
      <td style="font-weight:bold; color:#fff;">${a.name} <br><span style="color:var(--neutral); font-size:11px;">${p}</span></td>
      <td>W: <span class="${getCls(d.htf_trend.W1)}">${d.htf_trend.W1}</span> | D: <span class="${getCls(d.htf_trend.D1)}">${d.htf_trend.D1}</span></td>
      <td><div class="${sBadge}">${str}% Match</div></td>
      <td style="color:var(--gold)">${d.poi.fib_618.toFixed(a.dec)} - ${d.poi.fib_50.toFixed(a.dec)}</td>
      <td class="${getCls(d.signal)}">${d.signal}</td>
    </tr>`;

    if (str >= 80 && d.signal !== 'WAIT') {
        let cClass = d.signal === 'BUY' ? 'buy' : 'sell';
        let tClass = d.signal === 'BUY' ? 'type-buy' : 'type-sell';
        let aText = d.signal === 'BUY' ? '🟢 BUY' : '🔴 SELL';
        
        signalsHtml += `
        <div class="signal-card ${cClass}">
          <div class="sig-header">
            <div class="sig-asset">${a.name} <span class="strength-badge high">🔥 ${str}% إشارة قوية</span></div>
            <span class="sig-type ${tClass}">${aText}</span>
          </div>
          <div class="sig-levels">
            <div class="level-box"><div class="level-label">Entry</div><div class="level-val" style="color:#fff;">${p}</div></div>
            <div class="level-box"><div class="level-label">Target (TP)</div><div class="level-val" style="color:var(--up);">${d.tp.toFixed(a.dec)}</div></div>
            <div class="level-box"><div class="level-label">Stop (SL)</div><div class="level-val" style="color:var(--down);">${d.sl.toFixed(a.dec)}</div></div>
          </div>
        </div>`;
    }
  });

  if (tableHtml === '') {
      tableHtml = '<tr><td colspan="5" style="padding: 20px; color:var(--down);">يوجد تأخير في سحب البيانات من السوق، جاري المحاولة...</td></tr>';
  }

  document.getElementById('matrixBody').innerHTML = tableHtml;
  if(signalsHtml === '') {
      document.getElementById('signalsContainer').innerHTML = '<div style="color:var(--text-muted); text-align:center; width:100%; padding:20px;">لا توجد صفقات حالياً تتطابق بنسبة 80% فما فوق. جاري المراقبة...</div>';
  } else {
      document.getElementById('signalsContainer').innerHTML = signalsHtml;
  }
}

setInterval(() => { const now = new Date(); document.getElementById('clock').textContent = now.toUTCString().split(' ')[4] + ' UTC'; }, 1000);
let countdown = 60;
setInterval(() => { countdown--; if (countdown <= 0) { countdown = 60; fetchSystemData(); } document.getElementById('countdown').textContent = countdown; }, 1000);

fetchSystemData();
</script>
</body>
</html>
"""

@app.route('/')
def home():
    return HTML_CONTENT

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    return np.max(ranges, axis=1).rolling(period).mean()

def calculate_adx_proxy(df, period=14):
    tr = calculate_atr(df, period)
    price_change = abs(df['Close'] - df['Close'].shift(period))
    adx_proxy = (price_change / (tr * period)) * 100
    return adx_proxy.rolling(7).mean().fillna(20)


# --- CPU SAVING CACHE SYSTEM ---
CACHE = {
    "data": None,
    "timestamp": 0
}
CACHE_DURATION = 180  # 3 Minutes cache

@app.route('/api/data')
def get_data():
    current_time = time.time()
    
    if CACHE["data"] is not None and (current_time - CACHE["timestamp"] < CACHE_DURATION):
        return jsonify(CACHE["data"])

    tickers = {
        'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X', 'AUDUSD': 'AUDUSD=X',
        'USDJPY': 'JPY=X', 'XAUUSD': 'GC=F', 'BTCUSD': 'BTC-USD'
    }
    
    # --- Anti-Ban Session (Tricks Yahoo Finance into thinking this is a real browser) ---
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    assets_data = {}
    current_prices = {}
    history = load_history()
    active_symbols = [t['asset'] for t in history['active']]

    for asset_id, symbol in tickers.items():
        try:
            # Download each ticker individually to prevent multi-index parsing errors
            df_daily = yf.download(symbol, period="60d", interval="1d", progress=False, session=session)
            df_hourly = yf.download(symbol, period="10d", interval="1h", progress=False, session=session)
            
            if df_daily.empty or df_hourly.empty:
                print(f"Warning: No data received for {symbol}")
                continue
                
            d_daily = pd.DataFrame({'Close': df_daily['Close']}).dropna()
            d_hourly = pd.DataFrame({'High': df_hourly['High'], 'Low': df_hourly['Low'], 'Close': df_hourly['Close']}).dropna()
            
            curr_price = float(d_hourly['Close'].iloc[-1])
            current_prices[asset_id] = curr_price
            
            # --- TREND FILTERS ---
            w1_trend = 'UP' if curr_price > d_daily['Close'].rolling(50).mean().iloc[-1] else 'DOWN'
            d1_trend = 'UP' if curr_price > d_daily['Close'].rolling(20).mean().iloc[-1] else 'DOWN'
            h4_trend = 'UP' if curr_price > d_hourly['Close'].rolling(50).mean().iloc[-1] else 'DOWN'
            m30_trend = 'UP' if curr_price > d_hourly['Close'].rolling(10).mean().iloc[-1] else 'DOWN'

            rsi_val = float(calculate_rsi(d_hourly['Close']).iloc[-1])
            adx_val = float(calculate_adx_proxy(d_hourly).iloc[-1])
            
            # --- POI ZONE ---
            recent_48h = d_hourly.tail(48)
            diff = recent_48h['High'].max() - recent_48h['Low'].min()
            
            if h4_trend == 'UP':
                fib_50 = recent_48h['High'].max() - (diff * 0.500)
                fib_618 = recent_48h['High'].max() - (diff * 0.618)
                in_poi = (curr_price <= fib_50) and (curr_price >= fib_618)
                rsi_ok = rsi_val < 50
            else:
                fib_50 = recent_48h['Low'].min() + (diff * 0.500)
                fib_618 = recent_48h['Low'].min() + (diff * 0.618)
                in_poi = (curr_price >= fib_50) and (curr_price <= fib_618)
                rsi_ok = rsi_val > 50

            # --- CALCULATE SIGNAL STRENGTH % ---
            strength = 0
            if d1_trend == h4_trend: strength += 30
            if h4_trend == m30_trend: strength += 20
            if in_poi: strength += 30
            if adx_val >= 25: strength += 10
            if rsi_ok: strength += 10

            atr = float(calculate_atr(d_hourly).iloc[-1])
            signal = 'WAIT'
            sl, tp = 0.0, 0.0

            if strength >= 80:
                signal = 'BUY' if h4_trend == 'UP' else 'SELL'
                if signal == 'BUY':
                    sl = curr_price - (atr * 1.5)
                    tp = curr_price + (atr * 3.0)
                else:
                    sl = curr_price + (atr * 1.5)
                    tp = curr_price - (atr * 3.0)
                
                if asset_id not in active_symbols:
                    history['active'].append({
                        'asset': asset_id, 'type': signal, 'entry': curr_price,
                        'sl': sl, 'tp': tp, 'time': str(datetime.datetime.now())
                    })
                    save_history(history)

            assets_data[asset_id] = {
                'price': curr_price,
                'htf_trend': {'W1': w1_trend, 'D1': d1_trend, 'H4': h4_trend},
                'strength': strength,
                'poi': {'fib_50': fib_50, 'fib_618': fib_618},
                'signal': signal, 'sl': sl, 'tp': tp
            }
        except Exception as e:
            print(f"Error processing {asset_id}: {str(e)}")
            continue

    updated_history = evaluate_active_trades(current_prices)

    final_response = {"assets": assets_data, "history": updated_history}
    
    CACHE["data"] = final_response
    CACHE["timestamp"] = current_time

    return jsonify(final_response)

if __name__ == '__main__':
    app.run(port=8080, debug=False, use_reloader=False)
