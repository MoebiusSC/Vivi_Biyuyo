from __future__ import annotations
import asyncio
import logging
import signal
import os
import time
import threading
from .config import Config
from .engine import Engine
from .web import start_server


async def amain():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    cfg = Config.from_env()
    engine = Engine(cfg)
    server = start_server(engine, cfg.port)
    task = asyncio.create_task(engine.run())
    stopped = threading.Event()

    def watchdog():
        while not stopped.wait(10):
            if time.time() * 1000 - engine.state.get("last_tick_ms", 0) > 90000:
                logging.critical("event_loop_stalled")
                os._exit(1)

    threading.Thread(target=watchdog, daemon=True).start()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except NotImplementedError:
            pass
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        stopped.set()
        task.cancel()
        engine.save()
        server.shutdown()
        server.server_close()
        await engine.close()


def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
