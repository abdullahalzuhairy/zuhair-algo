import os
import json
import time
import datetime
import warnings
import numpy as np
import pandas as pd
import requests
from flask import Flask, jsonify

# استيراد yfinance وتجاهل التحذيرات
warnings.filterwarnings("ignore")
import yfinance as yf

app = Flask(__name__)

# --- الإعدادات والروابط ---
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

# --- نظام الذاكرة المؤقتة لتقليل الضغط وتجاوز الحظر ---
CACHE = {"data": None, "timestamp": 0}
CACHE_DURATION = 300  # 5 دقائق

# --- دوال المساعدة ---
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

# --- الواجهة البرمجية (API) ---
@app.route('/api/data')
def get_data():
    current_time = time.time()
    
    # إرجاع البيانات من الذاكرة إذا لم تمر 5 دقائق
    if CACHE["data"] and (current_time - CACHE["timestamp"] < CACHE_DURATION):
        return jsonify(CACHE["data"])

    # جلسة اتصال وهمية
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    })

    history = load_history()
    active_symbols = [t['asset'] for t in history['active']]
    assets_data = {}
    current_prices = {}

    for symbol, info in ASSETS.items():
        asset_name = info['name']
        try:
            # السحب التسلسلي الآمن
            tkr = yf.Ticker(symbol, session=session)
            df_daily = tkr.history(period="60d", interval="1d")
            df_hourly = tkr.history(period="10d", interval="1h")
            
            if df_daily.empty or df_hourly.empty:
                assets_data[asset_name] = {"error": "تم حظر الطلب من المصدر (Rate Limit). يرجى الانتظار."}
                continue
                
            d_daily = df_daily[['Close']].dropna()
            d_hourly = df_hourly[['High', 'Low', 'Close']].dropna()
            
            if d_daily.empty or d_hourly.empty:
                assets_data[asset_name] = {"error": "بيانات غير مكتملة."}
                continue

            curr_price = float(d_hourly['Close'].iloc[-1])
            current_prices[asset_name] = curr_price
            
            # حساب الاتجاه (بناءً على طلبك بالتركيز على الاتجاه + POI)
            w1_trend = 'UP' if curr_price > d_daily['Close'].rolling(50).mean().iloc[-1] else 'DOWN'
            d1_trend = 'UP' if curr_price > d_daily['Close'].rolling(20).mean().iloc[-1] else 'DOWN'
            h4_trend = 'UP' if curr_price > d_hourly['Close'].rolling(50).mean().iloc[-1] else 'DOWN'
            m30_trend = 'UP' if curr_price > d_hourly['Close'].rolling(10).mean().iloc[-1] else 'DOWN'

            rsi_val = float(calculate_rsi(d_hourly['Close']).iloc[-1])
            adx_val = float(calculate_adx_proxy(d_hourly).iloc[-1])
            
            recent_48h = d_hourly.tail(48)
            diff = recent_48h['High'].max() - recent_48h['Low'].min()
            
            if h4_trend == 'UP':
                fib_50 = recent_48h['High'].max() - (diff * 0.500)
                fib_618 = recent_48h['High'].max() - (diff * 0.618)
                in_poi = (curr_price <= fib_50) and (curr_price >= fib_618)
                rsi_ok = rsi_val < 55 # تخفيف الشرط قليلاً لزيادة الفرص
            else:
                fib_50 = recent_48h['Low'].min() + (diff * 0.500)
                fib_618 = recent_48h['Low'].min() + (diff * 0.618)
                in_poi = (curr_price >= fib_50) and (curr_price <= fib_618)
                rsi_ok = rsi_val > 45

            # قوة الإشارة
            strength = 0
            if d1_trend == h4_trend: strength += 30
            if h4_trend == m30_trend: strength += 20
            if in_poi: strength += 30
            if adx_val >= 20: strength += 10 
            if rsi_ok: strength += 10

            atr = float(calculate_atr(d_hourly).iloc[-1])
            signal = 'WAIT'
            sl, tp = 0.0, 0.0

            if strength >= 80:
                signal = 'BUY' if h4_trend == 'UP' else 'SELL'
                sl = curr_price - (atr * 1.5) if signal == 'BUY' else curr_price + (atr * 1.5)
                tp = curr_price + (atr * 3.0) if signal == 'BUY' else curr_price - (atr * 3.0)
                
                # تسجيل الصفقة الجديدة
                if asset_name not in active_symbols:
                    history['active'].append({
                        'asset': asset_name, 'type': signal, 'entry': curr_price,
                        'sl': sl, 'tp': tp, 'time': str(datetime.datetime.now())
                    })
                    save_history(history)
                    log_to_google_sheets(asset_name, signal, curr_price, tp, sl, "Open")
                    active_symbols.append(asset_name)

            assets_data[asset_name] = {
                'name': asset_name, 'price': curr_price, 'dec': info['dec'],
                'htf_trend': {'W1': w1_trend, 'D1': d1_trend, 'H4': h4_trend},
                'strength': strength, 'adx': adx_val, 'rsi': rsi_val,
                'poi': {'fib_50': fib_50, 'fib_618': fib_618},
                'signal': signal, 'sl': sl, 'tp': tp
            }
            
        except Exception as e:
            assets_data[asset_name] = {"error": f"خطأ مؤقت: {str(e)[:40]}..."}
            continue

    # تقييم الصفقات المفتوحة
    still_active = []
    for trade in history['active']:
        symbol = trade['asset']
        if symbol in current_prices:
            p = current_prices[symbol]
            if trade['type'] == 'BUY':
                if p >= trade['tp']:
                    history['won'] += 1
                    history['total_closed'] += 1
                    log_to_google_sheets(symbol, "BUY", trade['entry'], trade['tp'], trade['sl'], "WON (TP)")
                    continue
                elif p <= trade['sl']:
                    history['lost'] += 1
                    history['total_closed'] += 1
                    log_to_google_sheets(symbol, "BUY", trade['entry'], trade['tp'], trade['sl'], "LOST (SL)")
                    continue
            elif trade['type'] == 'SELL':
                if p <= trade['tp']:
                    history['won'] += 1
                    history['total_closed'] += 1
                    log_to_google_sheets(symbol, "SELL", trade['entry'], trade['tp'], trade['sl'], "WON (TP)")
                    continue
                elif p >= trade['sl']:
                    history['lost'] += 1
                    history['total_closed'] += 1
                    log_to_google_sheets(symbol, "SELL", trade['entry'], trade['tp'], trade['sl'], "LOST (SL)")
                    continue
        still_active.append(trade)

    history['active'] = still_active
    save_history(history)

    final_response = {
        "assets": assets_data, 
        "history": history,
        "last_update": str(datetime.datetime.now().strftime("%H:%M:%S UTC"))
    }
    
    CACHE["data"] = final_response
    CACHE["timestamp"] = current_time

    return jsonify(final_response)


