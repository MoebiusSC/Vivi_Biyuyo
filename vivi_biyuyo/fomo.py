from __future__ import annotations
import asyncio, json
from urllib.parse import quote_plus
import httpx, websockets


class FomoError(RuntimeError):
    pass


class FomoClient:
    BASE = "https://api.fomoapi.io"
    WS = "wss://api.fomoapi.io"

    def __init__(self, key: str):
        self.key = key
        self.http = httpx.AsyncClient(
            base_url=self.BASE,
            timeout=8,
            headers={"authorization": f"Bearer {key}", "user-agent": "Vivi-Biyuyo/0.2"},
        )

    async def close(self):
        await self.http.aclose()

    async def get(self, path: str, **params):
        r = await self.http.get(
            path, params={k: v for k, v in params.items() if v is not None}
        )
        if r.status_code == 402:
            raise FomoError("FOMO credits exhausted")
        if r.status_code >= 400:
            raise FomoError(f"FOMO HTTP {r.status_code}")
        data = r.json()
        if isinstance(data, dict) and data.get("error"):
            raise FomoError("FOMO response error")
        return data

    async def leaderboard(self, window: str, limit: int = 100):
        return await self.get(f"/v2/leaderboard/{window}", limit=limit)

    async def token_stats(self, address: str, network_id=None):
        return await self.get(f"/v2/token/{address}/stats", networkId=network_id)

    async def token_devs(self, address: str, network_id=None):
        return await self.get(f"/v2/token/{address}/devs", networkId=network_id)

    async def stream(self, mode="alerts"):
        endpoint = "trades" if mode == "trades" else "alerts"
        url = f"{self.WS}/ws/{endpoint}?key={quote_plus(self.key)}"
        backoff = 1
        while True:
            try:
                async with websockets.connect(
                    url, open_timeout=10, ping_interval=20, ping_timeout=20
                ) as ws:
                    backoff = 1
                    async for raw in ws:
                        try:
                            item = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(item, dict):
                            yield item
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                yield {"type": "stream_error", "error": type(exc).__name__}
                await asyncio.sleep(backoff)
                backoff = min(30, backoff * 2)
