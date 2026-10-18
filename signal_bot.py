import os
import json
import datetime
import requests
import yfinance as yf
import pandas as pd
import numpy as np

# ----------------- CONFIGURATION -----------------
TELEGRAM_BOT_TOKEN = "8547996769:AAGBptEXNOsXvnzfQVrOxhTYjnhIkc4YZ0Q"
CHANNEL_CHAT_ID = "@tradewiselynow"

DERIV_REF_LINK = "https://t.deriv.link?t=NEGTK7BHFWUG"
DERIV_PROMO_CODE = "DH54ZEQFYZH5"

TRADES_FILE = "active_trades.json"

# پیر تا جمعہ کے مارکیٹ پیئرز
WEEKDAY_PAIRS = {
    "GOLD (XAU/USD)": "GC=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X"
}

# ویک اینڈ (ہفتہ اور اتوار) 24/7 مارکیٹس
WEEKEND_PAIRS = {
    "BITCOIN (BTC/USD)": "BTC-USD",
    "ETHEREUM (ETH/USD)": "ETH-USD"
}

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=4)

def calculate_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_atr(df, window=14):
    high = df['High'].squeeze()
    low = df['Low'].squeeze()
    close = df['Close'].squeeze()
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=window).mean()
    return atr

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    response = requests.post(url, json=payload)
    return response.json()

def check_active_trades():
    """پرانی ایکٹو ٹریڈز کے TP یا SL ہٹ ہونے کی تصدیق اور لائیو الرٹ"""
    trades = load_trades()
    if not trades:
        return

    remaining_trades = {}

    for name, trade in trades.items():
        ticker = trade.get("ticker")
        try:
            df = yf.download(ticker, period="1d", interval="5m", progress=False)
            if df.empty:
                remaining_trades[name] = trade
                continue

            current_price = float(df['Close'].iloc[-1])
            signal_type = trade["signal_type"]
            entry = float(trade["entry"])
            tp1 = float(trade["tp1"])
            tp2 = float(trade["tp2"])
            sl = float(trade["sl"])

            hit_message = None

            if "BUY" in signal_type:
                if current_price >= tp2:
                    pips = abs(tp2 - entry)
                    hit_message = f"🎯🎯 *TARGET 2 SMASHED!* 🚀\nAsset: *{name}*\nTake Profit 2 Hit at `{current_price:.2f}`\nGain: `+{pips:.2f}`\n\nFull target achieved! Maximize your profits on Deriv 💰"
                elif current_price >= tp1 and not trade.get("tp1_hit"):
                    pips = abs(tp1 - entry)
                    trade["tp1_hit"] = True
                    hit_message = f"🎯 *TARGET 1 HIT!* ✅\nAsset: *{name}*\nTake Profit 1 Hit at `{current_price:.2f}`\nGain: `+{pips:.2f}`\n\nSecure 50% profit & move Stop Loss to Entry (Break-Even)!"
                elif current_price <= sl:
                    hit_message = f"🛑 *STOP LOSS HIT*\nAsset: *{name}*\nClosed at `{current_price:.2f}`\nRisk strictly managed as per plan."

            elif "SELL" in signal_type:
                if current_price <= tp2:
                    pips = abs(entry - tp2)
                    hit_message = f"🎯🎯 *TARGET 2 SMASHED!* 🚀\nAsset: *{name}*\nTake Profit 2 Hit at `{current_price:.2f}`\nGain: `+{pips:.2f}`\n\nFull target achieved! Maximize your profits on Deriv 💰"
                elif current_price <= tp1 and not trade.get("tp1_hit"):
                    pips = abs(entry - tp1)
                    trade["tp1_hit"] = True
                    hit_message = f"🎯 *TARGET 1 HIT!* ✅\nAsset: *{name}*\nTake Profit 1 Hit at `{current_price:.2f}`\nGain: `+{pips:.2f}`\n\nSecure 50% profit & move Stop Loss to Entry (Break-Even)!"
                elif current_price >= sl:
                    hit_message = f"🛑 *STOP LOSS HIT*\nAsset: *{name}*\nClosed at `{current_price:.2f}`\nRisk strictly managed as per plan."

            if hit_message:
                full_alert = f"""📢 *TRADE UPDATE / RESULT*
━━━━━━━━━━━━━━━━━━
{hit_message}
━━━━━━━━━━━━━━━━━━
🚀 *Trade 24/7 with $10,000 Practice Account:*
👉 [Open Deriv Account]({DERIV_REF_LINK})
*(Partner Code: `{DERIV_PROMO_CODE}`)*
"""
                send_telegram_message(full_alert)
                print(f"Update sent for {name}")

                if ("TARGET 2" in hit_message) or ("STOP LOSS" in hit_message):
                    continue

            remaining_trades[name] = trade

        except Exception as e:
            print(f"Error checking {name}: {e}")
            remaining_trades[name] = trade

    save_trades(remaining_trades)

