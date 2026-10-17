import os
import requests
import yfinance as yf
import pandas as pd
import numpy as np

# ----------------- CONFIGURATION -----------------
TELEGRAM_BOT_TOKEN = "8547996769:AAGBptEXNOsXvnzfQVrOxhTYjnhIkc4YZ0Q"
CHANNEL_CHAT_ID = "@tradewiselynow"

DERIV_REF_LINK = "https://t.deriv.link?t=NEGTK7BHFWUG"
DERIV_PROMO_CODE = "DH54ZEQFYZH5"

# اینالیسس کے لیے اثاثے (ہفتہ وار اور 24/7 مارکیٹ سپورٹ)
PAIRS = {
    "GOLD (XAU/USD)": "GC=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "BITCOIN": "BTC-USD"
}

def calculate_rsi(data, window=14):
    delta = data.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

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

def analyze_and_signal():
    signals_generated = 0

    for name, ticker in PAIRS.items():
        try:
            # 1 گھنٹے کی کینڈلز سے ڈیٹا اینالیسس
            df = yf.download(ticker, period="1mo", interval="1h", progress=False)
            if df.empty or len(df) < 50:
                continue

            close_prices = df['Close'].squeeze()
            current_price = float(close_prices.iloc[-1])

            # تکنیکی انڈیکیٹرز: 50 EMA اور RSI
            ema_50 = float(close_prices.ewm(span=50, adjust=False).mean().iloc[-1])
            rsi_series = calculate_rsi(close_prices)
            current_rsi = float(rsi_series.iloc[-1])

            signal_type = None
            sl = 0.0
            tp1 = 0.0
            tp2 = 0.0

            # بائے سگنل کی شرائط
            if current_price > ema_50 and 42 <= current_rsi <= 58:
                signal_type = "🟢 BUY SETUP"
                sl = current_price * 0.992
                tp1 = current_price * 1.008
                tp2 = current_price * 1.016

            # سیل سگنل کی شرائط
            elif current_price < ema_50 and 42 <= current_rsi <= 58:
                signal_type = "🔴 SELL SETUP"
                sl = current_price * 1.008
                tp1 = current_price * 0.992
                tp2 = current_price * 0.984

            if signal_type:
                signals_generated += 1
                msg = f"""📊 *ALPHA TRADE SIGNALS VIP*
━━━━━━━━━━━━━━━━━━
Asset: *{name}*
Signal: *{signal_type}*
Entry Price: `{current_price:.2f}`

🎯 *Take Profit 1:* `{tp1:.2f}`
🎯 *Take Profit 2:* `{tp2:.2f}`
🛑 *Stop Loss:* `{sl:.2f}`

⚡ *Risk / Reward:* `1:2`
📈 *Market Bias:* {'Bullish Momentum' if 'BUY' in signal_type else 'Bearish Momentum'}
━━━━━━━━━━━━━━━━━━
💡 *Risk Note:* Risk only 1% to 2% per trade.
🚀 *Trade 24/7 with $10,000 Practice Balance:*
👉 [Open Deriv Practice Account]({DERIV_REF_LINK})
*(Partner Code: `{DERIV_PROMO_CODE}`)*
"""
                res = send_telegram_message(msg)
                print(f"Signal sent for {name}: {res}")

        except Exception as e:
            print(f"Error analyzing {name}: {e}")

    if signals_generated == 0:
        print("Market conditions are neutral. Waiting for next high-probability setup.")

if __name__ == "__main__":
    analyze_and_signal()
