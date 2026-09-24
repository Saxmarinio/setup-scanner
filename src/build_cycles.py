#!/usr/bin/env python3
"""Build the cycle-composite page: docs/cycles.html + docs/cycles/<KEY>.json.

One JSON per instrument, holding every year's percentage path under both
alignments. Every composite the page can draw - mean or median, any cohort,
any hand-picked set of years - is derived from those paths in the browser, so
the toggles are instant and the server never has to anticipate a combination.

  python src/build_cycles.py            # all symbols
  python src/build_cycles.py BTC NDX    # just these
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from fetch import longhist
import cycles

OUT = "docs"

PAGE = r"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Cycle Composites</title>
<style>
:root{
  --bg:#131722; --panel:#1a1e29; --line:#2a2e39; --txt:#d1d4dc; --dim:#787b86;
  --actual:#2196f3;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--txt);font:14px/1.5 -apple-system,Segoe UI,sans-serif;
     margin:0;padding:20px}
a{color:#2196f3}
h1{font-size:18px;margin:0 0 4px;font-weight:600}
.sub{color:var(--dim);font-size:12px;margin-bottom:16px}
.wrap{display:flex;gap:18px;align-items:flex-start;flex-wrap:wrap}
.side{width:210px;flex:none}
.main{flex:1;min-width:420px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:12px 14px;
      margin-bottom:12px}
.card h3{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);
         margin:0 0 10px;font-weight:600}
select{width:100%;background:var(--bg);color:var(--txt);border:1px solid var(--line);
       border-radius:3px;padding:6px 8px;font:inherit}
.seg{display:flex;border:1px solid var(--line);border-radius:3px;overflow:hidden}
.seg button{flex:1;background:var(--bg);color:var(--dim);border:0;padding:7px 4px;font:inherit;
            font-size:12px;cursor:pointer}
.seg button.on{background:#2a3142;color:#fff;font-weight:600}
.seg button:focus-visible{outline:2px solid #2196f3;outline-offset:-2px}
.help{display:inline-block;width:14px;height:14px;line-height:14px;text-align:center;
      border:1px solid var(--dim);border-radius:50%;color:var(--dim);font-size:10px;
      cursor:help;margin-left:5px;position:relative;font-weight:400}
.help:hover>span,.help:focus>span{display:block}
.help>span{display:none;position:absolute;left:20px;top:-6px;width:250px;background:#0d1017;
           border:1px solid #3a3f4b;border-radius:4px;padding:9px 11px;color:var(--txt);
           font-size:12px;line-height:1.45;z-index:20;text-align:left;
           box-shadow:0 6px 20px rgba(0,0,0,.6)}
.help>span b{color:#fff;display:block;margin-bottom:2px}
.help>span i{display:block;margin-top:7px;color:var(--dim);font-style:normal}
label.ck{display:flex;align-items:center;gap:7px;padding:3px 0;cursor:pointer;font-size:13px}
label.ck input{accent-color:#2196f3;margin:0}
.sw{width:11px;height:11px;border-radius:2px;flex:none}
.years{display:flex;flex-wrap:wrap;gap:4px;max-height:132px;overflow-y:auto;margin-top:4px}
.years button{background:var(--bg);border:1px solid var(--line);color:var(--dim);border-radius:3px;
              padding:2px 6px;font:inherit;font-size:11px;cursor:pointer}
.years button.on{background:#f06292;border-color:#f06292;color:#121212;font-weight:600}
#chart{width:100%;height:auto;display:block;background:var(--panel);
       border:1px solid var(--line);border-radius:4px}
.note{color:var(--dim);font-size:12px;margin-top:10px}
.warn{background:#3a2a1b;color:#ffb74d;border-radius:3px;padding:8px 10px;font-size:12px;
      margin-bottom:12px;display:none}
table.tt{border-collapse:collapse;font-size:12px}
</style>

<h1>Cycle Composites</h1>
<div class=sub id=sub>Loading&hellip;</div>

<div class=wrap>
  <div class=side>
    <div class=card>
      <h3>Instrument</h3>
      <select id=sym></select>
    </div>

    <div class=card>
      <h3>Alignment <span class=help tabindex=0>?<span>
        <b>How years are stacked</b>
        <b style="color:#26a69a;margin-top:6px">Trading day</b>
        Session 1 over session 1. Ignores weekends and holidays entirely.
        Use when you care how far <i style="display:inline">into the trading year</i> we are.
        <b style="color:#26a69a;margin-top:6px">Calendar day</b>
        14 March over 14 March. Non-trading days carry the last close forward.
        Use when you care about a <i style="display:inline">date</i> &ndash; an expiry,
        a tax deadline, "the September effect".
        <i>Equity years run 250&ndash;253 sessions, so the two drift apart by roughly
        a month's worth of sessions by December.</i>
      </span></span></h3>
      <div class=seg id=align>
        <button data-v=trading class=on>Trading day</button>
        <button data-v=calendar>Calendar day</button>
      </div>
      <div class=warn id=alignWarn></div>
    </div>

    <div class=card>
      <h3>Average <span class=help tabindex=0>?<span>
        <b>How years are combined</b>
        <b style="color:#26a69a;margin-top:6px">Mean</b>
        The arithmetic average. What these tools normally show &ndash; but one
        2008, 2020 or 2017 drags the whole curve.
        <b style="color:#26a69a;margin-top:6px">Median</b>
        The middle year at every point. Describes the <i style="display:inline">typical</i>
        year and ignores the outlier.
        <i>Where the two disagree sharply, the mean is being driven by one or two
        extreme years &ndash; worth knowing before you trust the shape.</i>
      </span></span></h3>
      <div class=seg id=stat>
        <button data-v=mean class=on>Mean</button>
        <button data-v=median>Median</button>
      </div>
    </div>

    <div class=card>
      <h3>Y axis <span class=help tabindex=0>?<span>
        <b>What the vertical axis shows</b>
        <b style="color:#26a69a;margin-top:6px">Percent</b>
        Each year rebased to 0% at its own first bar. The only way to compare
        years directly &ndash; 1986 and 2026 are not on the same price scale.
        <b style="color:#26a69a;margin-top:6px">Price</b>
        The same curves projected onto <i style="display:inline">this year's</i>
        opening price, so the composite becomes a price path in real units:
        where the average year would finish from where you actually started.
        <i>Raw historical price cannot be overlaid at all &ndash; the Nasdaq 100
        opened 1986 near 130 and 2026 near 25,000.</i>
      </span></span></h3>
      <div class=seg id=yaxis>
        <button data-v=pct class=on>Percent</button>
        <button data-v=price>Price</button>
      </div>
      <div class=seg id=scale style="margin-top:6px">
        <button data-v=linear class=on>Linear</button>
        <button data-v=log>Log</button>
      </div>
      <div class=warn id=scaleWarn></div>
    </div>

    <div class=card>
      <h3>Curves</h3>
      <div id=cohorts></div>
    </div>

    <div class=card>
      <h3>Custom years</h3>
      <div class=years id=years></div>
    </div>
  </div>

  <div class=main>
    <svg id=chart viewBox="0 0 900 470" preserveAspectRatio="xMidYMid meet"></svg>
    <div class=note id=note></div>
  </div>
</div>

<script>
const SYMBOLS = __SYMBOLS__;
const COHORTS = [
  {id:"all",    label:"All years",        color:"#26a69a"},
  {id:"y1",     label:"Y1 Post-election", color:"#ffb74d"},
  {id:"y2",     label:"Y2 Midterm",       color:"#ef5350"},
  {id:"y3",     label:"Y3 Pre-election",  color:"#b388ff"},
  {id:"y4",     label:"Y4 Election",      color:"#ff7043"},
  {id:"l5",     label:"Last 5 years",     color:"#8bc34a"},
  {id:"l10",    label:"Last 10 years",    color:"#4dd0e1"},
  {id:"l20",    label:"Last 20 years",    color:"#7986cb"},
  {id:"dec",    label:"Decade offsets",   color:"#a1887f"},
  {id:"halving",label:"Halving years",    color:"#9575cd"},
  {id:"custom", label:"Custom",           color:"#f06292"}
];
const S = {sym:SYMBOLS[0].key, align:"trading", stat:"mean", yaxis:"pct", scale:"linear",
           on:new Set(["all"]), custom:new Set(), data:null, hover:null};

const $ = s => document.querySelector(s);
const median = a => { const b=[...a].sort((x,y)=>x-y), n=b.length;
  return n%2 ? b[(n-1)/2] : (b[n/2-1]+b[n/2])/2; };

function eligible(){                       // years usable in a composite
  const d = S.data, part = new Set(d.partialYears);
  return d[S.align].years.filter(y => !part.has(y));
}
function cohortYears(id){
  const ys = eligible(), cur = S.data.currentYear;
  if(id==="all")     return ys;
  if(id==="y1")      return ys.filter(y=>y%4===1);
  if(id==="y2")      return ys.filter(y=>y%4===2);
  if(id==="y3")      return ys.filter(y=>y%4===3);
  if(id==="y4")      return ys.filter(y=>y%4===0);
  if(id==="l5")      return ys.slice(-5);
  if(id==="l10")     return ys.slice(-10);
  if(id==="l20")     return ys.slice(-20);
  if(id==="dec")     return ys.filter(y=>[10,20,30].some(o=>y===cur-o));
  if(id==="halving") return ys.filter(y=>[2012,2016,2020,2024,2028].includes(y));
  if(id==="custom")  return ys.filter(y=>S.custom.has(y));
  return [];
}
function composite(years){
  const paths = S.data[S.align].paths;
  const w = S.align==="trading" ? S.data.tradingLen : S.data.calendarLen;
  const out = new Array(w).fill(null);
  // A point must be backed by most of the cohort. Without this the final index
  // is averaged from leap years alone, and the curve ends in a cliff that is an
  // artefact of the calendar rather than anything the market did.
  const need = Math.min(years.length, Math.max(2, Math.ceil(years.length*0.6)));
  for(let i=0;i<w;i++){
    const v=[];
    for(const y of years){ const p=paths[y]; if(p && p[i]!==null && p[i]!==undefined) v.push(p[i]); }
    if(v.length>=need) out[i] = S.stat==="mean" ? v.reduce((a,b)=>a+b,0)/v.length : median(v);
  }
  return out;
}
function actualPath(){
  const p = S.data[S.align].paths[S.data.currentYear];
  return p ? p.slice() : null;
}

// Percent -> price, anchored on the current year's first close, so every
// curve is a real price path this year could actually take.
function toPrice(arr){
  const p0 = S.data.currentStart;
  if(!p0) return arr;
  return arr.map(v => v===null||v===undefined ? null : p0*(1+v/100));
}
function series(){
  const out = [];
  const px = S.yaxis==="price";
  const a = actualPath();
  if(a) out.push({id:"actual", label:"Actual "+S.data.currentYear, color:"var(--actual)",
                  colorRaw:"#2196f3", data:px?toPrice(a):a, n:1});
  for(const c of COHORTS){
    if(!S.on.has(c.id)) continue;
    const ys = cohortYears(c.id);
    if(!ys.length) continue;
    const d0 = composite(ys);
    out.push({id:c.id, label:c.label, color:c.color, colorRaw:c.color,
              data:px?toPrice(d0):d0, n:ys.length, years:ys});
  }
  return out;
}

const W=900,H=470,ML=64,MR=14,MT=16,MB=54;
function draw(){
  const svg=$("#chart"), ss=series();
  const w = S.align==="trading" ? S.data.tradingLen : S.data.calendarLen;
  let lo=Infinity, hi=-Infinity;
  for(const s of ss) for(const v of s.data) if(v!==null){ if(v<lo)lo=v; if(v>hi)hi=v; }
  if(!isFinite(lo)){ lo=-10; hi=10; }
  const logOn = (S.scale==="log" && S.yaxis==="price" && lo>0);
  if(logOn){                       // pad multiplicatively, not additively
    const f=Math.pow(hi/lo,0.04); lo/=f; hi*=f;
  } else {
    const pad=(hi-lo)*0.08||1; lo-=pad; hi+=pad;
  }
  const X = i => ML + (i/(w-1))*(W-ML-MR);
  const L = Math.log10, lLo = logOn?L(lo):0, lHi = logOn?L(hi):0;
  const Y = v => logOn
    ? MT + (1-(L(v)-lLo)/(lHi-lLo))*(H-MT-MB)
    : MT + (1-(v-lo)/(hi-lo))*(H-MT-MB);

  let g="", ticks2=[];
  if(logOn){
    // One tick per 1-2-5 step across each decade the range spans.
    for(let e=Math.floor(lLo); e<=Math.ceil(lHi); e++)
      for(const m of [1,2,5]){ const v=m*Math.pow(10,e); if(v>=lo&&v<=hi) ticks2.push(v); }
    if(ticks2.length<3){ ticks2=[]; for(let k=0;k<=5;k++) ticks2.push(Math.pow(10,lLo+(lHi-lLo)*k/5)); }
  } else {
    const step = niceStep((hi-lo)/6);
    for(let v=Math.ceil(lo/step)*step; v<=hi; v+=step) ticks2.push(v);
  }
  for(const v of ticks2){
    const y=Y(v).toFixed(1);
    const zero = S.yaxis==="pct" && Math.abs(v)<1e-9;
    g+=`<line x1=${ML} y1=${y} x2=${W-MR} y2=${y} stroke="${zero?'#3d4452':'#232735'}" stroke-width="1"/>`;
    g+=`<text x=${ML-8} y=${(+y+4).toFixed(1)} fill="#787b86" font-size="11" text-anchor="end">${fmt(v)}</text>`;
  }
  const ticks=S.data[S.align].monthTicks, MON=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  ticks.forEach((t,i)=>{
    if(t>=w) return;
    const x=X(t).toFixed(1);
    g+=`<line x1=${x} y1=${MT} x2=${x} y2=${H-MB} stroke="#1f2430" stroke-width="1"/>`;
    g+=`<text x=${x} y=${H-MB+16} fill="#787b86" font-size="11" text-anchor="middle">${MON[i]}</text>`;
  });

  for(const s of ss){
    let d="", pen=false;
    s.data.forEach((v,i)=>{ if(v===null){pen=false;return;}
      d += (pen?"L":"M")+X(i).toFixed(1)+" "+Y(v).toFixed(1)+" "; pen=true; });
    const wdt = s.id==="actual" ? 2.1 : 1.5;
    g+=`<path d="${d}" fill="none" stroke="${s.colorRaw}" stroke-width="${wdt}" stroke-linejoin="round"/>`;
  }

  if(S.hover!==null && S.hover>=0 && S.hover<w){
    const x=X(S.hover).toFixed(1);
    g+=`<line x1=${x} y1=${MT} x2=${x} y2=${H-MB} stroke="#5d6270" stroke-width="1" stroke-dasharray="3 3"/>`;
    for(const s of ss){ const v=s.data[S.hover]; if(v===null||v===undefined) continue;
      g+=`<circle cx=${x} cy=${Y(v).toFixed(1)} r="3" fill="${s.colorRaw}"/>`; }
  }

  let lx=ML, ly=H-18, leg="";
  for(const s of ss){
    leg+=`<rect x=${lx} y=${ly-8} width="9" height="9" rx="2" fill="${s.colorRaw}"/>`;
    const t = s.id==="actual" ? s.label : `${s.label} (${s.n})`;
    leg+=`<text x=${lx+14} y=${ly} fill="#d1d4dc" font-size="11.5">${t}</text>`;
    lx += 26 + t.length*6.1;
  }
  svg.innerHTML = g+leg;
  tooltip(ss, w);
}
function niceStep(r){ if(!(r>0)) return 1;
  const p=Math.pow(10,Math.floor(Math.log10(r))), n=r/p;
  return (n<=1?1:n<=2?2:n<=5?5:10)*p; }
function fmt(v){
  if(S.yaxis==="pct") return (Math.abs(v)>=1000? v.toFixed(0) : v.toFixed(1))+"%";
  const a=Math.abs(v);
  if(a>=1000) return v.toLocaleString(undefined,{maximumFractionDigits:0});
  if(a>=10)   return v.toFixed(1);
  if(a>=1)    return v.toFixed(2);
  return v.toPrecision(3);
}

function tooltip(ss,w){
  const el=$("#note");
  if(S.hover===null||S.hover<0||S.hover>=w){
    el.innerHTML = S.data.alwaysOpen
      ? `<b>${S.data.name}</b> &middot; ${S.data.first} to ${S.data.last} &middot; trades every day, so both alignments are identical.`
      : `<b>${S.data.name}</b> &middot; ${S.data.first} to ${S.data.last} &middot; hover the chart for values.`;
    return;
  }
  const lbl = S.align==="trading" ? "Session "+(S.hover+1) : dayLabel(S.hover);
  let rows = ss.filter(s=>s.data[S.hover]!==null&&s.data[S.hover]!==undefined)
    .map(s=>`<tr><td style="padding:1px 10px 1px 0"><span class=sw style="display:inline-block;background:${s.colorRaw}"></span> ${s.label}</td>
             <td style="text-align:right;font-variant-numeric:tabular-nums">${fmt(s.data[S.hover])}</td></tr>`).join("");
  el.innerHTML = `<b>${lbl}</b><table class=tt>${rows}</table>`;
}
function dayLabel(i){ const d=new Date(2001,0,1); d.setDate(i+1);
  return d.toLocaleDateString(undefined,{day:"numeric",month:"short"}); }

function buildControls(){
  const c=$("#cohorts"); c.innerHTML="";
  for(const co of COHORTS){
    if(co.id==="halving" && !S.data.alwaysOpen) continue;       // crypto-only
    const n = cohortYears(co.id).length;
    const l=document.createElement("label"); l.className="ck";
    l.innerHTML=`<input type=checkbox ${S.on.has(co.id)?"checked":""}>
                 <span class=sw style="background:${co.color}"></span>
                 <span>${co.label}</span>
                 <span style="margin-left:auto;color:var(--dim);font-size:11px">${n}</span>`;
    l.querySelector("input").onchange=e=>{
      e.target.checked ? S.on.add(co.id) : S.on.delete(co.id); draw(); };
    c.appendChild(l);
  }
  const y=$("#years"); y.innerHTML="";
  for(const yr of eligible()){
    const b=document.createElement("button");
    b.textContent=yr; b.className=S.custom.has(yr)?"on":"";
    b.onclick=()=>{ S.custom.has(yr)?S.custom.delete(yr):S.custom.add(yr);
                    S.on.add("custom"); buildControls(); draw(); };
    y.appendChild(b);
  }
  $("#alignWarn").style.display = S.data.alwaysOpen ? "block" : "none";
  $("#alignWarn").textContent = "This market never closes, so both alignments give the same curve.";
}

// A percentage path crosses zero and goes negative, so a log axis is not
// defined on it. Rather than silently ignore the choice, disable it and say
// why - the toggle stays visible so the reason is discoverable.
function syncScale(){
  const px = S.yaxis==="price", ok = px && S.data && S.data.currentStart;
  $("#scale").querySelectorAll("button").forEach(b=>{
    b.disabled = !ok; b.style.opacity = ok ? 1 : .4;
    b.style.cursor = ok ? "pointer" : "not-allowed";
  });
  const warn=$("#scaleWarn");
  if(!px){
    warn.style.display="block";
    warn.textContent="Log needs a price axis - percent paths cross zero.";
    S.scale="linear";
    $("#scale").querySelectorAll("button").forEach(b=>
      b.classList.toggle("on", b.dataset.v==="linear"));
  } else if(!ok){
    warn.style.display="block";
    warn.textContent="No bars yet this year, so there is no price to project from.";
  } else warn.style.display="none";
}

async function loadSym(k){
  S.sym=k; S.custom.clear();
  const r=await fetch("cycles/"+k+".json"); S.data=await r.json();
  $("#sub").innerHTML=`${S.data.name} &middot; ${S.data[S.align].years.length} years of daily history
     (${S.data.first} &rarr; ${S.data.last}) &middot; every year rebased to 0% at its first bar`;
  buildControls(); syncScale(); draw();
}

$("#sym").innerHTML=SYMBOLS.map(s=>`<option value="${s.key}">${s.name}</option>`).join("");
$("#sym").onchange=e=>loadSym(e.target.value);
for(const grp of ["align","stat","yaxis","scale"]){
  $("#"+grp).querySelectorAll("button").forEach(b=>b.onclick=()=>{
    $("#"+grp).querySelectorAll("button").forEach(x=>x.classList.remove("on"));
    b.classList.add("on"); S[grp]=b.dataset.v;
    if(grp==="align") buildControls();
    syncScale();
    draw();
  });
}
const svg=$("#chart");
svg.addEventListener("mousemove",e=>{
  const r=svg.getBoundingClientRect();
  const px=(e.clientX-r.left)/r.width*W;
  const w=S.align==="trading"?S.data.tradingLen:S.data.calendarLen;
  S.hover=Math.round((px-ML)/(W-ML-MR)*(w-1)); draw();
});
svg.addEventListener("mouseleave",()=>{S.hover=null;draw();});
loadSym(S.sym);
</script>
"""


def main(keys):
    os.makedirs(os.path.join(OUT, "cycles"), exist_ok=True)
    meta = []
    for k in keys:
        name = longhist.SYMBOLS[k][0]
        df = longhist.load(k)
        if df is None or df.empty:
            print("  %-7s NO DATA - skipped" % k)
            continue
        payload = cycles.build(df, k, name)
        p = os.path.join(OUT, "cycles", "%s.json" % k)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        meta.append({"key": k, "name": name})
        print("  %-7s %5d bars  %s -> %s  %2d years  %3dkB"
              % (k, len(df), payload["first"], payload["last"],
                 len(payload["trading"]["years"]), os.path.getsize(p) // 1024))
    html = PAGE.replace("__SYMBOLS__", json.dumps(meta))
    with open(os.path.join(OUT, "cycles.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote %s/cycles.html (%d instruments)" % (OUT, len(meta)))


if __name__ == "__main__":
    main(sys.argv[1:] or list(longhist.SYMBOLS))
