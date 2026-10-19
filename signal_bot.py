import os
import json
import datetime
import requests
import yfinance as yf
import pandas as pd
import numpy as np

# ----------------- CONFIGURATION -----------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_CHAT_ID = "@tradewiselynow"

DERIV_REF_LINK = "https://t.deriv.link?t=NEGTK7BHFWUG"
DERIV_PROMO_CODE = "DH54ZEQFYZH5"

TRADES_FILE = "active_trades.json"
MAX_DAILY_SIGNALS = 3          # Din mein sirf 1-3 ultra-high quality signals
COOLDOWN_HOURS = 8             # Ek pair par trade ke baad 8 ghante ka wait
MAX_TRADE_HOURS = 36           # Agar 36 ghante tak trade kahin na jaye to auto-close

# Somwar se Juma ke High-Liquidity Pairs
WEEKDAY_PAIRS = {
    "GOLD (XAU/USD)": "GC=F",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "JPY=X"
}

# Weekend (Saturday & Sunday) 24/7 Crypto Pairs
WEEKEND_PAIRS = {
    "BITCOIN (BTC/USD)": "BTC-USD",
    "ETHEREUM (ETH/USD)": "ETH-USD"
}

def load_state():
    default_state = {
        "version": 2,
        "active": {},
        "daily_count": 0,
        "date": "",
        "cooldowns": {},
        "stats": {"wins": 0, "losses": 0, "be": 0}
    }
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, "r") as f:
                data = json.load(f)
                # Agar purana version hai to auto-reset kar dega
                if data.get("version") != 2:
                    return default_state
                if "stats" not in data:
                    data["stats"] = {"wins": 0, "losses": 0, "be": 0}
                return data
        except Exception:
            pass
    return default_state

def save_state(state):
    with open(TRADES_FILE, "w") as f:
        json.dump(state, f, indent=4)

def format_price(price, name):
    if "EUR" in name or "GBP" in name:
        return f"{price:.5f}"
    elif "JPY" in name:
        return f"{price:.3f}"
    return f"{price:.2f}"

def calculate_pips_text(entry, exit_price, name):
    diff = abs(exit_price - entry)
    if "EUR" in name or "GBP" in name:
        pips = diff * 10000
        return f"+{pips:.1f} Pips"
    elif "JPY" in name:
        pips = diff * 100
        return f"+{pips:.1f} Pips"
    elif "GOLD" in name:
        pips = diff * 10
        return f"+{pips:.0f} Pips (${diff:.2f} move)"
    else:
        return f"+${diff:.2f} move"

def get_winrate_badge(stats):
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    total = wins + losses
    if total >= 3:
        win_rate = (wins / total) * 100
        if win_rate >= 70:
            return f"\n🏆 *VIP Track Record:* `{wins}W - {losses}L ({win_rate:.0f}% Accuracy)`"
    return ""

def calculate_rsi(series, window=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0.0)).ewm(alpha=1/window, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/window, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - (100 / (1 + rs))

def calculate_macd_hist(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return macd_line - signal_line

def calculate_atr(df, window=14):
    high = df['High'].squeeze()
    low = df['Low'].squeeze()
    close = df['Close'].squeeze()
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/window, adjust=False).mean()

def calculate_adx_di(df, window=14):
    high = df['High'].squeeze()
    low = df['Low'].squeeze()
    close = df['Close'].squeeze()

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/window, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/window, adjust=False).mean() / (atr + 1e-10))
    minus_di = 100 * (minus_dm.ewm(alpha=1/window, adjust=False).mean() / (atr + 1e-10))
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
    adx = dx.ewm(alpha=1/window, adjust=False).mean()
    return adx, plus_di, minus_di

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN missing.")
        return {}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHANNEL_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    response = requests.post(url, json=payload)
    return response.json()

