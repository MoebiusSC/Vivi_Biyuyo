from __future__ import annotations
import json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vivi Biyuyo</title>
<style>body{background:#071018;color:#eef7f8;font:14px system-ui;margin:0}main{max-width:1200px;margin:auto;padding:24px}.card{background:#0d1b26;border:1px solid #203443;border-radius:12px;padding:15px;margin:10px 0}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.metric{font-size:26px;font-weight:700}.muted{color:#8ca3af}table{width:100%;border-collapse:collapse}th,td{padding:8px;border-bottom:1px solid #203443;text-align:left;font-size:12px}@media(max-width:800px){.grid{grid-template-columns:repeat(2,1fr)}}</style></head>
<body><main><div><div class="muted">FOMO smart-money memecoin engine</div><h1>Vivi Biyuyo</h1><p>Shadow-first · live execution disabled · <b id="status">...</b></p></div>
<div class="grid"><div class="card"><span class="muted">Eventos</span><div class="metric" id="events">0</div></div><div class="card"><span class="muted">Wallets</span><div class="metric" id="wallets">0</div></div><div class="card"><span class="muted">Candidatos</span><div class="metric" id="candidates">0</div></div><div class="card"><span class="muted">Señales</span><div class="metric" id="signals">0</div></div></div>
<div class="card"><h3>Estrategias A/B/C/D</h3><p id="lanes"></p></div>
<div class="card"><h3>Paper / latencia</h3><pre id="research"></pre></div>
<div class="card"><h3>Top wallets</h3><table><thead><tr><th>Trader</th><th>Score</th><th>Rank 7d</th><th>Rank 30d</th></tr></thead><tbody id="walletRows"></tbody></table></div>
<div class="card"><h3>Señales recientes</h3><table><thead><tr><th>Token</th><th>Chain</th><th>Traders</th><th>Cluster USD</th><th>Score</th><th>Lanes</th><th>Guard</th></tr></thead><tbody id="signalRows"></tbody></table></div>
<script>
function el(x){return document.getElementById(x)} function num(x){return Number(x||0).toLocaleString("es-BO",{maximumFractionDigits:2})}
async function refresh(){try{var r=await fetch("/api/state",{cache:"no-store"}),s=await r.json();el("status").textContent=s.status||"-";el("events").textContent=num(s.events);el("wallets").textContent=num(s.wallet_count);el("candidates").textContent=num(s.candidates);el("signals").textContent=num(s.signals);
el("research").textContent=JSON.stringify({mode:s.mode,latency:s.latency,paper:s.paper,queue:s.queue_depth},null,2);var lc=s.lane_counts||{};el("lanes").textContent="A "+num(lc.A)+" · B "+num(lc.B)+" · C "+num(lc.C)+" · D "+num(lc.D);
var wb=el("walletRows");wb.replaceChildren();(s.top_wallets||[]).forEach(function(w){var row=wb.insertRow();[w.handle,Number(w.score||0).toFixed(3),w.rank_7d||"-",w.rank_30d||"-"].forEach(function(v){row.insertCell().textContent=v})});
var sb=el("signalRows");sb.replaceChildren();(s.recent_signals||[]).forEach(function(x){var row=sb.insertRow(),ls=Object.keys(x.lanes||{}).filter(function(k){return x.lanes[k].triggered}).join(","),g=x.guard?(x.guard.passed?"OK":"BLOCK"):"-";[x.token,x.chain,x.uniqueTraders,num(x.clusterUsd),Number(x.score||0).toFixed(3),ls,g].forEach(function(v){row.insertCell().textContent=v})})}catch(e){el("status").textContent="Sin conexión"}} refresh();setInterval(refresh,3000);
</script></main></body></html>"""


def start_server(engine, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, body, ctype):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(status)
            self.send_header("content-type", ctype)
            self.send_header("cache-control", "no-store")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in {"/health", "/ready"}:
                alive = time.time() * 1000 - engine.state.get("last_tick_ms", 0) < 30000
                ready = (
                    alive
                    and engine.state.get("status") == "SHADOW_RUNNING"
                    and time.time() * 1000 - engine.state.get("last_receive_ms", 0)
                    < 120000
                )
                ok = ready if self.path == "/ready" else alive
                return self.send(
                    200 if ok else 503,
                    json.dumps(
                        {
                            "ok": ok,
                            "ready": ready,
                            "status": engine.state.get("status"),
                            "mode": engine.state.get("mode"),
                            "live_execution": False,
                        }
                    ),
                    "application/json",
                )
            if self.path == "/api/state":
                return self.send(
                    200,
                    json.dumps(
                        {
                            k: v
                            for k, v in engine.state.items()
                            if k not in {"recent_ids", "wallet_universe", "clusters"}
                        },
                        allow_nan=False,
                    ),
                    "application/json",
                )
            if self.path in {"/", "/index.html"}:
                return self.send(200, HTML, "text/html; charset=utf-8")
            return self.send(404, "not found", "text/plain")

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
