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

# --- Configuration ---
SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbykS5AgiAUziwJu798jKwcE3z1MItO-S9Z2XPq4cr_uGPX1QHepyVu-9MBraXYxRaM/exec"
HISTORY_FILE = 'trade_history.json'

ASSETS = {
    'EURUSD=X': {'name': 'EUR/USD', 'dec': 5},
    'GBPUSD=X': {'name': 'GBP/USD', 'dec': 5},
    'AUDUSD=X': {'name': 'AUD/USD', 'dec': 5},
    'JPY=X':    {'name': 'USD/JPY', 'dec': 3},
    'GC=F':     {'name': 'XAU/USD', 'dec': 2},
    'BTC-USD':  {'name': 'BTC/USD', 'dec': 2}
}

# Global Memory (The API will only read from here, NEVER hitting Yahoo directly)
SYSTEM_DATA = {
    "status": "booting",
    "last_update": "جارِ التسخين...",
    "assets": {},
    "history": {'total_closed': 0, 'won': 0, 'lost': 0, 'active': []}
}

# --- Utility Functions ---
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {'total_closed': 0, 'won': 0, 'lost': 0, 'active': []}

def save_history(history):
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f)
    except: pass

def log_to_google_sheets(asset, trade_type, entry, tp, sl, result="Open"):
    try:
        data = {
            "time": str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "asset": asset,
            "type": trade_type,
            "entry": round(entry, 5),
            "tp": round(tp, 5),
            "sl": round(sl, 5),
            "result": result
        }
        requests.post(SHEETS_WEBHOOK_URL, json=data, timeout=5)
    except: pass

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

