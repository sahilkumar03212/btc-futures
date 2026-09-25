import os
import time
import json
import requests
import pandas as pd
import ccxt
from datetime import datetime, timezone
from pathlib import Path

from features_1m import build_scalp_features
from predictor_1m import ScalpPredictor
from decision_1m import decide_scalp

# ─── Configuration ──────────────────────────────────────────────
SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"
LEVERAGE = 10
MARGIN_PCT = 0.02       # 2% of total balance per trade
TAKER_FEE = 0.0005      # 0.05% market order fee
STATE_FILE = "paper_state.json"
TRADE_LOG = "main_data/paper_trade_history.csv"

# Telegram settings
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── Telegram Alerts ─────────────────────────────────────────────
def send_telegram_message(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram credentials not set. Message:", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[ERROR] Failed to send Telegram message: {e}")

# ─── Paper Trading Engine ────────────────────────────────────────
class PaperTradingEngine:
    def __init__(self, initial_balance=10000.0):
        self.state = {
            "balance": initial_balance,
            "position": None,
            "trades": []
        }
        self.load_state()
        
    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    self.state = json.load(f)
            except Exception as e:
                print(f"[WARN] Could not load state: {e}")
                
    def save_state(self):
        with open(STATE_FILE, "w") as f:
            json.dump(self.state, f, indent=4)
            
    def get_balance(self):
        return self.state["balance"]
        
    def get_position(self):
        return self.state["position"]
        
    def open_long(self, current_price):
        if self.state["position"] is not None:
            return None
            
        balance = self.state["balance"]
        margin_used = balance * MARGIN_PCT
        position_size_usd = margin_used * LEVERAGE
        position_size_btc = position_size_usd / current_price
        
        # Deduct opening fee
        fee = position_size_usd * TAKER_FEE
        self.state["balance"] -= fee
        
        self.state["position"] = {
            "side": "LONG",
            "entry_price": current_price,
            "size_usd": position_size_usd,
            "size_btc": position_size_btc,
            "margin_used": margin_used,
            "entry_time": datetime.now(timezone.utc).isoformat()
        }
        self.save_state()
        return self.state["position"], fee
        
    def close_long(self, current_price, reason=""):
        pos = self.state["position"]
        if pos is None:
            return None
            
        # PnL (Futures Math)
        price_diff = current_price - pos["entry_price"]
        pnl_usd = price_diff * pos["size_btc"]
        
        # Deduct closing fee
        fee = (pos["size_btc"] * current_price) * TAKER_FEE
        net_pnl = pnl_usd - fee
        
        # Update balance
        self.state["balance"] += net_pnl
        roi_pct = (net_pnl / pos["margin_used"]) * 100
        
        trade_record = {
            "entry_time": pos["entry_time"],
            "exit_time": datetime.now(timezone.utc).isoformat(),
            "side": pos["side"],
            "entry_price": pos["entry_price"],
            "exit_price": current_price,
            "leverage": LEVERAGE,
            "margin_used": pos["margin_used"],
            "size_usd": pos["size_usd"],
            "net_pnl": round(net_pnl, 4),
            "roi_pct": round(roi_pct, 2),
            "new_balance": round(self.state["balance"], 2),
            "reason": reason
        }
        
        self.state["trades"].append(trade_record)
        self.state["position"] = None
        self.save_state()
        self.log_to_csv(trade_record)
        return trade_record
        
    def log_to_csv(self, record):
        os.makedirs(os.path.dirname(TRADE_LOG), exist_ok=True)
        df = pd.DataFrame([record])
        file_exists = os.path.isfile(TRADE_LOG)
        df.to_csv(TRADE_LOG, mode='a', header=not file_exists, index=False)

# ─── Data Fetching (Public API) ──────────────────────────────────
def fetch_1m_candles(exchange, limit=100):
    ohlcv = exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df

def get_current_price(exchange):
    ticker = exchange.fetch_ticker(SYMBOL)
    return ticker['last']

# ─── Main Loop ───────────────────────────────────────────────────
def main():
    print("Starting Paper Trading Simulator (1m Scalper, 10x Leverage)...")
    send_telegram_message("⚡ <b>FUTURES PAPER TRADER STARTED</b>\nExchange: Local Simulator\nLeverage: 10x")
    
    # Use public Binance API for free live price data (no keys needed!)
    exchange = ccxt.binance({"enableRateLimit": True})
    engine = PaperTradingEngine(initial_balance=10000.0)
    predictor = ScalpPredictor()
    
    last_processed_minute = None
    
    while True:
        try:
            now = datetime.now(timezone.utc)
            
            if now.second == 2 and now.minute != last_processed_minute:
                last_processed_minute = now.minute
                
                # 1. Check current price
                current_price = get_current_price(exchange)
                pos = engine.get_position()
                
                # 2. Risk Management (Stop Loss / Take Profit / Max Hold)
                if pos is not None:
                    entry_time = datetime.fromisoformat(pos["entry_time"])
                    minutes_held = (now - entry_time).total_seconds() / 60.0
                    
                    roi = ((current_price - pos["entry_price"]) / pos["entry_price"]) * LEVERAGE * 100
                    
                    exit_reason = None
                    if roi <= -10.0:
                        exit_reason = "Stop Loss (-10% ROI)"
                    elif roi >= 15.0:
                        exit_reason = "Take Profit (+15% ROI)"
                    elif minutes_held >= 5:
                        exit_reason = "Max Hold Time Reached (5m)"
                        
                    if exit_reason:
                        trade = engine.close_long(current_price, exit_reason)
                        msg = (f"📉 <b>POSITION CLOSED</b>\n"
                               f"Reason: {exit_reason}\n"
                               f"Entry: ${trade['entry_price']:.2f}\n"
                               f"Exit: ${trade['exit_price']:.2f}\n"
                               f"Net PnL: ${trade['net_pnl']:.2f} ({trade['roi_pct']}%)\n"
                               f"New Balance: ${trade['new_balance']:.2f}")
                        print(msg)
                        send_telegram_message(msg)
                        continue # Skip ML evaluation for this minute since we just closed

                # 3. Fetch data & ML prediction
                df = fetch_1m_candles(exchange)
                df = build_scalp_features(df)
                
                nan_count = df.iloc[-2].isna().sum()
                if nan_count > 0:
                    continue
                    
                prob = predictor.predict(df)
                has_pos = (pos is not None)
                action = decide_scalp(prob, current_price, has_open_position=has_pos)
                
                print(f"[{now.strftime('%H:%M:%S')}] Price: ${current_price:.2f} | Prob: {prob:.4f} | Action: {action} | Balance: ${engine.get_balance():.2f}")
                
                # 4. Open Position
                if action == "BUY" and pos is None:
                    new_pos, fee = engine.open_long(current_price)
                    msg = (f"🚀 <b>LONG OPENED</b>\n"
                           f"Price: ${current_price:.2f}\n"
                           f"Size: ${new_pos['size_usd']:.2f} (10x)\n"
                           f"Margin Used: ${new_pos['margin_used']:.2f}\n"
                           f"ML Confidence: {prob*100:.1f}%\n"
                           f"Fee Deducted: ${fee:.2f}")
                    print(msg)
                    send_telegram_message(msg)

        except Exception as e:
            print(f"[ERROR] Main loop error: {e}")
            
        time.sleep(1)

if __name__ == "__main__":
    main()
