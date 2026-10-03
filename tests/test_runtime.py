import asyncio
import json
import time
import urllib.request
import urllib.error
import pytest
from vivi_biyuyo.config import Config
from vivi_biyuyo.core import evaluate_guard
from vivi_biyuyo.engine import Engine
from vivi_biyuyo.journal import Journal
from vivi_biyuyo.trading import PaperTrader
from vivi_biyuyo.web import start_server


def test_modes_and_secret_file(monkeypatch, tmp_path):
    key = tmp_path / "key"
    key.write_text("private-key")
    monkeypatch.setenv("FOMO_API_KEY_FILE", str(key))
    cfg = Config.from_env()
    assert cfg.api_key == "private-key" and "private-key" not in repr(cfg)
    monkeypatch.setenv("VIVI_MODE", "live")
    with pytest.raises(ValueError):
        Config.from_env()
    monkeypatch.setenv("VIVI_MODE", "paper")
    monkeypatch.setenv("VIVI_LIVE_TRADING", "true")
    with pytest.raises(ValueError):
        Config.from_env()


def test_missing_safety_data_blocks_d():
    assert not evaluate_guard({}, {}).passed
    assert not evaluate_guard(
        {
            "holders": 1000,
            "top10HoldersPercent": 10,
            "windows": {"5m": {"buySellRatio": 3, "netVolumeUsd": 10}},
        },
        {"devs": []},
    ).passed


def test_paper_costs_identity_and_chain():
    state = {}
    trader = PaperTrader(state)
    event = {
        "eventId": "1",
        "userId": "alice",
        "chainId": 1,
        "tokenAddress": "mint",
        "side": "buy",
        "ts": 1,
    }
    decision = {"A": {"triggered": True, "score": 0.9}}
    assert trader.transact(event, decision, 0.7) == []
    event["priceUsd"] = 2
    trades = trader.transact(event, decision, 0.7)
    assert trades[0]["execution"] == "paper" and state["A"]["cash"] == pytest.approx(
        9899.7
    )
    assert trader.transact(event, decision, 0.7) == []
    event.update(side="sell", userId="bob", priceUsd=4)
    assert trader.transact(event, {}, 0.7) == []
    event.update(userId="alice", chainId=2)
    assert trader.transact(event, {}, 0.7) == []
    event["chainId"] = 1
    assert trader.transact(event, {}, 0.7)[0]["side"] == "sell"
    assert state["A"]["realized_pnl"] > 0 and not state["A"]["positions"]


def test_inbox_restart_and_atomic_effects(tmp_path):
    journal = Journal(tmp_path)
    ident = journal.receive({"eventId": "e"}, 100)
    journal.begin(ident)
    journal.record("trades", {"fill": 2})
    journal.close()  # crash before commit
    journal = Journal(tmp_path)
    assert list(journal.unprocessed()) == [(ident,)]
    journal.begin(ident)
    assert not journal.seen("e")
    journal.record("trades", {"fill": 2})
    journal.finish({"cash": 99})
    journal.close()
    journal = Journal(tmp_path)
    assert journal.load() == {"cash": 99} and list(journal.unprocessed()) == []
    assert journal.seen("e")
    assert journal.db.execute("SELECT count(*) FROM effects").fetchone()[0] == 1
    journal.close()


def test_health_readiness_and_dashboard():
    class Dummy:
        state = {
            "last_tick_ms": int(time.time() * 1000),
            "status": "WAITING_FOR_FOMO_API_KEY",
            "mode": "shadow",
        }

    engine = Dummy()
    server = start_server(engine, 0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert json.load(urllib.request.urlopen(base + "/health"))["ready"] is False
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base + "/ready")
        assert exc.value.code == 503
        assert b"Vivi Biyuyo" in urllib.request.urlopen(base + "/").read()
        engine.state.update(
            status="SHADOW_RUNNING", last_receive_ms=int(time.time() * 1000)
        )
        assert json.load(urllib.request.urlopen(base + "/ready"))["ready"]
        engine.state["last_tick_ms"] = 0
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/health")
    finally:
        server.shutdown()
        server.server_close()


