"""Observed latency; never equate provider timestamps with chain inclusion time."""

import time


def record_latency(root, event, received_ms, started):
    sample = {
        "eventId": event.get("eventId"),
        "received_ms": received_ms,
        "provider_ts": event["ts"],
        "feed_age_ms": received_ms - event["ts"],
        "processing_ms": round((time.monotonic() - started) * 1000, 3),
    }
    return sample
