from __future__ import annotations
import asyncio
from .config import Config
from .engine import Engine
from .web import start_server

async def amain():
    cfg=Config.from_env();engine=Engine(cfg);server=start_server(engine,cfg.port)
    task=asyncio.create_task(engine.run())
    try:await task
    finally:
        task.cancel();server.shutdown();await engine.close()

def main():
    try:asyncio.run(amain())
    except KeyboardInterrupt:pass

if __name__=="__main__":main()
