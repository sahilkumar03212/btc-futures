"""
Scalping Decision Layer — High confidence thresholding and tight risk metrics
"""

# Config threshold based on Colab validation
P_BUY_THRESHOLD = 0.62  # Requires > 62% confidence for a scalp buy
SL_PCT = 0.0015         # 0.15% Stop Loss (Tight protection)
TP_PCT = 0.0030         # 0.30% Take Profit (2:1 Reward:Risk)


def decide_scalp(p_up, current_price, has_open_position=False):
    """
    Formulates a scalp trade decision.
    """
    if has_open_position:
        return {
            "action": "HOLD",
            "reason": "Already in an active scalp position",
            "stop_loss": None,
            "take_profit": None
        }

    if p_up >= P_BUY_THRESHOLD:
        stop_loss = current_price * (1 - SL_PCT)
        take_profit = current_price * (1 + TP_PCT)
        return {
            "action": "BUY",
            "reason": f"High confidence P(up)={p_up:.3f} >= {P_BUY_THRESHOLD}",
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2)
        }
    else:
        return {
            "action": "HOLD",
            "reason": f"P(up)={p_up:.3f} below threshold {P_BUY_THRESHOLD}",
            "stop_loss": None,
            "take_profit": None
        }
