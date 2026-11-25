"""Cycle composites: the average shape of a year, built from many years.

Every year is rebased to 0% at its own first bar, then the years are laid on
top of one another and averaged. The only genuinely consequential choice is how
to lay them on top of one another, because trading years are not the same
length:

  TRADING-DAY alignment  - session 1 against session 1, session 2 against
      session 2. Years end at slightly different points (250-253 sessions).
      Correct when the question is "how far into the trading year are we", and
      it keeps holiday-shortened stretches from smearing.

  CALENDAR-DAY alignment - 14 March against 14 March, regardless of how many
      sessions have passed. Weekends and holidays are carried forward from the
      last close. Correct when the question is about a DATE - an options
      expiry, a tax deadline, "the September effect".

They produce visibly different curves. Neither is more correct in general, so
both are built and the reader toggles.

Similarly for the average itself: the MEAN is what these tools normally show,
but a single 2008 or 2020 drags it a long way. The MEDIAN describes the typical
year and ignores the outlier. Both are computed in the browser from the same
per-year paths, so toggling costs nothing.
"""
import numpy as np
import pandas as pd

CALENDAR_LEN = 366
# Sessions per year is NOT a constant across asset classes: an equity year is
# 250-253 sessions, but crypto never closes, so its "trading year" is 365. Take
# it from the data rather than assuming, or crypto gets silently truncated in
# November.
def trading_len(df):
    d = pd.to_datetime(df["datetime"])
    per = d.dt.year.value_counts()
    return int(min(CALENDAR_LEN, max(200, per.max())))


def is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def year_paths(df, align="trading", width=None):
    """Per-year percentage paths, rebased to 0 at each year's first bar.

    Returns {year: [pct or None, ...]} - a fixed-length list so the browser can
    average across years by index without any alignment logic of its own.
    """
    d = df.dropna(subset=["close"]).copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    d = d.sort_values("datetime")
    out = {}
    this_year = int(d["datetime"].max().year)
    if width is None:
        width = trading_len(d) if align == "trading" else CALENDAR_LEN

    for year, g in d.groupby(d["datetime"].dt.year):
        closes = g["close"].to_numpy(float)
        if len(closes) < 20 or closes[0] <= 0:
            continue                      # a stub year says nothing about shape
        pct = (closes / closes[0] - 1.0) * 100.0
        row = [None] * width

        if align == "trading":
            for i, v in enumerate(pct[:width]):
                row[i] = round(float(v), 2)
        else:
            # Place each session on its day-of-year, then carry the last close
            # forward across weekends and holidays so every date has a value.
            doy = g["datetime"].dt.dayofyear.to_numpy(int)
            for i, v in zip(doy, pct):
                if 1 <= i <= width:
                    row[i - 1] = round(float(v), 2)
            last = None
            for i in range(width):
                if row[i] is None:
                    if last is not None:
                        row[i] = last
                else:
                    last = row[i]
            # Only the CURRENT year gets its tail left empty - it has not
            # happened yet, and a composite must not average in a frozen line.
            # A completed year is complete even if its last session was the
            # 29th: carrying that close to the 31st is what "calendar
            # alignment" means. Truncating it instead silently shrinks the
            # cohort over the last few days and puts a spike in the year-end.
            if int(year) == this_year:
                end = max(doy) if len(doy) else 0
                for i in range(end, width):
                    row[i] = None
            elif not is_leap(int(year)):
                row[width - 1] = None      # no 29 Feb, so no 366th day
        out[int(year)] = row
    return out


def edge_paths(d, align, width, pad):
    """The `pad` bars either side of each year, rebased to THAT year's first close.

    The point of the context months is to see where a year came from and where
    it went, so both wings have to share the focus year's base. Rebasing the
    lead-in to the PREVIOUS year's January instead would not join up: the path
    has to pass through 0% on day one of the focus year.

    The main path is untouched - these are separate arrays, so the existing
    composite cannot shift under anyone.
    """
    pre, post = {}, {}
    if align == "trading":
        closes = d["close"].to_numpy(float)
        years = d["datetime"].dt.year.to_numpy(int)
        n = len(closes)
        starts = {}
        for i, y in enumerate(years):
            if int(y) not in starts:
                starts[int(y)] = i

        def at(gi, base):
            if 0 <= gi < n and closes[gi] > 0:
                return round(float((closes[gi] / base - 1.0) * 100.0), 2)
            return None

        for y, s in starts.items():
            base = closes[s]
            if base <= 0:
                continue
            # Offsets are from the year's first SESSION, which is what the main
            # domain is indexed by, so the wings butt up against it exactly.
            pre[y] = [at(s - pad + k, base) for k in range(pad)]
            post[y] = [at(s + width + k, base) for k in range(pad)]
    else:
        ser = d.set_index("datetime")["close"].astype(float)
        ser = ser[~ser.index.duplicated(keep="last")]
        # Forward-fill to a daily grid: the wings are read by DATE, so a
        # weekend or holiday must carry the last close rather than leave a hole.
        daily = ser.resample("D").last().ffill()

        def vals(ix, base):
            v = daily.reindex(ix).to_numpy(float)
            return [None if not np.isfinite(x) or x <= 0
                    else round(float((x / base - 1.0) * 100.0), 2) for x in v]

        for y, g in d.groupby(d["datetime"].dt.year):
            y = int(y)
            base = float(g["close"].iloc[0])
            if base <= 0:
                continue
            j0 = pd.Timestamp(year=y, month=1, day=1)
            j1 = pd.Timestamp(year=y + 1, month=1, day=1)
            pre[y] = vals([j0 - pd.Timedelta(days=pad - k) for k in range(pad)], base)
            post[y] = vals([j1 + pd.Timedelta(days=k) for k in range(pad)], base)
    return pre, post


