"""Statistics for founder-validate. Standard library only. Pure functions, no I/O.

Small on purpose: proportions with honest intervals, a two-group comparison that
reports the size of the difference and not only a p-value, the sample a test
needs, and two exploratory price tools. Every function says what it cannot tell
you. None of them turns a small sample into a big one.
"""

import math


class StatsError(Exception):
    pass


def normal_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def normal_ppf(p):
    """Inverse of the standard normal CDF (bisection: slow, exact enough, no tables)."""
    if not 0.0 < p < 1.0:
        raise StatsError("a probability must be strictly between 0 and 1")
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if normal_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _check_counts(k, n):
    if n < 0 or k < 0 or int(k) != k or int(n) != n:
        raise StatsError("counts must be whole numbers, zero or more")
    if k > n:
        raise StatsError("%d successes out of %d is impossible: the numerator is larger than the denominator" % (k, n))


def rate(k, n):
    """k / n, or None when there is no denominator. Never a made-up zero."""
    _check_counts(k, n)
    return (k / float(n)) if n else None


def wilson(k, n, confidence=0.95):
    """Wilson score interval for a proportion. Returns (low, high), or (None, None) with no data."""
    _check_counts(k, n)
    if n == 0:
        return None, None
    z = normal_ppf(1.0 - (1.0 - confidence) / 2.0)
    p = k / float(n)
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rule_of_three(n):
    """With zero events in n tries, the true rate is below about 3/n (95%). Zero seen is not zero."""
    if n <= 0:
        return None
    return min(1.0, 3.0 / n)


def two_proportions(k1, n1, k2, n2, confidence=0.95):
    """Compare group 2 with group 1 (the control).

    Returns the absolute difference (p2 - p1), its Newcombe interval, the
    relative lift and a two-sided p-value from the pooled z-test. With a
    denominator under 30 or fewer than 5 events and 5 non-events in a group,
    `approximation_ok` is False and the p-value should not be read.
    """
    _check_counts(k1, n1)
    _check_counts(k2, n2)
    if n1 == 0 or n2 == 0:
        raise StatsError("both groups need at least one observation")
    p1, p2 = k1 / float(n1), k2 / float(n2)
    diff = p2 - p1
    l1, u1 = wilson(k1, n1, confidence)
    l2, u2 = wilson(k2, n2, confidence)
    lo = diff - math.sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2)
    hi = diff + math.sqrt((u2 - p2) ** 2 + (p1 - l1) ** 2)
    pooled = (k1 + k2) / float(n1 + n2)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n1 + 1.0 / n2))
    if se == 0:
        z, p_value = 0.0, 1.0
    else:
        z = diff / se
        p_value = 2.0 * (1.0 - normal_cdf(abs(z)))
    ok = all(v >= 5 for v in (k1, n1 - k1, k2, n2 - k2)) and min(n1, n2) >= 30
    return {"p1": p1, "p2": p2, "diff": diff, "ci": (lo, hi), "confidence": confidence,
            "relative_lift": (diff / p1) if p1 > 0 else None, "z": z, "p_value": p_value,
            "approximation_ok": ok}


def sample_size_two_proportions(baseline, min_effect, alpha=0.05, power=0.8):
    """Observations needed in EACH group to detect an absolute change of min_effect from baseline."""
    if not 0 < baseline < 1:
        raise StatsError("the baseline rate must be between 0 and 1")
    p2 = baseline + min_effect
    if min_effect == 0 or not 0 < p2 < 1:
        raise StatsError("baseline + min_effect must stay between 0 and 1, and the effect cannot be zero")
    za = normal_ppf(1.0 - alpha / 2.0)
    zb = normal_ppf(power)
    pbar = (baseline + p2) / 2.0
    num = (za * math.sqrt(2.0 * pbar * (1.0 - pbar)) + zb * math.sqrt(baseline * (1.0 - baseline) + p2 * (1.0 - p2))) ** 2
    return int(math.ceil(num / (min_effect ** 2)))


def sample_size_one_proportion(expected, margin, confidence=0.95):
    """Observations needed to estimate a rate near `expected` to within plus or minus `margin`."""
    if not 0 < expected < 1 or not 0 < margin < 1:
        raise StatsError("expected rate and margin must be between 0 and 1")
    z = normal_ppf(1.0 - (1.0 - confidence) / 2.0)
    return int(math.ceil(z * z * expected * (1.0 - expected) / (margin * margin)))


def sign_test(n_over, n_under):
    """Two-sided exact binomial test that over- and under-estimates are equally likely."""
    n = n_over + n_under
    if n == 0:
        return None
    k = max(n_over, n_under)
    tail = sum(math.comb(n, i) for i in range(k, n + 1)) / float(2 ** n)
    return min(1.0, 2.0 * tail)


def median(values):
    vals = sorted(values)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def quartiles(values):
    vals = sorted(values)
    if not vals:
        return None, None, None
    half = len(vals) // 2
    lower, upper = vals[:half], vals[half + (len(vals) % 2):]
    return (median(lower) if lower else vals[0]), median(vals), (median(upper) if upper else vals[-1])


def gabor_granger(max_prices, grid=None):
    """Stated demand curve from 'the most I would pay' answers.

    For each price on the grid: the share who SAID they would pay at least that
    much, and price x share (a revenue index). This is stated willingness to
    pay. People overstate it. Use the curve to choose prices to test with a real
    offer, never as a forecast.
    """
    vals = sorted(float(v) for v in max_prices if v is not None and float(v) > 0)
    if len(vals) < 5:
        raise StatsError("need at least 5 price answers (got %d)" % len(vals))
    grid = sorted(set(grid or vals))
    n = float(len(vals))
    curve = []
    for p in grid:
        share = sum(1 for v in vals if v >= p) / n
        curve.append({"price": p, "share_willing": share, "revenue_index": p * share})
    best = max(curve, key=lambda c: c["revenue_index"])
    return {"n": len(vals), "curve": curve, "revenue_max_price": best["price"], "kind": "stated"}


def arc_elasticity(price1, rate1, price2, rate2):
    """Arc (midpoint) price elasticity of the conversion rate between two tested prices."""
    if price1 == price2:
        raise StatsError("the two prices are the same")
    if rate1 + rate2 == 0:
        return None
    dq = (rate2 - rate1) / ((rate1 + rate2) / 2.0)
    dp = (price2 - price1) / ((price1 + price2) / 2.0)
    return dq / dp


def pct(v, digits=1):
    return "n/a" if v is None else ("%%.%df%%%%" % digits) % (v * 100.0)


def describe_rate(k, n, confidence=0.95):
    """'8.0% (20 of 250; 95% interval 5.2% to 12.0%)' or an honest 'no data'."""
    if not n:
        return "no data"
    lo, hi = wilson(k, n, confidence)
    return "%s (%d of %d; %d%% interval %s to %s)" % (pct(k / float(n)), k, n, round(confidence * 100), pct(lo), pct(hi))