# --- The Background Ninja Worker ---
def market_scanner_loop():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    SYSTEM_DATA["history"] = load_history()
    
    while True:
        try:
            current_prices = {}
            temp_assets_data = {}
            active_symbols = [t['asset'] for t in SYSTEM_DATA["history"]['active']]

            for symbol, info in ASSETS.items():
                asset_id = info['name'].replace('/', '')
                try:
                    # Stealthy individual fetching
                    tkr = yf.Ticker(symbol, session=session)
                    df_daily = tkr.history(period="60d", interval="1d")
                    df_hourly = tkr.history(period="10d", interval="1h")
                    
                    if df_daily.empty or df_hourly.empty:
                        temp_assets_data[asset_id] = {"error": "لا توجد سيولة/حظر مؤقت"}
                        time.sleep(2)
                        continue
                        
                    d_daily = df_daily[['Close']].dropna()
                    d_hourly = df_hourly[['High', 'Low', 'Close']].dropna()
                    
                    curr_price = float(d_hourly['Close'].iloc[-1])
                    current_prices[asset_id] = curr_price
                    
                    # Logic: Trend, Momentum, POI
                    w1_trend = 'UP' if curr_price > d_daily['Close'].rolling(50).mean().iloc[-1] else 'DOWN'
                    d1_trend = 'UP' if curr_price > d_daily['Close'].rolling(20).mean().iloc[-1] else 'DOWN'
                    h4_trend = 'UP' if curr_price > d_hourly['Close'].rolling(50).mean().iloc[-1] else 'DOWN'
                    m30_trend = 'UP' if curr_price > d_hourly['Close'].rolling(10).mean().iloc[-1] else 'DOWN'

                    rsi_val = float(calculate_rsi(d_hourly['Close']).iloc[-1])
                    adx_val = float(calculate_adx_proxy(d_hourly).iloc[-1])
                    
                    recent_48h = d_hourly.tail(48)
                    diff = recent_48h['High'].max() - recent_48h['Low'].min()
                    
                    fib_50 = recent_48h['High'].max() - (diff * 0.5) if h4_trend == 'UP' else recent_48h['Low'].min() + (diff * 0.5)
                    fib_618 = recent_48h['High'].max() - (diff * 0.618) if h4_trend == 'UP' else recent_48h['Low'].min() + (diff * 0.618)
                    
                    if h4_trend == 'UP':
                        in_poi = (curr_price <= fib_50) and (curr_price >= fib_618)
                        rsi_ok = rsi_val < 55
                    else:
                        in_poi = (curr_price >= fib_50) and (curr_price <= fib_618)
                        rsi_ok = rsi_val > 45

                    # Strength Scoring
                    strength = 0
                    if d1_trend == h4_trend: strength += 30
                    if h4_trend == m30_trend: strength += 20
                    if in_poi: strength += 30
                    if adx_val >= 20: strength += 10 # Slightly relaxed ADX for realistic markets
                    if rsi_ok: strength += 10

                    atr = float(calculate_atr(d_hourly).iloc[-1])
                    signal = 'WAIT'
                    sl, tp = 0.0, 0.0

                    if strength >= 80:
                        signal = 'BUY' if h4_trend == 'UP' else 'SELL'
                        sl = curr_price - (atr * 1.5) if signal == 'BUY' else curr_price + (atr * 1.5)
                        tp = curr_price + (atr * 3.0) if signal == 'BUY' else curr_price - (atr * 3.0)
                        
                        if asset_id not in active_symbols:
                            SYSTEM_DATA["history"]['active'].append({
                                'asset': asset_id, 'type': signal, 'entry': curr_price,
                                'sl': sl, 'tp': tp, 'time': str(datetime.datetime.now())
                            })
                            save_history(SYSTEM_DATA["history"])
                            log_to_google_sheets(asset_id, signal, curr_price, tp, sl, "Open")
                            active_symbols.append(asset_id)

                    temp_assets_data[asset_id] = {
                        'name': info['name'], 'price': curr_price, 'dec': info['dec'],
                        'htf_trend': {'W1': w1_trend, 'D1': d1_trend, 'H4': h4_trend},
                        'strength': strength, 'adx': adx_val, 'rsi': rsi_val,
                        'poi': {'fib_50': fib_50, 'fib_618': fib_618},
                        'signal': signal, 'sl': sl, 'tp': tp
                    }
                except Exception as e:
                    temp_assets_data[asset_id] = {"error": f"جارِ إعادة المحاولة..."}
                
                # Anti-Ban Sleep (crucial)
                time.sleep(3)

            # Evaluate open trades
            still_active = []
            for trade in SYSTEM_DATA["history"]['active']:
                symbol = trade['asset']
                if symbol in current_prices:
                    p = current_prices[symbol]
                    if trade['type'] == 'BUY':
                        if p >= trade['tp']:
                            SYSTEM_DATA["history"]['won'] += 1
                            SYSTEM_DATA["history"]['total_closed'] += 1
                            log_to_google_sheets(symbol, "BUY", trade['entry'], trade['tp'], trade['sl'], "WON (TP)")
                            continue
                        elif p <= trade['sl']:
                            SYSTEM_DATA["history"]['lost'] += 1
                            SYSTEM_DATA["history"]['total_closed'] += 1
                            log_to_google_sheets(symbol, "BUY", trade['entry'], trade['tp'], trade['sl'], "LOST (SL)")
                            continue
                    elif trade['type'] == 'SELL':
                        if p <= trade['tp']:
                            SYSTEM_DATA["history"]['won'] += 1
                            SYSTEM_DATA["history"]['total_closed'] += 1
                            log_to_google_sheets(symbol, "SELL", trade['entry'], trade['tp'], trade['sl'], "WON (TP)")
                            continue
                        elif p >= trade['sl']:
                            SYSTEM_DATA["history"]['lost'] += 1
                            SYSTEM_DATA["history"]['total_closed'] += 1
                            log_to_google_sheets(symbol, "SELL", trade['entry'], trade['tp'], trade['sl'], "LOST (SL)")
                            continue
                still_active.append(trade)
            
            SYSTEM_DATA["history"]['active'] = still_active
            save_history(SYSTEM_DATA["history"])

            # Commit the fresh data to Global Memory
            SYSTEM_DATA["assets"] = temp_assets_data
            SYSTEM_DATA["status"] = "online"
            SYSTEM_DATA["last_update"] = str(datetime.datetime.now().strftime("%H:%M:%S UTC"))
            
        except Exception as e:
            pass
        
        # The Ninja rests for 5 minutes before the next full market scan
        time.sleep(300)

# Start the background worker immediately
threading.Thread(target=market_scanner_loop, daemon=True).start()


# --- API Endpoint ---
@app.route('/api/data')
def get_data():
    return jsonify(SYSTEM_DATA)


# --- Frontend UI ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zuhair Pro Engine</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root { 
    --bg: #0a0a0c; --panel: #13141a; --border: #262833; 
    --text: #d1d5db; --text-muted: #6b7280; 
    --up: #10b981; --down: #ef4444; --neutral: #8b5cf6; --gold: #f59e0b; 
    --header-bg: #1c1d26; --font-sans: 'Tajawal', sans-serif; --font-mono: 'Consolas', monospace; 
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background-color: var(--bg); color: var(--text); font-family: var(--font-sans); padding: 20px; font-size: 14px; line-height: 1.6; }