# --- واجهة المستخدم (HTML & JS) ---
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zuhair PRO Engine</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root { 
    --bg: #0a0a0c; --panel: #13141a; --border: #262833; 
    --text: #d1d5db; --text-muted: #6b7280; 
    --up: #10b981; --down: #ef4444; --neutral: #3b82f6; --gold: #f59e0b; 
    --header-bg: #1c1d26; --font-sans: 'Tajawal', sans-serif; --font-mono: 'Consolas', monospace; 
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background-color: var(--bg); color: var(--text); font-family: var(--font-sans); padding: 20px; font-size: 14px; line-height: 1.6; }

.top-bar { display: flex; justify-content: space-between; align-items: center; padding-bottom: 20px; border-bottom: 1px solid var(--border); margin-bottom: 25px; flex-wrap: wrap; gap: 15px;}
.logo { font-size: 28px; font-weight: 900; color: #fff; letter-spacing: 1px;}
.logo span { color: var(--neutral); }
.sys-status { display: flex; gap: 15px; align-items: center; font-family: var(--font-mono); font-size: 13px; color: var(--text-muted); background: var(--panel); padding: 10px 20px; border-radius: 8px; border: 1px solid var(--border);}
.pulse { width: 10px; height: 10px; background-color: var(--up); border-radius: 50%; box-shadow: 0 0 10px var(--up); animation: blink 2s infinite; }
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

.btn-refresh { background: var(--neutral); color: #fff; border: none; padding: 10px 20px; border-radius: 6px; font-family: var(--font-sans); font-weight: 700; cursor: pointer; transition: 0.2s;}
.btn-refresh:hover { background: #2563eb; }
.btn-refresh:disabled { background: var(--text-muted); cursor: not-allowed; }

.grid-layout { display: grid; grid-template-columns: 1fr; gap: 20px; margin-bottom: 25px; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.3);}
.card-head { background: var(--header-bg); padding: 15px 20px; font-size: 16px; font-weight: 700; color: #fff; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between;}

.stats-container { display: flex; justify-content: space-around; padding: 20px; flex-wrap: wrap; gap: 15px;}
.stat-item { text-align: center; background: rgba(255,255,255,0.02); padding: 15px; border-radius: 8px; border: 1px solid var(--border); flex-grow: 1; min-width: 120px;}
.stat-val { font-size: 28px; font-weight: 900; font-family: var(--font-mono); margin-bottom: 5px; color: #fff;}
.stat-lbl { font-size: 12px; color: var(--text-muted); text-transform: uppercase; font-weight: 700;}

table { width: 100%; border-collapse: collapse; text-align: center; }
th, td { padding: 15px; border-bottom: 1px solid var(--border); }
th { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: 1px; font-weight: 700; background: rgba(0,0,0,0.2);}
tr:last-child td { border-bottom: none; }
tr:hover { background: rgba(255,255,255,0.02); }

.asset-name { font-weight: 900; font-size: 16px; color: #fff; font-family: var(--font-mono);}
.price { color: var(--text-muted); font-family: var(--font-mono); font-size: 12px;}
.txt-up { color: var(--up); font-weight: bold; }
.txt-down { color: var(--down); font-weight: bold; }

.badge { padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: bold; display: inline-block;}
.badge-buy { background: rgba(16, 185, 129, 0.15); color: var(--up); border: 1px solid rgba(16, 185, 129, 0.3);}
.badge-sell { background: rgba(239, 68, 68, 0.15); color: var(--down); border: 1px solid rgba(239, 68, 68, 0.3);}
.badge-wait { background: rgba(107, 114, 128, 0.15); color: var(--text-muted); border: 1px solid rgba(107, 114, 128, 0.3);}

.trend-arrow { font-size: 18px; }
.progress-bg { background: rgba(0,0,0,0.5); height: 8px; border-radius: 4px; width: 100%; margin-top: 5px; overflow: hidden;}
.progress-fg { height: 100%; border-radius: 4px; transition: 0.5s; }

.loading-screen { text-align: center; padding: 40px; color: var(--text-muted); font-weight: bold; font-size: 16px; }
</style>
</head>
<body>

<div class="top-bar">
  <div class="logo">Zuhair <span>PRO</span></div>
  <div class="sys-status">
    <div class="pulse"></div>
    <span>ENGINE ONLINE</span>
    <span style="color:var(--border);">|</span>
    <span id="lastUpdate">--:--:--</span>
  </div>
  <button class="btn-refresh" id="refreshBtn" onclick="forceRefresh()">🔄 تحديث البيانات</button>
</div>

<div class="grid-layout">
  <div class="card">
    <div class="card-head"><span>🎯 سجل الأداء (Live Journal)</span> <span style="color:var(--gold); font-size:12px;">Synced with Google Sheets ✅</span></div>
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
        <tr><td colspan="6" class="loading-screen">⏳ يتم سحب البيانات الآمنة... يرجى الانتظار بضع ثوانٍ.</td></tr>
      </tbody>
    </table>
  </div>
</div>

<script>
async function loadData() {
    const btn = document.getElementById('refreshBtn');
    btn.disabled = true;
    btn.innerText = "⏳ جاري التحديث...";
    
    try {
        const res = await fetch('/api/data');
        const data = await res.json();
        
        document.getElementById('lastUpdate').innerText = "Last Scan: " + data.last_update;

        let hist = data.history;
        let wr = hist.total_closed > 0 ? ((hist.won / hist.total_closed) * 100).toFixed(1) : 0;
        document.getElementById('statsGrid').innerHTML = `
            <div class="stat-item"><div class="stat-val">${hist.total_closed}</div><div class="stat-lbl">إجمالي الصفقات</div></div>
            <div class="stat-item"><div class="stat-val" style="color:var(--up)">${hist.won}</div><div class="stat-lbl">أهداف (TP)</div></div>
            <div class="stat-item"><div class="stat-val" style="color:var(--down)">${hist.lost}</div><div class="stat-lbl">خسائر (SL)</div></div>
            <div class="stat-item"><div class="stat-val" style="color:var(--gold)">${wr}%</div><div class="stat-lbl">Win Rate</div></div>
        `;

        let html = '';
        for (const [id, d] of Object.entries(data.assets)) {
            if(d.error) {
                html += `<tr><td class="asset-name">${id}</td><td colspan="5" style="color:var(--down); font-size:12px; font-weight:bold;">⚠️ ${d.error}</td></tr>`;
                continue;
            }
            
            let arr_d1 = d.htf_trend.D1 === 'UP' ? '<span class="txt-up trend-arrow">↑</span>' : '<span class="txt-down trend-arrow">↓</span>';
            let arr_h4 = d.htf_trend.H4 === 'UP' ? '<span class="txt-up trend-arrow">↑</span>' : '<span class="txt-down trend-arrow">↓</span>';
            
            let strColor = d.strength >= 80 ? 'var(--up)' : (d.strength >= 50 ? 'var(--gold)' : 'var(--text-muted)');
            
            let badgeCls = d.signal === 'BUY' ? 'badge-buy' : (d.signal === 'SELL' ? 'badge-sell' : 'badge-wait');
            let sigText = d.signal === 'WAIT' ? 'WAIT' : `${d.signal} <br><span style="font-size:10px;">${d.price.toFixed(d.dec)}</span>`;

            html += `<tr>
                <td><div class="asset-name">${d.name}</div><div class="price">${d.price.toFixed(d.dec)}</div></td>
                <td><div style="font-size:14px; letter-spacing:5px;">${arr_d1} ${arr_h4}</div></td>
                <td style="font-family:var(--font-mono); font-size:12px; color:var(--text-muted);">ADX: ${d.adx.toFixed(0)} <br> RSI: ${d.rsi.toFixed(0)}</td>
                <td style="color:var(--gold); font-family:var(--font-mono); font-size:12px;">${d.poi.fib_618.toFixed(d.dec)}<br>${d.poi.fib_50.toFixed(d.dec)}</td>
                <td>
                    <div style="color:${strColor}; font-weight:bold; font-family:var(--font-mono);">${d.strength}%</div>
                    <div class="progress-bg"><div class="progress-fg" style="width:${d.strength}%; background:${strColor};"></div></div>
                </td>
                <td><div class="badge ${badgeCls}">${sigText}</div></td>
            </tr>`;
        }
        document.getElementById('matrixBody').innerHTML = html;

    } catch (e) {
        document.getElementById('matrixBody').innerHTML = `<tr><td colspan="6" style="color:var(--down);">فشل الاتصال بالسيرفر. يرجى المحاولة مرة أخرى.</td></tr>`;
    }
    
    btn.disabled = false;
    btn.innerText = "🔄 تحديث البيانات";
}

function forceRefresh() {
    document.getElementById('matrixBody').innerHTML = '<tr><td colspan="6" class="loading-screen">⏳ يتم جلب أحدث البيانات من السوق...</td></tr>';
    loadData();
}

// تحميل البيانات تلقائياً عند فتح الموقع
window.onload = loadData;
</script>
</body>
</html>
"""

@app.route('/')
def home():
    return HTML_CONTENT

if __name__ == '__main__':
    app.run(port=8080, debug=False, use_reloader=False)
