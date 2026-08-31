# Setup scanner

Daily/intraday sweep for two setups across Binance spot pairs and a small
equity list. Output is a set of static pages on GitHub Pages — one per tier,
linked from an index — each row linking straight to the TradingView chart for
manual confirmation.

Crypto data comes from Binance's public mirror `data-api.binance.vision`
(spot). The live `fapi`/`api` hosts return HTTP 451 to cloud IPs such as
GitHub Actions runners, and other perp venues (Bybit, OKX) return 403; the
mirror is not geo-blocked. The detectors use plain OHLCV, so spot candles are
a faithful stand-in for the perp.

## Detectors

**compression** — rising EMA12/21/35 ribbon beneath a descending line through
recent swing highs, price squeezed between. States: `forming` → `compressed`
→ `triggered` / `invalidated`. Selective: ~14 `compressed` bars per 8,600 on
BTC 4H (≈3.5/yr/symbol).

**divergence** — L1 roofed RSI (HP130/SS10/RSI21) and Hurst channel %B, price
lower low against oscillator higher low. Python port of the Pine indicator.
Runs on its own timeframe per tier (`divergence_tf`), independent of the
compression scan: **4H for both crypto tiers** (A and B), 1D for equities.

## Tiers

| tier | universe | compression scan | divergence | confirm |
|---|---|---|---|---|
| A | top 10 crypto by 30d median volume | 4H | 4H | 1D |
| B | all other crypto pairs | 1H | 4H | 4H + 1D |
| C | equities / ETFs | 1D | 1D | — |

Tier A membership is recomputed each run from 30d median volume (shortlisted by
24h volume first, for speed) — a one-day volume spike can't buy a name in.
`config/overrides.yaml` is the escape hatch.

## Two things to know before trusting output

**Tier B is uncalibrated.** 1H compression parameters are provisional. The 4H
divergence work showed daily-tuned margins *inverting* on 4H (margC=0.20:
−1.07% fwd20d, 45% hit), so nothing transfers across timeframe for free. Run
`src/calibrate.py` before treating tier B as anything but observational.

**HTF confirmation gates compression only.** Compression is a continuation
setup, so a favourable 4H/1D posture is the right filter. Divergence is a
cycle-low detector and fires counter-trend by construction — HTF state is
recorded as a ranking field and never as a gate, for the same reason oversold
filters select against right-translated cycles.

## Setup

```bash
git clone <your repo>
cd <your repo>
pip install -r requirements.txt
python src/scan.py --tier A --limit 20     # smoke test
open docs/index.html
```

Then in repo settings: Pages → source `main` branch, `/docs` folder.
No secrets required — every data source is public.

Actions minutes: unlimited on public repos, 2,000/month on private. Tier B at
4-hourly will consume a meaningful share of 2,000 — either make the repo
public or drop tier B to twice daily.

## Calibration

```bash
python src/scan.py --tier B --limit 40      # populate the bar store
python src/calibrate.py --tf 1h --symbols SOLUSDT INJUSDT LDOUSDT ...
```

Pick a config from a *stable region* of the grid, not the top row, then re-run
on held-out symbols. Top-row selection is in-sample fitting.

## Not yet built

- Blind-grading harness to fit ranking weights against your own judgement
  (generate chart images for past hits, strip ticker/date, grade, fit)
- Cross-universe transfer study for the divergence detector
- Telegram/email push of the top rows