.top-bar { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--border); margin-bottom: 25px; }
.logo { font-size: 28px; font-weight: 900; color: #fff; letter-spacing: 1px;}
.logo span { color: var(--gold); }
.sys-status { display: flex; gap: 15px; align-items: center; font-family: var(--font-mono); font-size: 12px; color: var(--text-muted); background: var(--panel); padding: 8px 15px; border-radius: 8px; border: 1px solid var(--border);}
.pulse { width: 8px; height: 8px; background-color: var(--up); border-radius: 50%; box-shadow: 0 0 10px var(--up); animation: blink 2s infinite; }
.pulse.booting { background-color: var(--gold); box-shadow: 0 0 10px var(--gold); }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

.grid-layout { display: grid; grid-template-columns: 1fr; gap: 20px; margin-bottom: 25px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.3);}
.card-head { background: var(--header-bg); padding: 15px 20px; font-size: 16px; font-weight: 700; color: #fff; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between;}

.stats-container { display: flex; justify-content: space-around; padding: 20px; }
.stat-item { text-align: center; }
.stat-val { font-size: 28px; font-weight: 900; font-family: var(--font-mono); margin-bottom: 5px; color: #fff;}
.stat-lbl { font-size: 12px; color: var(--text-muted); text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;}

table { width: 100%; border-collapse: collapse; text-align: center; }
th, td { padding: 15px; border-bottom: 1px solid var(--border); }
th { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 1px; font-weight: 700; background: rgba(0,0,0,0.2);}
tr:last-child td { border-bottom: none; }
tr:hover { background: rgba(255,255,255,0.02); }

.asset-name { font-weight: 900; font-size: 16px; color: #fff; font-family: var(--font-mono);}
.price { color: var(--text-muted); font-family: var(--font-mono); font-size: 12px;}
.txt-up { color: var(--up); font-weight: bold; }
.txt-down { color: var(--down); font-weight: bold; }

.badge { padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: bold; }
.badge-buy { background: rgba(16, 185, 129, 0.15); color: var(--up); border: 1px solid rgba(16, 185, 129, 0.3);}
.badge-sell { background: rgba(239, 68, 68, 0.15); color: var(--down); border: 1px solid rgba(239, 68, 68, 0.3);}
.badge-wait { background: rgba(107, 114, 128, 0.15); color: var(--text-muted); border: 1px solid rgba(107, 114, 128, 0.3);}

.trend-arrow { font-size: 16px; }
.progress-bg { background: rgba(0,0,0,0.5); height: 6px; border-radius: 3px; width: 100%; margin-top: 5px; overflow: hidden;}
.progress-fg { height: 100%; border-radius: 3px; transition: 0.5s; }

.booting-screen { text-align: center; padding: 40px; color: var(--gold); font-weight: bold; font-size: 16px; }
</style>
</head>
<body>

<div class="top-bar">
  <div class="logo">Zuhair <span>PRO</span></div>
  <div class="sys-status">
    <div id="statusDot" class="pulse booting"></div>
    <span id="statusText">SYSTEM BOOTING...</span>
    <span style="color:var(--border);">|</span>
    <span id="lastUpdate">--:--:--</span>
  </div>
</div>

<div class="grid-layout">
  <div class="card">
    <div class="card-head"><span>🎯 سجل الأداء (Live Journal)</span> <span style="color:var(--text-muted); font-size:12px;">Google Sheets Synced</span></div>
    <div class="stats-container" id="statsGrid">
        <div class="stat-item"><div class="stat-val">0</div><div class="stat-lbl">إجمالي الصفقات</div></div>
        <div class="stat-item"><div class="stat-val" style="color:var(--up)">0</div><div class="stat-lbl">أهداف (TP)</div></div>
        <div class="stat-item"><div class="stat-val" style="color:var(--down)">0</div><div class="stat-lbl">خسائر (SL)</div></div>
        <div class="stat-item"><div class="stat-val" style="color:var(--gold)">0%</div><div class="stat-lbl">Win Rate</div></div>
    </div>
  </div>
</div>

<div class="card">
  <div class="card-head">📊 الرادار التحليلي والسيولة (Market Radar)</div>
  <div style="overflow-x: auto;">
    <table id="matrixTable">
      <thead>
        <tr>
          <th>Asset</th>
          <th>Trend (D1 / H4)</th>
          <th>Momentum (ADX/RSI)</th>
          <th>Golden Zone (POI)</th>
          <th>Signal Strength</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody id="matrixBody">
        <tr><td colspan="6" class="booting-screen">⏳ يتم سحب البيانات بهدوء لتجاوز الحظر... يرجى الانتظار دقيقة.</td></tr>
      </tbody>
    </table>
  </div>
</div>

<script>
async function fetchData() {
  try {
    const res = await fetch('/api/data');
    const data = await response.json();
    updateUI(data);
  } catch (e) { console.log("Fetching..."); }
}

async function updateData() {
    try {
        const res = await fetch('/api/data');
        const data = await res.json();
        
        // Update Status
        if(data.status === "booting") {
            document.getElementById('statusDot').className = "pulse booting";
            document.getElementById('statusText').innerText = "WARMING UP APIs...";
            return; // Wait for data
        } else {
            document.getElementById('statusDot').className = "pulse";
            document.getElementById('statusText').innerText = "ENGINE ONLINE";
            document.getElementById('lastUpdate').innerText = "Last Scan: " + data.last_update;
        }

        // Update Stats
        let hist = data.history;
        let wr = hist.total_closed > 0 ? ((hist.won / hist.total_closed) * 100).toFixed(1) : 0;
        document.getElementById('statsGrid').innerHTML = `
            <div class="stat-item"><div class="stat-val">${hist.total_closed}</div><div class="stat-lbl">إجمالي الصفقات</div></div>
            <div class="stat-item"><div class="stat-val" style="color:var(--up)">${hist.won}</div><div class="stat-lbl">أهداف (TP)</div></div>
            <div class="stat-item"><div class="stat-val" style="color:var(--down)">${hist.lost}</div><div class="stat-lbl">خسائر (SL)</div></div>
            <div class="stat-item"><div class="stat-val" style="color:var(--gold)">${wr}%</div><div class="stat-lbl">Win Rate</div></div>
        `;

        // Update Matrix
        let html = '';
        for (const [id, d] of Object.entries(data.assets)) {
            if(d.error) {
                html += `<tr><td class="asset-name">${id}</td><td colspan="5" style="color:var(--text-muted); font-size:12px;">${d.error}</td></tr>`;
                continue;
            }
            
            let arr_d1 = d.htf_trend.D1 === 'UP' ? '<span class="txt-up trend-arrow">↑</span>' : '<span class="txt-down trend-arrow">↓</span>';
            let arr_h4 = d.htf_trend.H4 === 'UP' ? '<span class="txt-up trend-arrow">↑</span>' : '<span class="txt-down trend-arrow">↓</span>';
            
            let strColor = d.strength >= 80 ? 'var(--up)' : (d.strength >= 50 ? 'var(--gold)' : 'var(--text-muted)');
            
            let badgeCls = d.signal === 'BUY' ? 'badge-buy' : (d.signal === 'SELL' ? 'badge-sell' : 'badge-wait');
            let sigText = d.signal === 'WAIT' ? 'WAIT' : `${d.signal} @ ${d.price.toFixed(d.dec)}`;

            html += `<tr>
                <td><div class="asset-name">${d.name}</div><div class="price">${d.price.toFixed(d.dec)}</div></td>
                <td><div style="font-size:14px; letter-spacing:3px;">${arr_d1} ${arr_h4}</div></td>
                <td style="font-family:var(--font-mono); font-size:12px; color:var(--text-muted);">ADX: ${d.adx.toFixed(0)} | RSI: ${d.rsi.toFixed(0)}</td>
                <td style="color:var(--gold); font-family:var(--font-mono); font-size:12px;">${d.poi.fib_618.toFixed(d.dec)}<br>${d.poi.fib_50.toFixed(d.dec)}</td>
                <td>
                    <div style="color:${strColor}; font-weight:bold; font-family:var(--font-mono);">${d.strength}%</div>
                    <div class="progress-bg"><div class="progress-fg" style="width:${d.strength}%; background:${strColor};"></div></div>
                </td>
                <td><span class="badge ${badgeCls}">${sigText}</span></td>
            </tr>`;
        }
        document.getElementById('matrixBody').innerHTML = html;

    } catch (e) {}
}

// Refresh UI every 5 seconds (Extremely fast because it only talks to our own background server, NOT Yahoo)
setInterval(updateData, 5000);
updateData();
</script>
</body>
</html>
"""

@app.route('/')
def home():
    return HTML_CONTENT

if __name__ == '__main__':
    app.run(port=8080, debug=False, use_reloader=False)
