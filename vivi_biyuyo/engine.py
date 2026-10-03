from __future__ import annotations
import asyncio, time, os, logging
from .collector import collect
from .journal import Journal
from .quotes import observe
import math
from .trading import PaperTrader
from .research import record_latency
from collections import deque
from .config import Config
from .intelligence import WalletUniverse, ClusterEngine, evaluate_guard
from .strategies import lanes
from .fomo import FomoClient
from .storage import read_json, write_json, append_jsonl


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.root = cfg.state_dir
        self.state_path = self.root / "state.json"
        self.events_path = self.root / "events.jsonl"
        self.signals_path = self.root / "signals.jsonl"
        self.journal = Journal(self.root)
        self.state = (
            self.journal.load()
            or read_json(self.state_path, None)
            or {
                "version": 1,
                "name": "Vivi Biyuyo",
                "mode": "shadow",
                "status": "STARTING",
                "started_ms": int(time.time() * 1000),
                "events": 0,
                "duplicates": 0,
                "candidates": 0,
                "signals": 0,
                "errors": 0,
                "wallet_count": 0,
                "top_wallets": [],
                "lane_counts": {"A": 0, "B": 0, "C": 0, "D": 0},
                "recent_signals": [],
                "stream": {},
            }
        )
        self.state.update(
            status="STARTING",
            mode=os.environ.get("VIVI_MODE", "shadow"),
            live_execution=False,
        )
        self.state["last_tick_ms"] = int(time.time() * 1000)
        self.paper = PaperTrader(self.state.setdefault("paper", {}))
        self.queue = asyncio.Queue(maxsize=1000)
        self.client = FomoClient(cfg.api_key) if cfg.api_key else None
        self.wallets = WalletUniverse()
        self.wallets.wallets = self.state.get("wallet_universe", {})
        self.clusters = ClusterEngine(cfg.cluster_window_seconds)
        for key, rows in self.state.get("clusters", {}).items():
            self.clusters.data[key].extend(rows)
        self.ids = deque(self.state.get("recent_ids", [])[-5000:], maxlen=5000)
        self.idset = set(self.ids)
        self.last_wallet_refresh = 0
        self.guard_cache = {}

    def save(self):
        self.state["wallet_universe"] = self.wallets.wallets
        self.state["clusters"] = {k: list(v) for k, v in self.clusters.data.items()}
        self.state["recent_ids"] = list(self.ids)
        self.journal.save(self.state)
        if self.journal.active is None:
            write_json(self.state_path, self.state)

    def dedupe(self, eid):
        if not eid:
            return False
        if self.journal.seen(eid):
            self.state["duplicates"] += 1
            return True
        if len(self.ids) == self.ids.maxlen and self.ids:
            self.idset.discard(self.ids[0])
        self.ids.append(eid)
        self.idset.add(eid)
        return False

    async def refresh_wallets(self):
        b7, b30 = await asyncio.gather(
            self.client.leaderboard("7d", self.cfg.leaderboard_limit),
            self.client.leaderboard("30d", self.cfg.leaderboard_limit),
        )
        self.wallets.update(b7, b30, self.cfg.leaderboard_limit)
        self.last_wallet_refresh = time.time()
        self.state["wallet_count"] = len(self.wallets.wallets)
        self.state["top_wallets"] = self.wallets.top()
        self.state["wallet_refresh_ms"] = int(self.last_wallet_refresh * 1000)
        self.save()

    @staticmethod
    def normalize(raw):
        if raw.get("type") == "alert":
            side = raw.get("alertType")
            if side not in {"buy", "sell"}:
                return None
            return {
                "eventId": raw.get("eventId"),
                "tradeId": raw.get("tradeId"),
                "userId": raw.get("userId"),
                "trader": raw.get("trader"),
                "token": raw.get("token"),
                "tokenAddress": raw.get("tokenAddress"),
                "chainId": raw.get("chainId"),
                "chain": raw.get("chain"),
                "side": side,
                "usdValue": float(raw.get("usdValue") or 0),
                "ts": int(raw.get("ts") or time.time() * 1000),
                "source": raw.get("source", "feed"),
            }
        if raw.get("txHash") or raw.get("type") in {"trade", "swap"}:
            side = str(raw.get("side") or "").lower()
            if side not in {"buy", "sell"}:
                return None
            return {
                "eventId": raw.get("eventId") or raw.get("txHash"),
                "tradeId": raw.get("tradeId"),
                "userId": raw.get("userId"),
                "trader": raw.get("trader") or raw.get("handle"),
                "token": raw.get("token") or raw.get("symbol"),
                "tokenAddress": raw.get("tokenAddress") or raw.get("address"),
                "chainId": raw.get("chainId"),
                "chain": raw.get("chain"),
                "side": side,
                "usdValue": float(raw.get("usdValue") or raw.get("valueUsd") or 0),
                "ts": int(raw.get("ts") or time.time() * 1000),
                "source": "onchain",
            }

    async def get_guard(self, event):
        key = f"{event.get('chainId')}:{event['tokenAddress']}"
        cached = self.guard_cache.get(key)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        network = int(event["chainId"]) if event.get("chainId") is not None else None
        stats, devs = await asyncio.gather(
            self.client.token_stats(event["tokenAddress"], network),
            self.client.token_devs(event["tokenAddress"], network),
        )
        g = evaluate_guard(
            stats,
            devs,
            self.cfg.min_holders,
            self.cfg.max_top10_percent,
            self.cfg.min_buy_sell_ratio,
        )
        if len(self.guard_cache) >= 1000:
            oldest = min(self.guard_cache, key=lambda k: self.guard_cache[k][0])
            del self.guard_cache[oldest]
        self.guard_cache[key] = (time.time(), g)
        return g

    async def handle(self, raw, received_ms=None):
        started = time.monotonic()
        received_ms = received_ms or int(time.time() * 1000)
        if raw.get("type") == "welcome":
            self.state["stream"] = {
                "mode": self.cfg.stream_mode,
                "realtime": raw.get("realtime"),
                "delaySeconds": raw.get("delaySeconds"),
            }
            self.state["status"] = "SHADOW_RUNNING"
            self.save()
            return
        if raw.get("type") == "stream_error":
            self.state["errors"] += 1
            self.state["stream"]["last_error"] = raw.get("error")
            self.state["status"] = "STREAM_RECONNECTING"
            self.save()
            return
        try:
            e = self.normalize(raw)
        except (ValueError, TypeError, OverflowError):
            self.record("rejected", {"reason": "invalid_numeric_event"})
            return
        if e and (not math.isfinite(e["usdValue"]) or e["usdValue"] < 0):
            self.record("rejected", {"reason": "invalid_usd"})
            return
        if (
            not e
            or not e.get("tokenAddress")
            or (e["side"] == "buy" and e["usdValue"] < self.cfg.min_alert_usd)
        ):
            return
        if not e.get("eventId") or not e.get("userId"):
            return
        e["priceUsd"] = raw.get("priceUsd")
        e["received_ms"] = received_ms
        self.state["latency"] = record_latency(self.root, e, received_ms, started)
        if self.dedupe(str(e.get("eventId") or "")):
            self.save()
            return
        q = self.wallets.quality(e.get("userId"))
        e["wallet_quality"] = q
        self.record("events", e)
        self.state["events"] += 1
        cluster = self.clusters.add(e, q)
        if e["side"] != "buy" or not cluster:
            await self.paper_trade(e, {})
            self.save()
            return
        pre = lanes(cluster, None, self.cfg.min_cluster_traders)
        if not (pre["A"]["triggered"] or pre["B"]["triggered"]):
            self.save()
            return
        self.state["candidates"] += 1
        guard = None
        try:
            guard = await self.get_guard(e)
        except Exception as exc:
            self.state["errors"] += 1
            self.state["last_guard_error"] = type(exc).__name__
        out = lanes(cluster, guard, self.cfg.min_cluster_traders)
        triggered = [x for x in out.values() if x["triggered"]]
        best = max((x["score"] for x in triggered), default=0)
        if best >= self.cfg.signal_threshold:
            rec = {
                "ts": int(time.time() * 1000),
                "token": cluster.symbol,
                "tokenAddress": cluster.address,
                "chain": cluster.chain,
                "chainId": cluster.chain_id,
                "uniqueTraders": cluster.unique_traders,
                "clusterUsd": round(cluster.total_usd, 2),
                "avgWalletQuality": round(cluster.average_quality, 4),
                "maxWalletQuality": round(cluster.max_quality, 4),
                "score": best,
                "lanes": out,
                "execution": "shadow",
                "guard": None
                if not guard
                else {
                    "passed": guard.passed,
                    "flowScore": guard.flow_score,
                    "safetyScore": guard.safety_score,
                    "holders": guard.holders,
                    "top10Percent": guard.top10,
                    "buySellRatio": guard.ratio,
                    "netVolumeUsd": guard.net,
                    "devExitRisk": guard.dev_exit,
                    "reasons": list(guard.reasons),
                },
            }
            self.record("signals", rec)
            self.state["signals"] += 1
            self.state["recent_signals"] = ([rec] + self.state["recent_signals"])[:50]
            for lane, item in out.items():
                if item["triggered"]:
                    self.state["lane_counts"][lane] = (
                        self.state["lane_counts"].get(lane, 0) + 1
                    )
        await self.paper_trade(e, out)
        self.save()

    def record(self, kind, payload):
        self.journal.record(kind, payload)

    async def paper_trade(self, event, decisions):
        if self.state["mode"] == "paper":
            age = time.time() * 1000 - event["ts"]
            if age > 120000 or age < -10000:
                self.state["paper_stale_events"] = (
                    self.state.get("paper_stale_events", 0) + 1
                )
                return
            if event.get("priceUsd") is None and self.client:
                key = f"{event.get('chainId')}:{event['tokenAddress']}"
                needed = any(
                    d.get("triggered")
                    and d.get("score", 0) >= self.cfg.signal_threshold
                    for d in decisions.values()
                ) or any(key in p["positions"] for p in self.paper.state.values())
                if needed:
                    try:
                        quote = await observe(self.client, event)
                        if quote:
                            event.update(quote)
                            self.record(
                                "market_data",
                                dict(
                                    quote,
                                    chainId=event.get("chainId"),
                                    tokenAddress=event["tokenAddress"],
                                ),
                            )
                    except Exception as exc:
                        self.state["last_quote_error"] = type(exc).__name__
            if not event.get("priceUsd"):
                self.state["paper_missing_quote"] = (
                    self.state.get("paper_missing_quote", 0) + 1
                )
            for trade in self.paper.transact(
                event, decisions, self.cfg.signal_threshold
            ):
                self.record("trades", trade)

    async def heartbeat(self):
        while True:
            self.state["last_tick_ms"] = int(time.time() * 1000)
            self.state["queue_depth"] = self.queue.qsize()
            self.save()
            await asyncio.sleep(5)

    async def refresh_loop(self):
        while True:
            try:
                await self.refresh_wallets()
            except Exception as exc:
                self.state["errors"] += 1
                self.state["last_wallet_error"] = type(exc).__name__
                logging.getLogger(__name__).warning(
                    "wallet_refresh_failed: %s", type(exc).__name__
                )
            await asyncio.sleep(self.cfg.wallet_refresh_seconds)

    async def consume(self):
        while True:
            ident = await self.queue.get()
            item = self.journal.begin(ident)
            if item is None:
                self.queue.task_done()
                continue
            try:
                started = time.monotonic()
                await self.handle(*item)
                if self.state.get("latency", {}).get("eventId") == item[0].get(
                    "eventId"
                ) and item[0].get("eventId"):
                    self.state.setdefault("latency", {})["processing_ms"] = round(
                        (time.monotonic() - started) * 1000, 3
                    )
                    self.state["latency"]["queue_age_ms"] = (
                        int(time.time() * 1000) - item[1]
                    )
                    self.record("latency", self.state["latency"])
                pending = list(self.journal.pending)
                self.journal.finish(self.state)
                self.save()
                # JSONL is a convenience export; SQLite remains authoritative.
                import json

                for kind, payload in pending:
                    append_jsonl(self.root / (kind + ".jsonl"), json.loads(payload))
            except Exception as exc:
                self.state["errors"] += 1
                self.state["last_engine_error"] = type(exc).__name__
                logging.getLogger(__name__).error(
                    "event_processing_failed: %s", type(exc).__name__
                )
                self.journal.abort()
                self.state = self.journal.load() or self.state
                self.wallets.wallets = self.state.get("wallet_universe", {})
                self.clusters.data.clear()
                for key, rows in self.state.get("clusters", {}).items():
                    self.clusters.data[key].extend(rows)
                raise
            finally:
                self.queue.task_done()

    async def run(self):
        if not self.client:
            self.state["status"] = "WAITING_FOR_FOMO_API_KEY"
            self.save()
            await self.heartbeat()
        async with asyncio.TaskGroup() as group:
            group.create_task(self.refresh_loop())
            group.create_task(
                collect(
                    self.client,
                    self.cfg.stream_mode,
                    self.journal,
                    self.queue,
                    self.state,
                )
            )
            group.create_task(self.consume())
            group.create_task(self.heartbeat())

    async def close(self):
        if self.client:
            await self.client.close()
        self.journal.close()