def month_ticks(df, align="trading"):
    """Where the months fall on the x axis, so both modes can be read.

    Calendar mode is arithmetic. Trading mode is empirical: the median session
    number at which each month first appears, across all years in the history.
    """
    if align == "calendar":
        starts = pd.date_range("2001-01-01", periods=12, freq="MS").dayofyear
        return [int(x) - 1 for x in starts]

    d = df.copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    per_month = {m: [] for m in range(1, 13)}
    for _, g in d.groupby(d["datetime"].dt.year):
        g = g.sort_values("datetime").reset_index(drop=True)
        if len(g) < 20:
            continue
        months = g["datetime"].dt.month.to_numpy(int)
        for m in range(1, 13):
            hit = np.nonzero(months == m)[0]
            if len(hit):
                per_month[m].append(int(hit[0]))
    return [int(np.median(per_month[m])) if per_month[m] else 0
            for m in range(1, 13)]


def build(df, symbol_key, name):
    """Everything the page needs for one instrument."""
    d = df.dropna(subset=["close"]).copy()
    d["datetime"] = pd.to_datetime(d["datetime"])
    tl = trading_len(d)
    payload = {
        "key": symbol_key,
        "name": name,
        "first": str(d["datetime"].min().date()),
        "last": str(d["datetime"].max().date()),
        "tradingLen": tl,
        # Sessions per year vary (250-253 for equities). Drawing out to the
        # LONGEST year leaves a ragged tail that only a handful of years reach,
        # so a small cohort's last few points swing on two or three members.
        # Cap at the typical year instead: session 253 is not comparable across
        # years anyway.
        "tradingTypical": int(d.groupby(d["datetime"].dt.year).size()
                              .drop(index=[y for y in [int(d["datetime"].max().year)]
                                           if y in set(d["datetime"].dt.year)],
                                    errors="ignore").median()),
        "calendarLen": CALENDAR_LEN,
        # When an asset never closes, the two alignments are the same series.
        # Say so rather than offering a toggle that does nothing.
        "alwaysOpen": bool(tl >= 360),
    }
    for align in ("trading", "calendar"):
        width = tl if align == "trading" else CALENDAR_LEN
        paths = year_paths(d, align, width)
        # Four months of context either side. A third of a year is 4 months in
        # both modes, so the same fraction works for a 252-session equity year
        # and a 366-day calendar year without a second constant.
        pad = int(round(width / 3.0))
        pre, post = edge_paths(d, align, width, pad)
        payload[align] = {
            "years": sorted(paths.keys()),
            "paths": {str(y): paths[y] for y in sorted(paths)},
            "monthTicks": month_ticks(d, align),
            "pad": pad,
            "pre": {str(y): pre[y] for y in sorted(pre) if y in paths},
            "post": {str(y): post[y] for y in sorted(post) if y in paths},
        }
    # A year that does not START at the start of the year cannot describe the
    # shape of a year - Bitcoin's 2010 begins on 18 July, and rebasing that to
    # "0% on day one" would invent a January that never traded. The current
    # year is partial by definition; it is the Actual line, not a composite
    # member. Both are excluded from cohorts by default.
    this_year = int(d["datetime"].max().year)
    partial = []
    for y, g in d.groupby(d["datetime"].dt.year):
        first_doy = int(g["datetime"].dt.dayofyear.min())
        if first_doy > 10 or int(y) == this_year or len(g) < 120:
            partial.append(int(y))
    payload["partialYears"] = sorted(partial)
    payload["currentYear"] = this_year
    # Bull/bear per year, from the calendar-year return rather than a hand
    # -kept list. Hand-labelling is what the reference tool does, but it only
    # ever covers one instrument and it ages; sign-of-the-year is objective,
    # self-maintaining, and works for gold and copper too. On BTC it recovers
    # the conventional bear years (2014, 2018, 2022) without being told.
    rets = {}
    for y, g in d.groupby(d["datetime"].dt.year):
        c0, c1 = float(g["close"].iloc[0]), float(g["close"].iloc[-1])
        if c0 > 0:
            rets[str(int(y))] = round((c1 / c0 - 1.0) * 100.0, 2)
    payload["yearReturn"] = rets
    # The anchor for price mode. Raw historical price cannot be overlaid - the
    # Nasdaq 100 opened 1986 near 130 and 2026 near 25,000, and one linear axis
    # cannot hold both. What IS meaningful is projecting each composite's
    # percentage path onto THIS year's opening price, which turns the composite
    # into a price path in real units: "where does the average year finish".
    cur = d[d["datetime"].dt.year == this_year]
    payload["currentStart"] = float(cur["close"].iloc[0]) if len(cur) else None
    payload["lastClose"] = float(d["close"].iloc[-1])
    return payload
