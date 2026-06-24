"""Shared metric helpers."""


def _percentiles(sorted_data, percentiles):
    """
    Compute percentiles from a list of numbers (will be sorted).
    Returns dict e.g. {50: 2.5, 90: 8.0}. Uses linear interpolation.
    """
    if not sorted_data or not percentiles:
        return {}
    arr = sorted(sorted_data)
    n = len(arr)
    out = {}
    for p in percentiles:
        if p <= 0:
            out[p] = round(arr[0], 2)
        elif p >= 100:
            out[p] = round(arr[-1], 2)
        else:
            idx = (p / 100.0) * (n - 1)
            lo = int(idx)
            hi = min(lo + 1, n - 1)
            frac = idx - lo
            val = arr[lo] * (1 - frac) + arr[hi] * frac
            out[p] = round(val, 2)
    return out