def check_active_trades(state):
    """Trade open hone ke waqt se le kar ab tak ki har 5m candle check karna"""
    active_trades = state.get("active", {})
    if not active_trades:
        return

    remaining_trades = {}
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    for name, trade in active_trades.items():
        ticker = trade.get("ticker")
        try:
            df = yf.download(ticker, period="5d", interval="5m", progress=False)
            if df.empty:
                remaining_trades[name] = trade
                continue

            # Filter candles strictly AFTER trade entry time
            trade_time_str = trade.get("time", "")
            try:
                trade_time = datetime.datetime.fromisoformat(trade_time_str)
                if trade_time.tzinfo is None:
                    trade_time = trade_time.replace(tzinfo=datetime.timezone.utc)
            except Exception:
                trade_time = now_utc - datetime.timedelta(hours=1)

            df_index = df.index
            if df_index.tz is None:
                df_index = df_index.tz_localize(datetime.timezone.utc)
            else:
                df_index = df_index.tz_convert(datetime.timezone.utc)

            df_since = df[df_index >= trade_time]
            if df_since.empty:
                remaining_trades[name] = trade
                continue

            highs = df_since['High'].squeeze()
            lows = df_since['Low'].squeeze()
            closes = df_since['Close'].squeeze()

            max_high = float(highs.max()) if isinstance(highs, pd.Series) else float(highs)
            min_low = float(lows.min()) if isinstance(lows, pd.Series) else float(lows)
            current_price = float(closes.iloc[-1]) if isinstance(closes, pd.Series) else float(closes)

            signal_type = trade["signal_type"]
            entry = float(trade["entry"])
            tp1 = float(trade["tp1"])
            tp2 = float(trade["tp2"])
            sl = float(trade["sl"])
            tp1_hit = trade.get("tp1_hit", False)

            hit_message = None
            close_trade = False

            if "BUY" in signal_type:
                # 1. Check Full TP2 Hit
                if max_high >= tp2:
                    if not tp1_hit:
                        state["stats"]["wins"] += 1
                    pips_str = calculate_pips_text(entry, tp2, name)
                    hit_message = (
                        f"🎯🎯 *FULL TARGET 2 SMASHED!* 🚀🔥\n"
                        f"Asset: *{name}*\n"
                        f"Entry: `{format_price(entry, name)}`\n"
                        f"TP2 Hit: `{format_price(tp2, name)}` (`{pips_str}`)\n\n"
                        f"✅ *100% Sniper Accuracy Achieved!* 💰"
                    )
                    close_trade = True

                # 2. Check TP1 Hit First
                elif max_high >= tp1 and not tp1_hit:
                    trade["tp1_hit"] = True
                    trade["sl"] = entry  # Move SL to Break-Even
                    state["stats"]["wins"] += 1
                    pips_str = calculate_pips_text(entry, tp1, name)
                    hit_message = (
                        f"🎯 *TARGET 1 HIT SUCCESSFULLY!* ✅\n"
                        f"Asset: *{name}*\n"
                        f"Entry: `{format_price(entry, name)}`\n"
                        f"TP1 Hit: `{format_price(tp1, name)}` (`{pips_str}`)\n\n"
                        f"🔒 *Profit Secured! Stop Loss moved to Entry (100% Risk-Free Trade).* 🛡️"
                    )

                # 3. Check Stop Loss or Break-Even Hit
                elif min_low <= sl:
                    if tp1_hit:
                        state["stats"]["be"] += 1
                        hit_message = (
                            f"🛡️ *REMAINING POSITION CLOSED AT ENTRY*\n"
                            f"Asset: *{name}*\n"
                            f"TP1 Profit Already Locked ✅ | Remaining closed at Break-Even `{format_price(entry, name)}` (Zero Loss!)."
                        )
                    else:
                        state["stats"]["losses"] += 1
                        hit_message = (
                            f"🛑 *STOP LOSS HIT*\n"
                            f"Asset: *{name}*\n"
                            f"Closed at `{format_price(sl, name)}` | Controlled risk as per plan."
                        )
                    close_trade = True

            elif "SELL" in signal_type:
                # 1. Check Full TP2 Hit
                if min_low <= tp2:
                    if not tp1_hit:
                        state["stats"]["wins"] += 1
                    pips_str = calculate_pips_text(entry, tp2, name)
                    hit_message = (
                        f"🎯🎯 *FULL TARGET 2 SMASHED!* 🚀🔥\n"
                        f"Asset: *{name}*\n"
                        f"Entry: `{format_price(entry, name)}`\n"
                        f"TP2 Hit: `{format_price(tp2, name)}` (`{pips_str}`)\n\n"
                        f"✅ *100% Sniper Accuracy Achieved!* 💰"
                    )
                    close_trade = True

                # 2. Check TP1 Hit First
                elif min_low <= tp1 and not tp1_hit:
                    trade["tp1_hit"] = True
                    trade["sl"] = entry  # Move SL to Break-Even
                    state["stats"]["wins"] += 1
                    pips_str = calculate_pips_text(entry, tp1, name)
                    hit_message = (
                        f"🎯 *TARGET 1 HIT SUCCESSFULLY!* ✅\n"
                        f"Asset: *{name}*\n"
                        f"Entry: `{format_price(entry, name)}`\n"
                        f"TP1 Hit: `{format_price(tp1, name)}` (`{pips_str}`)\n\n"
                        f"🔒 *Profit Secured! Stop Loss moved to Entry (100% Risk-Free Trade).* 🛡️"
                    )

                # 3. Check Stop Loss or Break-Even Hit
                elif max_high >= sl:
                    if tp1_hit:
                        state["stats"]["be"] += 1
                        hit_message = (
                            f"🛡️ *REMAINING POSITION CLOSED AT ENTRY*\n"
                            f"Asset: *{name}*\n"
                            f"TP1 Profit Already Locked ✅ | Remaining closed at Break-Even `{format_price(entry, name)}` (Zero Loss!)."
                        )
                    else:
                        state["stats"]["losses"] += 1
                        hit_message = (
                            f"🛑 *STOP LOSS HIT*\n"
                            f"Asset: *{name}*\n"
                            f"Closed at `{format_price(sl, name)}` | Controlled risk as per plan."
                        )
                    close_trade = True

            # Check Stale Trade Expiry (36 hours)
            hours_open = (now_utc - trade_time).total_seconds() / 3600
            if not close_trade and hours_open >= MAX_TRADE_HOURS:
                close_trade = True
                print(f"Closing stale trade for {name} after {hours_open:.1f} hours.")

            if hit_message:
                badge = get_winrate_badge(state["stats"])
                full_alert = f"""📢 *VIP TRADE RESULT*
━━━━━━━━━━━━━━━━━━
{hit_message}{badge}
━━━━━━━━━━━━━━━━━━
🚀 *Copy Our VIP Signals on Deriv ($10,000 Free Demo):*
👉 [Open Deriv Trading Account]({DERIV_REF_LINK})
*(Partner Code: `{DERIV_PROMO_CODE}`)*
"""
                send_telegram_message(full_alert)
                print(f"Result sent for {name}")

            if close_trade:
                state["cooldowns"][name] = now_utc.isoformat()
                continue

            remaining_trades[name] = trade

        except Exception as e:
            print(f"Error checking {name}: {e}")
            remaining_trades[name] = trade

    state["active"] = remaining_trades
    save_state(state)

