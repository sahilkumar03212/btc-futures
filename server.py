"""
Web Server Wrapper for Render.com — Futures Leveraged Bot
"""
import os
import sys
import threading
import traceback
from datetime import datetime, timezone
from flask import Flask, jsonify, send_file
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import futures_bot

app = Flask(__name__)

bot_status = {"state": "starting", "last_error": None, "started_at": None}


def run_bot_with_recovery():
    """Run the futures bot with automatic restart on crash."""
    import time
    bot_status["started_at"] = datetime.now(timezone.utc).isoformat()

    while True:
        try:
            bot_status["state"] = "running"
            futures_bot.main()
        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            bot_status["state"] = "crashed"
            bot_status["last_error"] = error_msg
            print(f"\n[FATAL] Futures bot crashed: {error_msg}")
            traceback.print_exc()
            try:
                futures_bot.send_telegram(f"⚠️ <b>Futures Bot Crashed!</b>\nRestarting in 30s...\n{error_msg}")
            except Exception:
                pass
            print("[RECOVERY] Restarting in 30 seconds...")
            time.sleep(30)


bot_thread = threading.Thread(target=run_bot_with_recovery, daemon=True)
bot_thread.start()


@app.route('/')
def home():
    return jsonify({
        "status": bot_status["state"],
        "bot": "BTC Futures Scalper (1m, Leveraged)",
        "started_at": bot_status["started_at"],
        "last_error": bot_status["last_error"],
        "download_logs": "/download-logs"
    })

@app.route('/download-logs')
def download_logs():
    """Allows the user to download the CSV trade history."""
    log_path = Path(__file__).parent / "logs" / "trade_history.csv"
    if log_path.exists():
        return send_file(log_path, as_attachment=True)
    else:
        return jsonify({"error": "No trades have been recorded yet."}), 404


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
