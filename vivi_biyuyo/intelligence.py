from __future__ import annotations
import math
from collections import defaultdict, deque
from dataclasses import dataclass


def clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def wallet_row_quality(row: dict, limit: int = 100) -> float:
    rank = max(1, int(row.get("rank") or limit))
    rank_score = clip(1 - (rank - 1) / max(1, limit - 1))
    pnl = float(row.get("pnlUsd") or 0)
    volume = max(1, float(row.get("volumeUsd") or 0))
    pnl_score = (math.tanh(max(-3, min(3, pnl / max(1000, volume * 0.10)))) + 1) / 2
    trades = max(0, int(row.get("trades") or 0))
    activity = clip(math.log1p(trades) / math.log1p(100))
    verified = 1 if row.get("verified") else 0
    return round(
        clip(0.45 * rank_score + 0.35 * pnl_score + 0.15 * activity + 0.05 * verified),
        4,
    )


class WalletUniverse:
    def __init__(self):
        self.wallets = {}

    def update(self, b7: dict, b30: dict, limit: int):
        merged = {}
        for window, payload, weight in (("7d", b7, 0.6), ("30d", b30, 0.4)):
            for row in payload.get("traders", []) if isinstance(payload, dict) else []:
                uid = str(row.get("userId") or "")
                if not uid:
                    continue
                node = merged.setdefault(
                    uid,
                    {
                        "userId": uid,
                        "handle": row.get("handle") or uid,
                        "scores": {},
                        "score": 0.0,
                    },
                )
                q = wallet_row_quality(row, limit)
                node["scores"][window] = q
                node["score"] += weight * q
                node["rank_" + window] = int(row.get("rank") or limit)
                node["pnl_" + window] = float(row.get("pnlUsd") or 0)
        for node in merged.values():
            w = sum(0.6 if k == "7d" else 0.4 for k in node["scores"])
            node["score"] = round(node["score"] / w, 4) if w else 0
        self.wallets = merged

    def quality(self, uid):
        return float(self.wallets.get(str(uid), {}).get("score", 0))

    def top(self, n=20):
        return sorted(self.wallets.values(), key=lambda x: x["score"], reverse=True)[:n]


@dataclass(frozen=True)
class Cluster:
    address: str
    symbol: str
    chain: str
    chain_id: int | None
    unique_traders: int
    total_usd: float
    average_quality: float
    max_quality: float
    first_ts: int
    last_ts: int


class ClusterEngine:
    def __init__(self, window_seconds=120):
        self.window_ms = window_seconds * 1000
        self.data = defaultdict(deque)

    def add(self, event: dict, quality: float):
        if event.get("side") != "buy" or not event.get("tokenAddress"):
            return None
        ts = int(event["ts"])
        key = f"{event.get('chainId')}:{event['tokenAddress']}"
        q = self.data[key]
        q.append(
            {
                "uid": event.get("userId") or event.get("trader"),
                "usd": float(event.get("usdValue") or 0),
                "q": quality,
                "ts": ts,
            }
        )
        newest = max(x["ts"] for x in q)
        kept = sorted(
            (x for x in q if x["ts"] >= newest - self.window_ms), key=lambda x: x["ts"]
        )
        q.clear()
        q.extend(kept)
        for old_key in list(self.data):
            if (
                self.data[old_key]
                and max(x["ts"] for x in self.data[old_key]) < newest - self.window_ms
            ):
                del self.data[old_key]
        traders = {str(x["uid"]) for x in q if x["uid"]}
        return Cluster(
            str(event["tokenAddress"]),
            str(event.get("token") or "?"),
            str(event.get("chain") or "unknown"),
            int(event["chainId"]) if event.get("chainId") is not None else None,
            len(traders),
            sum(x["usd"] for x in q),
            sum(x["q"] for x in q) / len(q),
            max(x["q"] for x in q),
            q[0]["ts"],
            q[-1]["ts"],
        )


@dataclass(frozen=True)
class Guard:
    passed: bool
    flow_score: float
    safety_score: float
    holders: int | None
    top10: float | None
    ratio: float | None
    net: float | None
    dev_exit: bool
    reasons: tuple[str, ...]


def evaluate_guard(
    stats: dict, dev_payload, minimum_holders=100, max_top10=40, min_ratio=1.2
) -> Guard:
    holders = int(stats["holders"]) if stats.get("holders") is not None else None
    top10 = (
        float(stats["top10HoldersPercent"])
        if stats.get("top10HoldersPercent") is not None
        else None
    )
    five = (stats.get("windows") or {}).get("5m") or {}
    ratio = (
        float(five["buySellRatio"]) if five.get("buySellRatio") is not None else None
    )
    net = float(five["netVolumeUsd"]) if five.get("netVolumeUsd") is not None else None
    if top10 is not None and (not math.isfinite(top10) or not 0 <= top10 <= 100):
        top10 = None
    if ratio is not None and (not math.isfinite(ratio) or ratio < 0):
        ratio = None
    if net is not None and not math.isfinite(net):
        net = None
    if isinstance(dev_payload, list):
        devs = dev_payload
    elif isinstance(dev_payload, dict):
        devs = next(
            (
                dev_payload[k]
                for k in ("devs", "holders", "data")
                if isinstance(dev_payload.get(k), list)
            ),
            [],
        )
    else:
        devs = []
    dev_exit = any(
        float(x.get("realizedPnlUsd") or 0) > 0 and float(x.get("amount") or 0) <= 0
        for x in devs
    )
    reasons = []
    if not devs or any(
        not isinstance(x, dict) or x.get("amount") is None for x in devs
    ):
        reasons.append("dev_data_unknown")
    if holders is None:
        reasons.append("holders_unknown")
    elif holders < minimum_holders:
        reasons.append("too_few_holders")
    if top10 is None:
        reasons.append("top10_unknown")
    elif top10 > max_top10:
        reasons.append("holder_concentration")
    if ratio is None:
        reasons.append("flow_ratio_unknown")
    elif ratio < min_ratio:
        reasons.append("weak_buy_sell_ratio")
    if net is None:
        reasons.append("net_flow_unknown")
    elif net <= 0:
        reasons.append("negative_net_flow")
    if dev_exit:
        reasons.append("dev_exit_risk")
    safety = round(
        (
            (0 if holders is None else min(1, holders / max(1, minimum_holders * 4)))
            + (
                0
                if top10 is None
                else max(0, min(1, (max_top10 - top10) / max(1, max_top10) + 0.5))
            )
            + (0 if dev_exit else 0.8 if devs else 0.5)
        )
        / 3,
        4,
    )
    flow = round(
        0.65 * (0 if ratio is None else min(1, ratio / max(min_ratio * 2, 0.01)))
        + 0.35 * (0 if net is None or net <= 0 else min(1, net / 20000)),
        4,
    )
    return Guard(
        not reasons, flow, safety, holders, top10, ratio, net, dev_exit, tuple(reasons)
    )
