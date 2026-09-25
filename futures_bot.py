"""
BTC/USDT 1m Scalper — BYBIT FUTURES (LEVERAGED)
"""
import os
import sys
import time
import requests
import ccxt
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

from features_1m import add_features_1m
from predictor_1m import ScalpPredictor
from decision_1m import decide_scalp

# ─── Configuration ────────────────────────────────────────────────
SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"
LOOP_INTERVAL = 60

# ─── FUTURES CONFIG ───
LEVERAGE = 10
MARGIN_PCT = 0.02  # Use 2% of account balance as margin

FUTURES_TESTNET_API_KEY = os.environ.get("FUTURES_TESTNET_API_KEY", "")
FUTURES_TESTNET_API_SECRET = os.environ.get("FUTURES_TESTNET_API_SECRET", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── Safety limits ───
MAX_CONSECUTIVE_LOSSES = 10
MAX_DAILY_LOSS_PCT = 0.05  # Increased to 5% because futures are more volatile
MAX_HOLD_BARS = 5

def send_telegram(text: str):
    """Send HTML-formatted Telegram message."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[WARN] Telegram failed: {e}")

# ─── Exchange Setup ──────────────────────────────────────────────
def get_exchange():
    exchange = ccxt.bybit({
        "apiKey": FUTURES_TESTNET_API_KEY,
        "secret": FUTURES_TESTNET_API_SECRET,
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},  # Bybit uses 'swap' for USDT Perpetuals
    })
    exchange.set_sandbox_mode(True)
    
    # Try to set leverage on startup
    try:
        exchange.load_markets()
        exchange.set_leverage(LEVERAGE, SYMBOL)
        print(f"[SETUP] Leverage successfully set to {LEVERAGE}x on Bybit")
    except Exception as e:
        print(f"[WARN] Could not set leverage on Bybit (might already be set): {e}")
        
    return exchange

def get_current_price(exchange):
    ticker = exchange.fetch_ticker(SYMBOL)
    return float(ticker["last"])

def get_balance(exchange):
    try:
        balance = exchange.fetch_balance()
        return float(balance.get("USDT", {}).get("free", 0.0))
    except Exception as e:
        print(f"[WARN] Failed to fetch balance: {e}")
        return 0.0

def fetch_1m_candles(exchange, limit=100):
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df.set_index("ts", inplace=True)
    return df

# ─── Position Tracking ───────────────────────────────────────────
class ScalpPosition:
    def __init__(self):
        self.is_open = False
        self.side = None
        self.entry_price = 0.0
        self.margin_usd = 0.0
        self.total_size_usd = 0.0
        self.btc_qty = 0.0
        self.stop_loss = 0.0
        self.take_profit = 0.0
        self.bars_held = 0
        
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.consecutive_losses = 0

    def open(self, side, price, margin_usd, total_size_usd, qty, stop_loss, take_profit):
        self.is_open = True
        self.side = side
        self.entry_price = price
        self.margin_usd = margin_usd
        self.total_size_usd = total_size_usd
        self.btc_qty = qty
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.bars_held = 0

    def check_exit(self, current_price):
        """Returns reason string if exit condition met, else None."""
        if not self.is_open:
            return None
            
        if self.side == "long":
            if current_price <= self.stop_loss:
                return "stop_loss"
            if current_price >= self.take_profit:
                return "take_profit"
                
        self.bars_held += 1
        if self.bars_held >= MAX_HOLD_BARS:
            return "max_hold"
            
        return None

    def close(self, exit_price, exit_reason=""):
        # PnL calculation based on total leveraged size
        price_change_pct = (exit_price - self.entry_price) / self.entry_price
        
        if self.side == "long":
            pnl_usd = price_change_pct * self.total_size_usd
        else:
            pnl_usd = -price_change_pct * self.total_size_usd
            
        # ROI on margin (account impact)
        roi_pct = (pnl_usd / self.margin_usd) * 100 if self.margin_usd > 0 else 0
        
        self.daily_pnl += pnl_usd
        self.daily_trades += 1

        if pnl_usd < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        result = {
            "entry": self.entry_price,
            "exit": exit_price,
            "roi_pct": round(roi_pct, 4),
            "pnl_usd": round(pnl_usd, 4),
            "bars_held": self.bars_held,
            "reason": exit_reason
        }
        
        # Log to CSV
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        csv_file = log_dir / "trade_history.csv"
        
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        is_new_file = not csv_file.exists()
        
        try:
            with open(csv_file, "a") as f:
                if is_new_file:
                    f.write("Timestamp,Side,Entry,Exit,ROI_Pct,PnL_USD,Bars_Held,Reason\n")
                f.write(f"{timestamp},{self.side},{self.entry_price},{exit_price},{result['roi_pct']},{result['pnl_usd']},{self.bars_held},{exit_reason}\n")
        except Exception as e:
            print(f"[WARN] Failed to write to CSV log: {e}")

        self.is_open = False
        self.entry_price = 0.0
        self.margin_usd = 0.0
        self.total_size_usd = 0.0
        self.btc_qty = 0.0
        self.bars_held = 0
        return result

# ─── Main Loop ───────────────────────────────────────────────────
def main():
    print(f"\n🚀 Starting 1m Futures Leveraged Scalper ({LEVERAGE}x)...")
    exchange = get_exchange()
    predictor = ScalpPredictor()
    pos = ScalpPosition()
    
    send_telegram(
        f"⚡ <b>FUTURES Scalper Started</b>\n"
        f"Mode: Paper Trading (Futures)\n"
        f"Leverage: {LEVERAGE}x\n"
        f"Cycle: Every 60s\n"
        f"SL: 0.15% | TP: 0.30%\n"
        f"Max Hold: {MAX_HOLD_BARS} mins\n"
        f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    last_bar = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            current_minute = now.replace(second=0, microsecond=0)

            if current_minute != last_bar:
                time.sleep(2)  # Let candle close
                
                balance = get_balance(exchange)
                price = get_current_price(exchange)
                now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S")

                # 1. Manage existing position
                if pos.is_open:
                    exit_reason = pos.check_exit(price)
                    if exit_reason:
                        # Close the position in Futures (reduceOnly=True for safety)
                        try:
                            # If long, sell to close
                            order = exchange.create_market_order(
                                SYMBOL, 'sell', pos.btc_qty, params={"reduceOnly": True}
                            )
                            fill_price = float(order.get("average", price) or price)
                        except Exception as e:
                            print(f"[ERROR] Failed to close futures trade: {e}")
                            fill_price = price
                            
                        result = pos.close(fill_price, exit_reason)
                        emoji = "💰" if result["pnl_usd"] > 0 else "💸"
                        
                        msg = (
                            f"{emoji} <b>Futures Scalp Closed</b> ({exit_reason})\n"
                            f"Entry: ${result['entry']:,.2f} → Exit: ${result['exit']:,.2f}\n"
                            f"ROI: <b>{result['roi_pct']:+.2f}%</b> (${result['pnl_usd']:+.2f})\n"
                            f"Held: {result['bars_held']} min | Daily PnL: ${pos.daily_pnl:+.2f}"
                        )
                        print(f"[{now_utc}] {emoji} CLOSED SCALP | {exit_reason} | ROI: {result['roi_pct']:+.2f}% (${result['pnl_usd']:+.2f})")
                        send_telegram(msg)
                        last_bar = current_minute
                        continue

                # 2. Check safety limits
                if pos.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                    print(f"[{now_utc}] 🛑 Max consecutive losses ({MAX_CONSECUTIVE_LOSSES}). Cooling down for 1 hour.")
                    send_telegram(f"🛑 <b>Cooling Down!</b>\nHit {MAX_CONSECUTIVE_LOSSES} losses in a row. Pausing for 1 hr.")
                    time.sleep(3600)
                    pos.consecutive_losses = 0
                    continue

                if pos.daily_pnl <= -(balance * MAX_DAILY_LOSS_PCT) and balance > 0:
                    print(f"[{now_utc}] 🛑 Circuit breaker hit. Lost >{MAX_DAILY_LOSS_PCT*100}% of balance today.")
                    send_telegram(f"🛑 <b>Circuit Breaker Hit!</b>\nLost >{MAX_DAILY_LOSS_PCT*100}% today. Stopping bot.")
                    time.sleep(86400)
                    continue

                # 3. Fetch data & predict
                df = fetch_1m_candles(exchange)
                df = add_features_1m(df)
                
                nan_count = df.iloc[-2].isna().sum()
                if nan_count > 0:
                    print(f"[{now_utc}] ⏳ Warming up features... (NaN detected)")
                    last_bar = current_minute
                    continue

                latest_features = df.iloc[-2].copy()
                p_up = predictor.predict(latest_features)

                # 4. Decision
                decision = decide_scalp(p_up)
                
                if decision["action"] == "BUY" and not pos.is_open:
                    margin_usd = balance * MARGIN_PCT
                    total_size_usd = margin_usd * LEVERAGE
                    qty = round(total_size_usd / price, 4)
                    
                    if qty > 0:
                        try:
                            order = exchange.create_market_buy_order(SYMBOL, qty)
                            fill_price = float(order.get("average", price) or price)
                            
                            sl_price = fill_price * (1 - decision["stop_loss"])
                            tp_price = fill_price * (1 + decision["take_profit"])
                            
                            pos.open(
                                side="long",
                                price=fill_price,
                                margin_usd=margin_usd,
                                total_size_usd=total_size_usd,
                                qty=qty,
                                stop_loss=sl_price,
                                take_profit=tp_price
                            )
                            
                            msg = (
                                f"⚡ <b>FUTURES BUY @ ${fill_price:,.2f}</b>\n"
                                f"Margin: ${margin_usd:,.2f} | Size: ${total_size_usd:,.2f} ({qty} BTC)\n"
                                f"Leverage: {LEVERAGE}x\n"
                                f"SL: ${sl_price:,.2f} | TP: ${tp_price:,.2f}\n"
                                f"P(up): {p_up:.3f}"
                            )
                            print(f"[{now_utc}] ⚡ OPENED FUTURES SCALP | Size: ${total_size_usd:,.2f} | P(up): {p_up:.3f}")
                            send_telegram(msg)
                        except Exception as e:
                            print(f"[{now_utc}] ❌ Failed to open futures trade: {e}")
                else:
                    print(f"[{now_utc}] BTC: ${price:,.2f} | P(up): {p_up:.3f} | {decision['action']} — {decision['reason']}")

                last_bar = current_minute

            time.sleep(1)

        except Exception as e:
            print(f"\n[FATAL] Error in main loop: {e}")
            traceback.print_exc()
            time.sleep(60)

if __name__ == "__main__":
    main()
