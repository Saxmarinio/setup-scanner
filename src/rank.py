"""Ranking and clustering.

The clustering step is not cosmetic. On a day when BTC prints a divergence,
a large fraction of alt perps will print one too - they are beta to the same
move. 200 hits is one bet, not 200. Collapsing correlated hits to
best-in-cluster is what stops the scanner manufacturing an illusion of
opportunity breadth on exactly the days you are most concentrated.
"""
import numpy as np, pandas as pd

def _norm(v, invert=False):
    v = np.asarray(v, float)
    if len(v) == 0 or np.allclose(np.nanmax(v), np.nanmin(v)):
        return np.full(len(v), 0.5)
    z = (v - np.nanmin(v)) / (np.nanmax(v) - np.nanmin(v))
    return 1 - z if invert else z

def score_compression(rows, w):
    if not rows:
        return rows
    apex = [r.get("bars_to_apex") or 999 for r in rows]
    pct  = [r.get("ribbon_pct", 1.0) for r in rows]
    bis  = [r.get("bars_in_state", 0) for r in rows]
    fav  = [1.0 if r.get("htf_favourable") else 0.0 for r in rows]
    s = (w["apex_urgency"] * _norm(apex, invert=True)
         + w["ribbon_tightness"] * _norm(pct, invert=True)
         + w["persistence"] * _norm(bis)
         + w["htf_favourable"] * np.asarray(fav))
    for r, v in zip(rows, s):
        r["score"] = round(float(v), 3)
    return rows

def score_divergence(rows, w):
    if not rows:
        return rows
    rec = [r.get("bars_since", 99) for r in rows]
    exc = [r.get("margin_excess", 0.0) for r in rows]
    fav = [1.0 if r.get("htf_favourable") else 0.0 for r in rows]
    s = (w["recency"] * _norm(rec, invert=True)
         + w["margin_excess"] * _norm(exc)
         + w["htf_favourable"] * np.asarray(fav))
    for r, v in zip(rows, s):
        r["score"] = round(float(v), 3)
    return rows

def collapse_clusters(rows, returns_by_symbol, threshold=0.80):
    """Keep the highest-scoring member of each correlated group."""
    rows = sorted(rows, key=lambda r: -r.get("score", 0))
    kept, kept_syms = [], []
    for r in rows:
        s = r["symbol"]
        rs = returns_by_symbol.get(s)
        dup = False
        if rs is not None:
            for ks in kept_syms:
                ko = returns_by_symbol.get(ks)
                if ko is None:
                    continue
                n = min(len(rs), len(ko))
                if n < 30:
                    continue
                c = np.corrcoef(rs[-n:], ko[-n:])[0, 1]
                if np.isfinite(c) and c >= threshold:
                    dup = True
                    r["clustered_with"] = ks
                    break
        if not dup:
            kept.append(r); kept_syms.append(s)
    return kept, [r for r in rows if r not in kept]
