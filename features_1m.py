"""
Scalping Feature Calculator — Pure Pandas (Matches Colab training exactly)
"""
import pandas as pd
import numpy as np


def calculate_rsi(series, window):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=window - 1, adjust=False).mean()
    ema_down = down.ewm(com=window - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))


def build_scalp_features(df):
    """
    Computes features on 1-minute candles.
    Input df must have columns: ['open', 'high', 'low', 'close', 'volume']
    """
    df = df.copy()

    # Micro RSI
    df["rsi_5"] = calculate_rsi(df["close"], 5)
    df["rsi_14"] = calculate_rsi(df["close"], 14)

    # Bollinger Bands
    sma_20 = df["close"].rolling(window=20).mean()
    std_20 = df["close"].rolling(window=20).std()
    bb_lower = sma_20 - (std_20 * 2)
    bb_upper = sma_20 + (std_20 * 2)
    df["bb_width"] = (bb_upper - bb_lower) / sma_20 * 100

    # Daily VWAP (Resets every day at midnight UTC)
    df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
    if hasattr(df.index, 'date'):
        dates = df.index.date
    else:
        dates = pd.to_datetime(df['timestamp']).dt.date
        
    cum_vol_price = (df["typical_price"] * df["volume"]).groupby(dates).cumsum()
    cum_vol = df["volume"].groupby(dates).cumsum()
    df["vwap"] = cum_vol_price / cum_vol
    df["dist_to_vwap"] = (df["close"] - df["vwap"]) / df["vwap"]

    # Volume Spikes
    vol_sma_20 = df["volume"].rolling(20).mean()
    df["vol_spike"] = df["volume"] / vol_sma_20

    # Momentum
    df["ret_1m"] = df["close"].pct_change(1)
    df["ret_5m"] = df["close"].pct_change(5)

    features = ["rsi_5", "rsi_14", "bb_width", "dist_to_vwap", "vol_spike", "ret_1m", "ret_5m"]
    return df[features]
