"""Durable ingress decoupled from slow intelligence calls by a bounded queue."""

import time


async def collect(client, mode, journal, queue, state):
    for row in journal.unprocessed():
        await queue.put(row[0])
    async for raw in client.stream(mode):
        received_ms = int(time.time() * 1000)
        state["last_receive_ms"] = received_ms
        ident = journal.receive(raw, received_ms)
        await queue.put(ident)