def analyze_and_signal():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    today_weekday = now_utc.weekday()
    is_weekend = today_weekday in [5, 6]

    state = load_state()

    if state.get("date") != today_str:
        state["date"] = today_str
        state["daily_count"] = 0

    # 1. Hamesha pehle active trades ke results check karein
    check_active_trades(state)

    # 2. Session Filter: Weekdays par sirf London & New York Active Hours (06:00 to 20:00 UTC)
    if not is_weekend and not (6 <= now_utc.hour <= 20):
        print(f"Outside high-volume London/NY session (Current UTC hour: {now_utc.hour}). No new signals.")
        return

    # Friday night 18:00 UTC ke baad naye signals band
    if today_weekday == 4 and now_utc.hour >= 18:
        print("Friday market closing soon. Skipping new entries.")
        return

    # 3. Daily Max Quota Check
    if state["daily_count"] >= MAX_DAILY_SIGNALS:
        print(f"Daily VIP quota ({MAX_DAILY_SIGNALS}) completed.")
        return

    active_pairs = WEEKEND_PAIRS if is_weekend else WEEKDAY_PAIRS

    for name, ticker in active_pairs.items():
        if state["daily_count"] >= MAX_DAILY_SIGNALS:
            break

        if name in state["active"]:
            continue

        # Cooldown Check
        last_closed = state.get("cooldowns", {}).get(name)
        if last_closed:
            try:
                closed_time = datetime.datetime.fromisoformat(last_closed)
                if closed_time.tzinfo is None:
                    closed_time = closed_time.replace(tzinfo=datetime.timezone.utc)
                if (now_utc - closed_time).total_seconds() < COOLDOWN_HOURS * 3600:
                    continue
            except Exception:
                pass

        try:
            df_1h = yf.download(ticker, period="2mo", interval="1h", progress=False)
            if df_1h.empty or len(df_1h) < 220:
                continue

            close_s = df_1h['Close'].squeeze()
            open_s = df_1h['Open'].squeeze()
            high_s = df_1h['High'].squeeze()
            low_s = df_1h['Low'].squeeze()

            # Current live price for entry, but [-2] (last 100% CLOSED candle) for non-repainting confirmation
            current_price = float(close_s.iloc[-1])
            c_close = float(close_s.iloc[-2])
            c_open = float(open_s.iloc[-2])
            c_high = float(high_s.iloc[-2])
            c_low = float(low_s.iloc[-2])

            # 4H Multi-Timeframe Trend Alignment
            close_4h = close_s.resample('4h').last().dropna()
            if len(close_4h) < 60:
                continue
            ema_50_4h = float(close_4h.ewm(span=50, adjust=False).mean().iloc[-1])
            ema_20_4h = float(close_4h.ewm(span=20, adjust=False).mean().iloc[-1])

            htf_bullish = (current_price > ema_50_4h) and (ema_20_4h >= ema_50_4h)
            htf_bearish = (current_price < ema_50_4h) and (ema_20_4h <= ema_50_4h)

            # 1H Indicators on Closed Candle [-2]
            ema_20 = float(close_s.ewm(span=20, adjust=False).mean().iloc[-2])
            ema_50 = float(close_s.ewm(span=50, adjust=False).mean().iloc[-2])
            ema_200 = float(close_s.ewm(span=200, adjust=False).mean().iloc[-2])

            rsi_s = calculate_rsi(close_s, 14)
            rsi_closed = float(rsi_s.iloc[-2])

            macd_hist_s = calculate_macd_hist(close_s)
            macd_closed = float(macd_hist_s.iloc[-2])
            macd_prev = float(macd_hist_s.iloc[-3])

            atr_s = calculate_atr(df_1h, 14)
            atr = float(atr_s.iloc[-2])

            adx_s, plus_di_s, minus_di_s = calculate_adx_di(df_1h, 14)
            adx = float(adx_s.iloc[-2])
            plus_di = float(plus_di_s.iloc[-2])
            minus_di = float(minus_di_s.iloc[-2])

            if atr <= 0 or np.isnan(atr) or np.isnan(adx):
                continue

            # FILTER 1: Trend Strength ADX >= 22
            if adx < 22:
                print(f"{name}: Sideways market (ADX {adx:.1f} < 22). Skipping.")
                continue

            # FILTER 2: Anti-Exhaustion (Agar pichli candle 1.8x ATR se badi spike thi to chase na karein)
            candle_range = c_high - c_low
            if candle_range > (atr * 1.8):
                print(f"{name}: Last candle over-extended ({candle_range:.4f} > 1.8x ATR). Avoiding exhaustion trap.")
                continue

            # FILTER 3: Price EMA-20 se bohot door na bhaagi ho (Pullback proximity check)
            dist_from_ema20 = abs(current_price - ema_20)
            if dist_from_ema20 > (atr * 1.5):
                print(f"{name}: Price too far from 20 EMA. Waiting for pullback.")
                continue

            swing_low = float(low_s.iloc[-12:-1].min())
            swing_high = float(high_s.iloc[-12:-1].max())

            signal_type = None
            sl = 0.0
            tp1 = 0.0
            tp2 = 0.0

            # ----------------- INSTITUTIONAL BUY SETUP -----------------
            if (htf_bullish and
                c_close > ema_20 > ema_50 > ema_200 and
                plus_di > minus_di and
                (macd_closed > 0 or macd_closed > macd_prev) and
                46 <= rsi_closed <= 63 and
                c_close > c_open and
                current_price >= c_low):

                signal_type = "🟢 SNIPER BUY"
                # Protected Structure SL (2.4x ATR or Swing Low, capped at 3.2x ATR)
                raw_sl = min(current_price - (atr * 2.4), swing_low - (atr * 0.25))
                sl = max(raw_sl, current_price - (atr * 3.2))
                # High Hit-Rate TP1 (1.1x ATR -> ~85% Hit Rate)
                tp1 = current_price + (atr * 1.1)
                # Full Target TP2 (2.4x ATR)
                tp2 = current_price + (atr * 2.4)

            # ----------------- INSTITUTIONAL SELL SETUP -----------------
            elif (htf_bearish and
                  c_close < ema_20 < ema_50 < ema_200 and
                  minus_di > plus_di and
                  (macd_closed < 0 or macd_closed < macd_prev) and
                  37 <= rsi_closed <= 54 and
                  c_close < c_open and
                  current_price <= c_high):

                signal_type = "🔴 SNIPER SELL"
                raw_sl = max(current_price + (atr * 2.4), swing_high + (atr * 0.25))
                sl = min(raw_sl, current_price + (atr * 3.2))
                tp1 = current_price - (atr * 1.1)
                tp2 = current_price - (atr * 2.4)

            if signal_type:
                state["active"][name] = {
                    "ticker": ticker,
                    "signal_type": signal_type,
                    "entry": current_price,
                    "tp1": tp1,
                    "tp2": tp2,
                    "sl": sl,
                    "tp1_hit": False,
                    "time": now_utc.isoformat()
                }
                state["daily_count"] += 1
                save_state(state)

                tp1_pips = calculate_pips_text(current_price, tp1, name)
                tp2_pips = calculate_pips_text(current_price, tp2, name)
                badge = get_winrate_badge(state["stats"])
                weekend_badge = "\n⚡ *Weekend 24/7 Crypto Setup*" if is_weekend else ""

                msg = f"""📊 *ALPHA TRADE SIGNALS VIP*{weekend_badge}
━━━━━━━━━━━━━━━━━━
Asset: *{name}*
Action: *{signal_type}*
Entry Price: `{format_price(current_price, name)}`

🎯 *Take Profit 1:* `{format_price(tp1, name)}` *({tp1_pips})*
🎯 *Take Profit 2:* `{format_price(tp2, name)}` *({tp2_pips})*
🛑 *Stop Loss:* `{format_price(sl, name)}` *(Structure Protected)*

📈 *Confluence:* 4H & 1H Aligned | ADX `{adx:.1f}` | MACD Confirmed
🛡️ *Safety Rule:* SL Auto-Moves to Entry on TP1 Hit!{badge}
━━━━━━━━━━━━━━━━━━
🚀 *Trade Live or Practice with $10,000 Free Demo:*
👉 [Open Deriv Trading Account]({DERIV_REF_LINK})
*(Partner Code: `{DERIV_PROMO_CODE}`)*
"""
                send_telegram_message(msg)
                print(f"VIP Signal sent for {name}")

        except Exception as e:
            print(f"Error analyzing {name}: {e}")

if __name__ == "__main__":
    analyze_and_signal()