def test_engine_duplicate_survives_restart(monkeypatch, tmp_path):
    monkeypatch.setenv("VIVI_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("FOMO_API_KEY_FILE", raising=False)
    monkeypatch.delenv("FOMO_API_KEY", raising=False)

    async def process(engine, raw):
        ident = engine.journal.receive(raw, 100000)
        item = engine.journal.begin(ident)
        await engine.handle(*item)
        engine.journal.finish(engine.state)

    raw = {
        "type": "alert",
        "alertType": "buy",
        "eventId": "1",
        "userId": "a",
        "tokenAddress": "mint",
        "usdValue": 1000,
        "ts": 100000,
    }
    engine = Engine(Config.from_env())
    asyncio.run(process(engine, raw))
    assert engine.state["events"] == 1
    asyncio.run(engine.close())
    engine = Engine(Config.from_env())
    asyncio.run(process(engine, raw))
    assert engine.state["events"] == 1 and engine.state["duplicates"] == 1
    asyncio.run(engine.close())


def test_worker_commits_paper_fill_once(monkeypatch, tmp_path):
    monkeypatch.setenv("VIVI_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("VIVI_MODE", "paper")
    monkeypatch.delenv("FOMO_API_KEY_FILE", raising=False)
    monkeypatch.delenv("FOMO_API_KEY", raising=False)

    async def exercise():
        engine = Engine(Config.from_env())
        engine.wallets.wallets = {"a": {"score": 0.95}}
        raw = {
            "type": "alert",
            "alertType": "buy",
            "eventId": "once",
            "userId": "a",
            "tokenAddress": "mint",
            "chainId": 1,
            "usdValue": 1000,
            "ts": int(time.time() * 1000),
            "priceUsd": 2,
        }
        for _ in range(2):
            ident = engine.journal.receive(raw, int(time.time() * 1000))
            await engine.queue.put(ident)
        worker = asyncio.create_task(engine.consume())
        await asyncio.wait_for(engine.queue.join(), 2)
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        assert (
            engine.journal.db.execute(
                "SELECT count(*) FROM effects WHERE kind='trades'"
            ).fetchone()[0]
            == 1
        )
        assert engine.state["paper"]["A"]["cash"] == pytest.approx(9899.7)
        assert engine.state["duplicates"] == 1
        await engine.close()
        restored = Engine(Config.from_env())
        assert restored.state["paper"]["A"]["cash"] == pytest.approx(9899.7)
        await restored.close()

    asyncio.run(exercise())


def test_collector_durable_backpressure(tmp_path):
    from vivi_biyuyo.collector import collect

    class Client:
        async def stream(self, mode):
            for i in range(3):
                yield {"eventId": str(i)}

    async def exercise():
        journal = Journal(tmp_path)
        queue = asyncio.Queue(maxsize=1)
        state = {}
        worker = asyncio.create_task(collect(Client(), "alerts", journal, queue, state))
        await asyncio.sleep(0.02)
        assert queue.qsize() == 1
        assert journal.db.execute("SELECT count(*) FROM inbox").fetchone()[0] == 2
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        journal.close()
        journal = Journal(tmp_path)
        assert len(list(journal.unprocessed())) == 2
        journal.close()

    asyncio.run(exercise())


def test_fomo_error_does_not_expose_secret():
    import httpx
    from vivi_biyuyo.fomo import FomoClient, FomoError

    async def exercise():
        client = FomoClient("very-private-key")
        await client.http.aclose()
        client.http = httpx.AsyncClient(
            base_url=client.BASE,
            transport=httpx.MockTransport(
                lambda req: httpx.Response(401, text="very-private-key")
            ),
        )
        try:
            with pytest.raises(FomoError) as exc:
                await client.get("/v2/leaderboard/7d")
            assert "very-private-key" not in str(exc.value)
        finally:
            await client.close()

    asyncio.run(exercise())
