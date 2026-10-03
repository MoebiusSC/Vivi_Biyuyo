from vivi_biyuyo.core import WalletUniverse,ClusterEngine,evaluate_guard,lanes,wallet_row_quality

def ev(i,u,ts,usd=1000):
    return {"eventId":str(i),"userId":u,"trader":u,"token":"MEME","tokenAddress":"mint","chainId":1399811149,"chain":"solana","side":"buy","usdValue":usd,"ts":ts}

def test_wallet_quality_and_stable_user_id():
    assert wallet_row_quality({"rank":1,"pnlUsd":10000,"volumeUsd":50000,"trades":50,"verified":True},100)>wallet_row_quality({"rank":90,"pnlUsd":-1000,"volumeUsd":50000,"trades":5},100)
    u=WalletUniverse();u.update({"traders":[{"rank":1,"userId":"abc","handle":"one","pnlUsd":100,"volumeUsd":1000,"trades":10}]},{"traders":[{"rank":10,"userId":"abc","handle":"renamed","pnlUsd":50,"volumeUsd":1000,"trades":20}]},100)
    assert set(u.wallets)=={"abc"}

def test_cluster_window_and_lanes():
    c=ClusterEngine(120);c.add(ev(1,"a",100000),.8);cluster=c.add(ev(2,"b",150000),.8)
    guard=evaluate_guard({"holders":1000,"top10HoldersPercent":20,"windows":{"5m":{"buySellRatio":2,"netVolumeUsd":10000}}},{"devs":[]})
    out=lanes(cluster,guard,2)
    assert cluster.unique_traders==2 and out["B"]["triggered"] and out["C"]["triggered"] and out["D"]["triggered"]

def test_unsafe_concentration_blocks_d():
    c=ClusterEngine(120);c.add(ev(1,"a",100000),.9);cluster=c.add(ev(2,"b",110000),.9)
    guard=evaluate_guard({"holders":1000,"top10HoldersPercent":70,"windows":{"5m":{"buySellRatio":3,"netVolumeUsd":10000}}},{"devs":[]})
    assert not guard.passed
    assert not lanes(cluster,guard,2)["D"]["triggered"]
