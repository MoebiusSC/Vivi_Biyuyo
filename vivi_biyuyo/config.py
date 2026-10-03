from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Config:
    api_key: str
    stream_mode: str
    state_dir: Path
    port: int
    leaderboard_limit: int
    wallet_refresh_seconds: int
    cluster_window_seconds: int
    min_cluster_traders: int
    min_alert_usd: float
    signal_threshold: float
    max_top10_percent: float
    min_holders: int
    min_buy_sell_ratio: float

    @classmethod
    def from_env(cls):
        mode=os.environ.get("VIVI_STREAM_MODE","alerts").strip().lower()
        if mode not in {"alerts","trades"}:
            raise ValueError("VIVI_STREAM_MODE must be alerts or trades")
        return cls(
            api_key=os.environ.get("FOMO_API_KEY","").strip(),
            stream_mode=mode,
            state_dir=Path(os.environ.get("VIVI_STATE_DIR","state/vivi_biyuyo")),
            port=int(os.environ.get("VIVI_PORT","8080")),
            leaderboard_limit=max(10,min(150,int(os.environ.get("VIVI_LEADERBOARD_LIMIT","100")))),
            wallet_refresh_seconds=max(300,int(os.environ.get("VIVI_WALLET_REFRESH_SECONDS","1800"))),
            cluster_window_seconds=max(15,int(os.environ.get("VIVI_CLUSTER_WINDOW_SECONDS","120"))),
            min_cluster_traders=max(2,int(os.environ.get("VIVI_MIN_CLUSTER_TRADERS","2"))),
            min_alert_usd=max(0,float(os.environ.get("VIVI_MIN_ALERT_USD","250"))),
            signal_threshold=max(0,min(1,float(os.environ.get("VIVI_SIGNAL_THRESHOLD",".70")))),
            max_top10_percent=max(0,min(100,float(os.environ.get("VIVI_MAX_TOP10_PERCENT","40")))),
            min_holders=max(0,int(os.environ.get("VIVI_MIN_HOLDERS","100"))),
            min_buy_sell_ratio=max(0,float(os.environ.get("VIVI_MIN_BUY_SELL_RATIO","1.20"))),
        )
