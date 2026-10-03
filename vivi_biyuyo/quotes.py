"""Observed FOMO position marks for paper only; not executable venue quotes."""

import math
import time


async def observe(client, event):
    payload = await client.get(f"/v2/users/{event['userId']}/positions", limit=100)
    rows = (
        payload.get("positions", payload.get("trades", []))
        if isinstance(payload, dict)
        else []
    )
    for row in rows:
        token = row.get("token") or {}
        network = token.get("networkId", row.get("networkId"))
        if token.get("address") != event["tokenAddress"] or str(network) != str(
            event.get("chainId")
        ):
            continue
        price = row.get("priceUsd")
        if isinstance(price, (int, float)) and math.isfinite(price) and price > 0:
            return {
                "priceUsd": price,
                "observed_ms": int(time.time() * 1000),
                "source": "fomo_position_mark",
                "executable": False,
            }
    return None
