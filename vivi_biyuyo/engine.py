from __future__ import annotations
import asyncio,time
from collections import deque
from .config import Config
from .core import WalletUniverse,ClusterEngine,evaluate_guard,lanes
from .fomo import FomoClient,FomoError
from .storage import read_json,write_json,append_jsonl

class Engine:
    def __init__(self,cfg:Config):
        self.cfg=cfg; self.root=cfg.state_dir; self.state_path=self.root/"state.json"
        self.events_path=self.root/"events.jsonl"; self.signals_path=self.root/"signals.jsonl"
        self.state=read_json(self.state_path,None) or {"version":1,"name":"Vivi Biyuyo","mode":"shadow","status":"STARTING",
            "started_ms":int(time.time()*1000),"events":0,"duplicates":0,"candidates":0,"signals":0,"errors":0,
            "wallet_count":0,"top_wallets":[],"lane_counts":{"A":0,"B":0,"C":0,"D":0},"recent_signals":[],"stream":{}}
        self.client=FomoClient(cfg.api_key) if cfg.api_key else None; self.wallets=WalletUniverse()
        self.clusters=ClusterEngine(cfg.cluster_window_seconds); self.ids=deque(self.state.get("recent_ids",[])[-5000:],maxlen=5000)
        self.idset=set(self.ids); self.last_wallet_refresh=0; self.guard_cache={}
    def save(self):
        self.state["recent_ids"]=list(self.ids); write_json(self.state_path,self.state)
    def dedupe(self,eid):
        if not eid:return False
        if eid in self.idset:self.state["duplicates"]+=1;return True
        if len(self.ids)==self.ids.maxlen and self.ids:self.idset.discard(self.ids[0])
        self.ids.append(eid);self.idset.add(eid);return False
    async def refresh_wallets(self):
        b7,b30=await asyncio.gather(self.client.leaderboard("7d",self.cfg.leaderboard_limit),
                                   self.client.leaderboard("30d",self.cfg.leaderboard_limit))
        self.wallets.update(b7,b30,self.cfg.leaderboard_limit); self.last_wallet_refresh=time.time()
        self.state["wallet_count"]=len(self.wallets.wallets);self.state["top_wallets"]=self.wallets.top();self.state["wallet_refresh_ms"]=int(self.last_wallet_refresh*1000);self.save()
    @staticmethod
    def normalize(raw):
        if raw.get("type")=="alert":
            side=raw.get("alertType")
            if side not in {"buy","sell"}:return None
            return {"eventId":raw.get("eventId"),"tradeId":raw.get("tradeId"),"userId":raw.get("userId"),"trader":raw.get("trader"),
                    "token":raw.get("token"),"tokenAddress":raw.get("tokenAddress"),"chainId":raw.get("chainId"),"chain":raw.get("chain"),
                    "side":side,"usdValue":float(raw.get("usdValue") or 0),"ts":int(raw.get("ts") or time.time()*1000),"source":raw.get("source","feed")}
        if raw.get("txHash") or raw.get("type") in {"trade","swap"}:
            side=str(raw.get("side") or "").lower()
            if side not in {"buy","sell"}:return None
            return {"eventId":raw.get("eventId") or raw.get("txHash"),"tradeId":raw.get("tradeId"),"userId":raw.get("userId"),
                    "trader":raw.get("trader") or raw.get("handle"),"token":raw.get("token") or raw.get("symbol"),
                    "tokenAddress":raw.get("tokenAddress") or raw.get("address"),"chainId":raw.get("chainId"),"chain":raw.get("chain"),
                    "side":side,"usdValue":float(raw.get("usdValue") or raw.get("valueUsd") or 0),"ts":int(raw.get("ts") or time.time()*1000),"source":"onchain"}
    async def get_guard(self,event):
        key=f"{event.get('chainId')}:{event['tokenAddress']}";cached=self.guard_cache.get(key)
        if cached and time.time()-cached[0]<300:return cached[1]
        network=int(event["chainId"]) if event.get("chainId") is not None else None
        stats,devs=await asyncio.gather(self.client.token_stats(event["tokenAddress"],network),self.client.token_devs(event["tokenAddress"],network))
        g=evaluate_guard(stats,devs,self.cfg.min_holders,self.cfg.max_top10_percent,self.cfg.min_buy_sell_ratio);self.guard_cache[key]=(time.time(),g);return g
    async def handle(self,raw):
        if raw.get("type")=="welcome":
            self.state["stream"]={"mode":self.cfg.stream_mode,"realtime":raw.get("realtime"),"delaySeconds":raw.get("delaySeconds")};self.state["status"]="SHADOW_RUNNING";self.save();return
        if raw.get("type")=="stream_error":
            self.state["errors"]+=1;self.state["stream"]["last_error"]=raw.get("error");self.save();return
        e=self.normalize(raw)
        if not e or not e.get("tokenAddress") or e["usdValue"]<self.cfg.min_alert_usd:return
        if self.dedupe(str(e.get("eventId") or "")):self.save();return
        q=self.wallets.quality(e.get("userId"));e["wallet_quality"]=q;append_jsonl(self.events_path,e);self.state["events"]+=1
        cluster=self.clusters.add(e,q)
        if e["side"]!="buy" or not cluster:self.save();return
        pre=lanes(cluster,None,self.cfg.min_cluster_traders)
        if not(pre["A"]["triggered"] or pre["B"]["triggered"]):self.save();return
        self.state["candidates"]+=1;guard=None
        try:guard=await self.get_guard(e)
        except FomoError as exc:self.state["errors"]+=1;self.state["last_guard_error"]=str(exc)
        out=lanes(cluster,guard,self.cfg.min_cluster_traders);triggered=[x for x in out.values() if x["triggered"]]
        best=max((x["score"] for x in triggered),default=0)
        if best>=self.cfg.signal_threshold:
            rec={"ts":int(time.time()*1000),"token":cluster.symbol,"tokenAddress":cluster.address,"chain":cluster.chain,"chainId":cluster.chain_id,
                 "uniqueTraders":cluster.unique_traders,"clusterUsd":round(cluster.total_usd,2),"avgWalletQuality":round(cluster.average_quality,4),
                 "maxWalletQuality":round(cluster.max_quality,4),"score":best,"lanes":out,"execution":"shadow",
                 "guard":None if not guard else {"passed":guard.passed,"flowScore":guard.flow_score,"safetyScore":guard.safety_score,"holders":guard.holders,
                     "top10Percent":guard.top10,"buySellRatio":guard.ratio,"netVolumeUsd":guard.net,"devExitRisk":guard.dev_exit,"reasons":list(guard.reasons)}}
            append_jsonl(self.signals_path,rec);self.state["signals"]+=1;self.state["recent_signals"]=([rec]+self.state["recent_signals"])[:50]
            for lane,item in out.items():
                if item["triggered"]:self.state["lane_counts"][lane]=self.state["lane_counts"].get(lane,0)+1
        self.save()
    async def run(self):
        if not self.client:
            self.state["status"]="WAITING_FOR_FOMO_API_KEY";self.save()
            while True:await asyncio.sleep(60)
        try:await self.refresh_wallets()
        except Exception as exc:self.state["errors"]+=1;self.state["last_wallet_error"]=f"{type(exc).__name__}: {exc}";self.save()
        async for raw in self.client.stream(self.cfg.stream_mode):
            if time.time()-self.last_wallet_refresh>=self.cfg.wallet_refresh_seconds:
                try:await self.refresh_wallets()
                except Exception as exc:self.state["errors"]+=1;self.state["last_wallet_error"]=f"{type(exc).__name__}: {exc}"
            try:await self.handle(raw)
            except Exception as exc:self.state["errors"]+=1;self.state["last_engine_error"]=f"{type(exc).__name__}: {exc}";self.save()
    async def close(self):
        if self.client:await self.client.close()