def analyze_and_signal():
    today_weekday = datetime.datetime.utcnow().weekday()
    is_weekend = today_weekday in [5, 6]
    active_pairs = WEEKEND_PAIRS if is_weekend else WEEKDAY_PAIRS

    # 1. پہلے ایکٹو ٹریڈز کے TP اور SL کا معائنہ
    check_active_trades()

    trades = load_trades()

    # 2. ہائی ایکوریسی سگنل فلٹرنگ
    for name, ticker in active_pairs.items():
        if name in trades:
            continue

        try:
            df = yf.download(ticker, period="1mo", interval="1h", progress=False)
            if df.empty or len(df) < 200:
                continue

            close_prices = df['Close'].squeeze()
            current_price = float(close_prices.iloc[-1])

            # فلٹر 1: ڈبل موونگ ایوریج (50 EMA & 200 EMA)
            ema_50 = float(close_prices.ewm(span=50, adjust=False).mean().iloc[-1])
            ema_200 = float(close_prices.ewm(span=200, adjust=False).mean().iloc[-1])

            # فلٹر 2: مومینٹم (RSI 14)
            rsi_series = calculate_rsi(close_prices)
            current_rsi = float(rsi_series.iloc[-1])

            # فلٹر 3: والٹیلیٹی (ATR برائے ڈائنامک رسک)
            atr_series = calculate_atr(df)
            current_atr = float(atr_series.iloc[-1])

            if current_atr <= 0 or np.isnan(current_atr):
                continue

            signal_type = None
            sl = 0.0
            tp1 = 0.0
            tp2 = 0.0

            # اعلیٰ معیار کا بائے سگنل:
            # قیمت 200 EMA سے اوپر ہو + 50 EMA ٹرینڈ کو سپورٹ کرے + RSI پل بیک میں ہو
            if current_price > ema_200 and ema_50 > ema_200 and (40 <= current_rsi <= 52):
                signal_type = "🟢 HIGH-PROBABILITY BUY"
                sl = current_price - (current_atr * 1.5)
                tp1 = current_price + (current_atr * 1.5)  # 1:1 TP1 (ہائی ہٹ ریٹ)
                tp2 = current_price + (current_atr * 3.0)  # 1:2 TP2 (میکسمم پرافٹ)

            # اعلیٰ معیار کا سیل سگنل:
            # قیمت 200 EMA سے نیچے ہو + 50 EMA ڈاون ٹرینڈ میں ہو + RSI پل بیک میں ہو
            elif current_price < ema_200 and ema_50 < ema_200 and (48 <= current_rsi <= 60):
                signal_type = "🔴 HIGH-PROBABILITY SELL"
                sl = current_price + (current_atr * 1.5)
                tp1 = current_price - (current_atr * 1.5)
                tp2 = current_price - (current_atr * 3.0)

            if signal_type:
                trades[name] = {
                    "ticker": ticker,
                    "signal_type": signal_type,
                    "entry": current_price,
                    "tp1": tp1,
                    "tp2": tp2,
                    "sl": sl,
                    "tp1_hit": False,
                    "time": str(datetime.datetime.utcnow())
                }
                save_trades(trades)

                weekend_badge = "\n⚡ *Weekend 24/7 Market Alert*" if is_weekend else ""
                msg = f"""📊 *ALPHA TRADE SIGNALS VIP*{weekend_badge}
━━━━━━━━━━━━━━━━━━
Asset: *{name}*
Setup: *{signal_type}*
Entry Price: `{current_price:.2f}`

🎯 *Take Profit 1:* `{tp1:.2f}` (Safe)
🎯 *Take Profit 2:* `{tp2:.2f}` (Extended)
🛑 *Stop Loss:* `{sl:.2f}` (ATR Protected)

⚡ *Risk / Reward:* `1:2`
📈 *Trend Filter:* Confirmed (50 & 200 EMA Bias)
━━━━━━━━━━━━━━━━━━
💡 *Risk Advice:* Risk max 1-2% per trade.
🚀 *Trade 24/7 Synthetics & Crypto with $10,000 Practice Balance:*
👉 [Open Deriv Practice Account]({DERIV_REF_LINK})
*(Partner Code: `{DERIV_PROMO_CODE}`)*
"""
                send_telegram_message(msg)
                print(f"High-Probability Signal sent for {name}")

        except Exception as e:
            print(f"Error analyzing {name}: {e}")

if __name__ == "__main__":
    analyze_and_signal()
