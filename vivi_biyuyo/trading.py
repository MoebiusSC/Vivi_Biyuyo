"""Independent simulated cash portfolios. No signing or live execution adapter."""

import math


class PaperTrader:
    def __init__(self, state, initial=10000, size=100, fee_bps=30, slippage_bps=100):
        self.state = state
        self.size, self.fee, self.slippage = size, fee_bps / 10000, slippage_bps / 10000
        for lane in "ABCD":
            state.setdefault(
                lane, {"cash": initial, "positions": {}, "realized_pnl": 0}
            )

    def transact(self, event, decisions, threshold):
        price = event.get("priceUsd")
        if (
            not isinstance(price, (float, int))
            or not math.isfinite(price)
            or price <= 0
        ):
            return []  # No fabricated fills when the feed lacks a usable quote.
        key = f"{event.get('chainId')}:{event['tokenAddress']}"
        trades = []
        for lane, portfolio in self.state.items():
            position = portfolio["positions"].get(key)
            if position:
                position["mark"] = price
            decision = decisions.get(lane, {})
            if (
                event["side"] == "buy"
                and not position
                and decision.get("triggered")
                and decision.get("score", 0) >= threshold
            ):
                cost = self.size * (1 + self.fee)
                if portfolio["cash"] < cost:
                    continue
                fill = price * (1 + self.slippage)
                portfolio["cash"] -= cost
                portfolio["positions"][key] = {
                    "quantity": self.size / fill,
                    "cost": cost,
                    "mark": price,
                    "userId": event.get("userId"),
                    "opened_ms": event["ts"],
                }
                trades.append({"lane": lane, "side": "buy", "fill": fill, "cost": cost})
            elif (
                event["side"] == "sell"
                and position
                and event.get("userId") == position["userId"]
            ):
                fill = price * (1 - self.slippage)
                proceeds = position["quantity"] * fill * (1 - self.fee)
                portfolio["cash"] += proceeds
                portfolio["realized_pnl"] += proceeds - position["cost"]
                del portfolio["positions"][key]
                trades.append(
                    {"lane": lane, "side": "sell", "fill": fill, "proceeds": proceeds}
                )
        return [
            dict(
                t,
                eventId=event.get("eventId"),
                tokenAddress=event["tokenAddress"],
                chainId=event.get("chainId"),
                ts=event["ts"],
                execution="paper",
                price_source=event.get("source", "observed_event")
                if not event.get("observed_ms")
                else "fomo_position_mark",
                observed_ms=event.get("observed_ms", event.get("received_ms")),
            )
            for t in trades
        ]
