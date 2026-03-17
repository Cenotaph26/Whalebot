"""
FastAPI Server — Dashboard + API
"""

import asyncio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from src.engine import get_full_state, run_bot

app = FastAPI(title="Whale Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    asyncio.create_task(run_bot())


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/state")
async def api_state():
    return JSONResponse(get_full_state())


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(DASHBOARD_HTML)


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Whale Bot</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
:root{--bg:#080b10;--surface:#0d1117;--border:#1c2333;--border2:#243044;--text:#c9d1d9;--muted:#586069;--green:#3fb950;--red:#f85149;--yellow:#d29922;--blue:#58a6ff;--cyan:#39d0d8;--orange:#db6d28;--purple:#bc8cff;--font-mono:'JetBrains Mono',monospace;--font-display:'Syne',sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font-mono);font-size:13px}
.shell{display:grid;grid-template-rows:48px 1fr;height:100vh}
.topbar{display:flex;align-items:center;gap:16px;padding:0 20px;border-bottom:1px solid var(--border);background:var(--surface)}
.logo{font-family:var(--font-display);font-size:16px;font-weight:800;letter-spacing:-.5px;color:#fff}
.logo span{color:var(--cyan)}
.status-dot{width:7px;height:7px;border-radius:50%;background:var(--muted);flex-shrink:0}
.status-dot.live{background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.sym{color:var(--blue);font-weight:600;font-size:12px}
.price-main{font-size:18px;font-weight:700;color:#fff;margin-left:auto;transition:color .3s}
.up{color:var(--green)}.dn{color:var(--red)}
.body{display:grid;grid-template-columns:260px 1fr 280px;overflow:hidden}
.panel{border-right:1px solid var(--border);overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:12px}
.panel:last-child{border-right:none}
.card{background:var(--surface);border:1px solid var(--border);border-radius:6px;overflow:hidden}
.card-head{padding:8px 12px;border-bottom:1px solid var(--border);font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;color:var(--muted)}
.card-body{padding:10px 12px}
.metric-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border)}
.metric-row:last-child{border-bottom:none}
.metric-row .label{color:var(--muted);font-size:11px}
.metric-row .val{font-weight:600;font-size:12px}
.balance-num{font-family:var(--font-display);font-size:26px;font-weight:800;color:#fff;line-height:1}
.balance-sub{font-size:11px;color:var(--muted);margin-top:4px}
.pnl-row{display:flex;gap:12px;margin-top:10px}
.pnl-box{flex:1;background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px 8px}
.pnl-box .plabel{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.pnl-box .pval{font-size:14px;font-weight:700;margin-top:2px}
.wr-bar-bg{background:var(--bg);border-radius:3px;height:6px;margin-top:8px;overflow:hidden}
.wr-bar-fill{height:100%;border-radius:3px;background:var(--green);transition:width .5s}
.trade-item{background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:8px 10px;margin-bottom:6px}
.trade-item:last-child{margin-bottom:0}
.trade-header{display:flex;align-items:center;gap:6px;margin-bottom:6px}
.badge{font-size:10px;font-weight:700;padding:1px 6px;border-radius:3px;text-transform:uppercase}
.badge.long{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.3)}
.badge.short{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.3)}
.trade-id{color:var(--muted);font-size:10px}
.trade-age{margin-left:auto;color:var(--muted);font-size:10px}
.trade-prices{display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px}
.tp-item{background:var(--surface);border-radius:3px;padding:4px 6px}
.tp-label{font-size:9px;color:var(--muted);text-transform:uppercase}
.tp-val{font-size:11px;font-weight:600;margin-top:1px}
.tp-sl{color:var(--red)!important}.tp-tp{color:var(--green)!important}
.signal-item{display:flex;align-items:flex-start;gap:8px;padding:6px 0;border-bottom:1px solid var(--border)}
.signal-item:last-child{border-bottom:none}
.sig-icon{width:22px;height:22px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:10px;flex-shrink:0;margin-top:1px}
.sig-icon.LONG{background:rgba(63,185,80,.15);color:var(--green)}
.sig-icon.SHORT{background:rgba(248,81,73,.15);color:var(--red)}
.sig-content{flex:1;min-width:0}
.sig-source{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.sig-source.whale_trade{color:var(--cyan)}.sig-source.volume_spike{color:var(--yellow)}.sig-source.imbalance{color:var(--purple)}.sig-source.iceberg{color:var(--orange)}
.sig-detail{font-size:11px;color:var(--muted);margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sig-age{font-size:10px;color:var(--muted);flex-shrink:0;margin-top:2px}
.str-bar{height:2px;border-radius:1px;margin-top:4px;background:var(--border);overflow:hidden}
.str-fill{height:100%;background:var(--cyan)}
.flag-item{padding:6px 8px;border-radius:4px;margin-bottom:5px;font-size:11px}
.flag-item:last-child{margin-bottom:0}
.flag-item.HIGH{background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.3)}
.flag-item.MEDIUM{background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.3)}
.flag-item.LOW{background:rgba(88,166,255,.1);border:1px solid rgba(88,166,255,.3)}
.flag-type{font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:.5px}
.flag-item.HIGH .flag-type{color:var(--red)}.flag-item.MEDIUM .flag-type{color:var(--yellow)}.flag-item.LOW .flag-type{color:var(--blue)}
.flag-detail{color:var(--muted);margin-top:2px;font-size:10px;line-height:1.4}
.safety-pill{padding:6px 12px;border-radius:20px;font-size:11px;font-weight:700;text-align:center}
.safety-pill.safe{background:rgba(63,185,80,.12);color:var(--green);border:1px solid rgba(63,185,80,.3)}
.safety-pill.danger{background:rgba(248,81,73,.12);color:var(--red);border:1px solid rgba(248,81,73,.3);animation:pulse 1.5s infinite}
.book-row{display:flex;align-items:center;gap:6px;padding:2px 0;font-size:11px}
.book-bar-bg{flex:1;height:14px;border-radius:2px;background:var(--bg);overflow:hidden}
.book-bar-fill{height:100%;border-radius:2px;transition:width .3s}
.book-bar-fill.bid{background:rgba(63,185,80,.25)}.book-bar-fill.ask{background:rgba(248,81,73,.25)}
.book-pct{width:36px;text-align:right;font-weight:600}
.book-pct.bid{color:var(--green)}.book-pct.ask{color:var(--red)}
.book-label{width:36px;color:var(--muted);font-size:10px}
.log-line{display:flex;gap:6px;padding:3px 0;border-bottom:1px solid rgba(28,35,51,.5);font-size:11px;line-height:1.4}
.log-line:last-child{border-bottom:none}
.log-ts{color:var(--muted);flex-shrink:0;width:52px}
.log-level{flex-shrink:0;width:38px;font-size:10px;font-weight:700}
.log-level.INFO{color:var(--muted)}.log-level.WARN{color:var(--yellow)}.log-level.ERROR{color:var(--red)}
.log-msg{color:var(--text);word-break:break-word}
.ct-row{display:grid;grid-template-columns:52px 46px 80px 80px 70px 40px;gap:4px;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);font-size:11px}
.ct-row:last-child{border-bottom:none}
.ct-row.header{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.5px}
#halted-banner{display:none;position:fixed;top:48px;left:0;right:0;background:var(--red);color:#fff;text-align:center;padding:8px;font-weight:700;font-size:12px;z-index:99}
::-webkit-scrollbar{width:4px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px}
</style>
</head>
<body>
<div id="halted-banner">⛔ BOT DURDURULDU — Günlük kayıp limiti aşıldı</div>
<div class="shell">
  <div class="topbar">
    <span class="status-dot" id="dot"></span>
    <span class="logo">WHALE<span>BOT</span></span>
    <span class="sym" id="sym">BTCUSDT</span>
    <span style="color:var(--muted);font-size:11px" id="uptime">—</span>
    <div style="margin-left:auto;display:flex;align-items:center;gap:12px">
      <span style="font-size:11px;color:var(--muted)">BTC/USDT · TESTNET</span>
      <span class="price-main" id="price-main">—</span>
    </div>
  </div>
  <div class="body">
    <!-- LEFT -->
    <div class="panel">
      <div class="card">
        <div class="card-head">💰 Bakiye</div>
        <div class="card-body">
          <div class="balance-num" id="balance">$10,000.00</div>
          <div class="balance-sub">Testnet sanal bakiye</div>
          <div class="pnl-row">
            <div class="pnl-box"><div class="plabel">Realized</div><div class="pval" id="rpnl">$0.00</div></div>
            <div class="pnl-box"><div class="plabel">Unrealized</div><div class="pval" id="upnl">$0.00</div></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-head">📊 İstatistik</div>
        <div class="card-body">
          <div class="metric-row"><span class="label">Win Rate</span><span class="val" id="wr">—</span></div>
          <div class="metric-row"><span class="label">Toplam İşlem</span><span class="val" id="total-trades">0</span></div>
          <div class="metric-row"><span class="label">Kazanan</span><span class="val up" id="wins">0</span></div>
          <div class="metric-row"><span class="label">Kaybeden</span><span class="val dn" id="losses">0</span></div>
          <div class="metric-row"><span class="label">Günlük Kayıp</span><span class="val" id="dl">%0.00</span></div>
          <div class="wr-bar-bg"><div class="wr-bar-fill" id="wr-bar" style="width:0%"></div></div>
        </div>
      </div>
      <div class="card">
        <div class="card-head">📖 Order Book</div>
        <div class="card-body">
          <div class="book-row">
            <span class="book-label">BID</span>
            <div class="book-bar-bg"><div class="book-bar-fill bid" id="bid-bar" style="width:50%"></div></div>
            <span class="book-pct bid" id="bid-pct">50%</span>
          </div>
          <div style="height:6px"></div>
          <div class="book-row">
            <span class="book-label">ASK</span>
            <div class="book-bar-bg"><div class="book-bar-fill ask" id="ask-bar" style="width:50%"></div></div>
            <span class="book-pct ask" id="ask-pct">50%</span>
          </div>
          <div style="margin-top:10px">
            <div class="metric-row"><span class="label">Buy Vol (1m)</span><span class="val up" id="bv">0</span></div>
            <div class="metric-row"><span class="label">Sell Vol (1m)</span><span class="val dn" id="sv">0</span></div>
            <div class="metric-row"><span class="label">Hacim Spike</span><span class="val" id="spike">1.0×</span></div>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-head">🟢 Açık İşlemler (<span id="ot-count">0</span>)</div>
        <div class="card-body" id="open-trades-body"><div style="color:var(--muted);font-size:11px;text-align:center;padding:10px 0">Açık işlem yok</div></div>
      </div>
    </div>
    <!-- CENTER -->
    <div class="panel" style="border-right:1px solid var(--border)">
      <div class="card">
        <div class="card-head">🛡️ Anti-Manipülasyon Filtreleri</div>
        <div class="card-body">
          <div class="safety-pill safe" id="safety-pill">✓ İşlem Güvenli</div>
          <div style="margin-top:10px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">
            <div class="tp-item"><div class="tp-label">Spoof</div><div class="tp-val up" id="f-spoof">✓</div></div>
            <div class="tp-item"><div class="tp-label">Wash</div><div class="tp-val up" id="f-wash">✓</div></div>
            <div class="tp-item"><div class="tp-label">Stop Hunt</div><div class="tp-val up" id="f-stop">✓</div></div>
            <div class="tp-item"><div class="tp-label">News Lock</div><div class="tp-val up" id="f-news">✓</div></div>
            <div class="tp-item"><div class="tp-label">Layering</div><div class="tp-val up" id="f-layer">✓</div></div>
            <div class="tp-item"><div class="tp-label">Aktif Flag</div><div class="tp-val" id="f-count">0</div></div>
          </div>
          <div style="margin-top:10px" id="flags-list"></div>
        </div>
      </div>
      <div class="card" style="flex:1">
        <div class="card-head">⚡ Sinyal Akışı</div>
        <div class="card-body" id="signals-body" style="max-height:320px;overflow-y:auto">
          <div style="color:var(--muted);font-size:11px;text-align:center;padding:10px 0">Sinyal bekleniyor...</div>
        </div>
      </div>
      <div class="card">
        <div class="card-head">📋 Kapalı İşlemler</div>
        <div class="card-body">
          <div class="ct-row header"><span>ID</span><span>Yön</span><span>Giriş</span><span>Çıkış</span><span>PnL</span><span>Durum</span></div>
          <div id="closed-trades-body"><div style="color:var(--muted);font-size:11px;text-align:center;padding:8px 0">Henüz işlem yok</div></div>
        </div>
      </div>
    </div>
    <!-- RIGHT -->
    <div class="panel">
      <div class="card" style="flex:1">
        <div class="card-head">📡 Bot Logları</div>
        <div class="card-body" id="log-body" style="max-height:calc(100vh - 120px);overflow-y:auto">
          <div style="color:var(--muted);text-align:center;padding:10px">Bağlanılıyor...</div>
        </div>
      </div>
    </div>
  </div>
</div>
<script>
const $=id=>document.getElementById(id);
let prevPrice=0;
function fmt(n){return Number(n).toLocaleString('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtBTC(n){return Number(n).toFixed(3)}
function age(s){if(s<60)return s+'sn';if(s<3600)return Math.floor(s/60)+'dk';return Math.floor(s/3600)+'sa'}
async function poll(){
  try{
    const r=await fetch('/api/state');
    const d=await r.json();
    render(d);
  }catch(e){$('dot').className='status-dot';}
  setTimeout(poll,1000);
}
function render(d){
  const bot=d.bot||{},mkt=d.market||{},risk=d.risk||{},am=d.anti_manip||{},logs=d.logs||[],sigs=d.signals||[];
  $('dot').className='status-dot'+(bot.connected?' live':'');
  $('sym').textContent=bot.symbol||'BTCUSDT';
  $('uptime').textContent=age(bot.uptime_sec||0);
  const price=mkt.price||0;
  const pEl=$('price-main');
  pEl.textContent='$'+fmt(price);
  pEl.style.color=price>prevPrice?'#3fb950':price<prevPrice?'#f85149':'#fff';
  prevPrice=price;
  $('halted-banner').style.display=risk.bot_halted?'block':'none';
  $('balance').textContent='$'+fmt(risk.balance||0);
  const rp=risk.total_pnl||0;
  $('rpnl').textContent=(rp>=0?'+':'')+'$'+fmt(rp);$('rpnl').className='pval '+(rp>=0?'up':'dn');
  const up2=risk.unrealized_pnl||0;
  $('upnl').textContent=(up2>=0?'+':'')+'$'+fmt(up2);$('upnl').className='pval '+(up2>=0?'up':'dn');
  const wr=risk.win_rate||0;
  $('wr').textContent=wr+'%';$('wr').className='val '+(wr>=50?'up':'dn');
  $('total-trades').textContent=risk.total_trades||0;
  $('wins').textContent=risk.wins||0;$('losses').textContent=risk.losses||0;
  const dl=risk.daily_loss_pct||0;
  $('dl').textContent='%'+Math.abs(dl).toFixed(2);$('dl').className='val '+(dl>0?'dn':'up');
  $('wr-bar').style.width=wr+'%';
  const bp=mkt.bid_pct||50,ap=mkt.ask_pct||50;
  $('bid-bar').style.width=bp+'%';$('ask-bar').style.width=ap+'%';
  $('bid-pct').textContent=bp+'%';$('ask-pct').textContent=ap+'%';
  $('bv').textContent=fmtBTC(mkt.buy_vol_1m||0)+' BTC';
  $('sv').textContent=fmtBTC(mkt.sell_vol_1m||0)+' BTC';
  const sr=mkt.spike_ratio||0;
  $('spike').textContent=sr.toFixed(1)+'×';$('spike').className='val '+(sr>=3?'dn':'');
  const safe=am.safe!==false;
  const pill=$('safety-pill');
  pill.className='safety-pill '+(safe?'safe':'danger');
  pill.textContent=safe?'✓ İşlem Güvenli':'⚠ '+(am.reason||'Risk Tespit Edildi');
  const flags=am.flags||[];
  const hasType=t=>flags.some(f=>f.type===t&&f.age_sec<120);
  const setF=(id,bad)=>{$(id).textContent=bad?'✗':'✓';$(id).className='tp-val '+(bad?'dn':'up')};
  setF('f-spoof',hasType('spoof'));setF('f-wash',hasType('wash'));
  setF('f-stop',hasType('stop_hunt'));setF('f-news',am.news_locked);setF('f-layer',hasType('layering'));
  $('f-count').textContent=am.active_flags||0;$('f-count').className='tp-val '+((am.active_flags||0)>0?'dn':'up');
  $('flags-list').innerHTML=flags.length===0?'':flags.map(f=>`
    <div class="flag-item ${f.severity}">
      <div class="flag-type">${f.type.replace('_',' ')} · ${f.severity} · ${f.age_sec}sn önce</div>
      <div class="flag-detail">${f.detail}</div>
    </div>`).join('');
  const ot=risk.open_trades||[];
  $('ot-count').textContent=ot.length;
  $('open-trades-body').innerHTML=ot.length===0?'<div style="color:var(--muted);font-size:11px;text-align:center;padding:10px 0">Açık işlem yok</div>':
    ot.map(t=>`<div class="trade-item">
      <div class="trade-header"><span class="badge ${t.direction.toLowerCase()}">${t.direction}</span><span class="trade-id">#${t.id}</span><span class="trade-age">${t.age_min}dk</span></div>
      <div class="trade-prices">
        <div class="tp-item"><div class="tp-label">Giriş</div><div class="tp-val">$${fmt(t.entry)}</div></div>
        <div class="tp-item"><div class="tp-label">SL</div><div class="tp-val tp-sl">$${fmt(t.sl)}</div></div>
        <div class="tp-item"><div class="tp-label">TP</div><div class="tp-val tp-tp">$${fmt(t.tp)}</div></div>
      </div>
      <div style="margin-top:6px;display:flex;justify-content:space-between;font-size:11px">
        <span style="color:var(--muted)">Boyut: $${fmt(t.size)}</span>
        <span class="${t.upnl>=0?'up':'dn'}">${t.upnl>=0?'+':''}$${fmt(t.upnl)} (${t.upnl_pct>=0?'+':''}${t.upnl_pct}%)</span>
      </div></div>`).join('');
  $('signals-body').innerHTML=sigs.length===0?'<div style="color:var(--muted);font-size:11px;text-align:center;padding:10px 0">Sinyal bekleniyor...</div>':
    sigs.map(s=>`<div class="signal-item">
      <div class="sig-icon ${s.direction}">${s.direction==='LONG'?'▲':'▼'}</div>
      <div class="sig-content">
        <div style="display:flex;justify-content:space-between">
          <span class="sig-source ${s.source}">${s.source.replace('_',' ')}</span>
          <span class="sig-age">${s.age_sec}sn</span>
        </div>
        <div class="sig-detail">${s.details}</div>
        <div class="str-bar"><div class="str-fill" style="width:${s.strength*100}%"></div></div>
      </div></div>`).join('');
  const ct=risk.closed_trades||[];
  $('closed-trades-body').innerHTML=ct.length===0?'<div style="color:var(--muted);font-size:11px;text-align:center;padding:8px 0">Henüz işlem yok</div>':
    ct.map(t=>`<div class="ct-row">
      <span style="color:var(--muted)">#${t.id}</span>
      <span class="${t.direction==='LONG'?'up':'dn'}">${t.direction}</span>
      <span>$${fmt(t.entry)}</span><span>$${fmt(t.exit)}</span>
      <span class="${t.pnl>=0?'up':'dn'}">${t.pnl>=0?'+':''}$${fmt(t.pnl)}</span>
      <span style="color:${t.status==='TP'?'var(--green)':'var(--red)'}">${t.status}</span>
    </div>`).join('');
  if(logs.length>0){
    const lb=$('log-body');
    const atBottom=lb.scrollHeight-lb.clientHeight<=lb.scrollTop+40;
    lb.innerHTML=logs.map(l=>`<div class="log-line"><span class="log-ts">${l.ts}</span><span class="log-level ${l.level}">${l.level}</span><span class="log-msg">${l.msg}</span></div>`).join('');
    if(atBottom)lb.scrollTop=lb.scrollHeight;
  }
}
poll();
</script>
</body>
</html>"""
