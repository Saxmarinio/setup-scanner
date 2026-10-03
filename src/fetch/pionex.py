"""Which assets are actually tradable on Pionex.

There are two separate Pionex listings and they are NOT the same venue:
api.pionex.com carries ~391 base currencies, api.pionex.us ~263, and only
about 144 are common to both. The US entity also quotes in USD and USDC as
well as USDT, so RENDER trades there as RENDER_USD and ARB as ARB_USD.

Both facts cost me a wrong answer: querying only .com with a USDT-only filter
reported RENDER, XPL, PUMP and ZRO as unavailable when all four are tradable.
So: take every base currency, from both hosts, regardless of quote.

The union is deliberately permissive. It says "tradable on Pionex somewhere"
rather than "tradable on your account", which is the right default for a
scanner - better to surface a setup you might not be able to take than to
hide one you could.
"""
import json, os, time
import requests

HOSTS = ("https://api.pionex.us", "https://api.pionex.com")
CACHE = os.path.join("data", "pionex_bases.json")
MAX_AGE_H = 24


def bases(refresh=True):
    """Base currencies listed on either Pionex host. Cached for a day - the
    listing changes on a scale of weeks, and a scan must not fail because an
    exchange API blipped."""
    if os.path.exists(CACHE):
        age_h = (time.time() - os.path.getmtime(CACHE)) / 3600.0
        if age_h < MAX_AGE_H or not refresh:
            try:
                return set(json.load(open(CACHE, encoding="utf-8"))["bases"])
            except Exception:
                pass
    out, ok = set(), []
    for h in HOSTS:
        try:
            r = requests.get(h + "/api/v1/common/symbols", timeout=30)
            r.raise_for_status()
            syms = r.json()["data"]["symbols"]
            got = {s["baseCurrency"].upper() for s in syms if s.get("baseCurrency")}
            out |= got
            ok.append("%s=%d" % (h.split("//")[1], len(got)))
        except Exception as e:
            print("  pionex: %s unreachable (%s)" % (h, str(e)[:60]))
    if not out:
        # Never let an outage silently empty the universe.
        if os.path.exists(CACHE):
            print("  pionex: both hosts failed, using cached list")
            return set(json.load(open(CACHE, encoding="utf-8"))["bases"])
        raise RuntimeError("pionex: no listing available and no cache")
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    json.dump({"bases": sorted(out), "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "hosts": ok}, open(CACHE, "w", encoding="utf-8"), indent=0)
    print("  pionex: %d bases (%s)" % (len(out), ", ".join(ok)))
    return out
