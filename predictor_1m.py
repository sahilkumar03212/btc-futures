"""
XGBoost Scalper Predictor — Loads model from models/ directory
"""
from pathlib import Path
from xgboost import XGBClassifier

MODEL_PATH = Path(__file__).parent / "models" / "xgb_scalper_1m.json"


class ScalpPredictor:
    def __init__(self):
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"Model file not found at {MODEL_PATH}")

        print(f"Loading Scalper Model from {MODEL_PATH}...")
        self.model = XGBClassifier()
        self.model.load_model(str(MODEL_PATH))
        print("✓ Scalper Model loaded successfully.")

    def predict(self, feature_df):
        """
        Takes the feature dataframe, extracts the latest bar,
        and returns P(up) probability.
        """
        latest_features = feature_df.iloc[[-1]]
        p_up = float(self.model.predict_proba(latest_features)[0, 1])
        return p_up
