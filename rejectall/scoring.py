"""Deterministic score from measured facts. Same evidence in, same score out.

Bump SCORING_VERSION whenever a weight changes, so old runs stay comparable.
"""

from .patterns import NECESSARY_ONLY

SCORING_VERSION = 1

W_EXTRA_CLICK = 15        # per click reject needs beyond accept
CAP_EXTRA_CLICK = 45
W_NO_REJECT = 40          # banner has accept but no reject path within two layers
W_PAY_OR_OK = 30          # only alternative to consent is paying
W_PRETICKED = 5           # per pre-ticked, non-disabled toggle (legit-interest or consent)
CAP_PRETICKED = 20
W_TRACKER = 3             # per distinct third-party tracker domain fired before any consent
CAP_TRACKER = 40


def score(r):
    """r: a site result dict. Returns (score 0..100 or None, grade, penalty breakdown)."""
    if r.get("status") == "unmeasurable":
        return None, "?", []
    pen = []
    if r.get("status") == "measured":
        acc = r.get("accept_clicks")
        rej = r.get("reject_clicks")
        if r.get("pay_or_ok"):
            pen.append(("pay_or_ok", W_PAY_OR_OK))
        if rej is None and not necessary_only(r):
            pen.append(("no_reject_path", W_NO_REJECT))
        elif rej is not None and acc is not None and rej > acc:
            pen.append(("extra_reject_clicks", min(CAP_EXTRA_CLICK, W_EXTRA_CLICK * (rej - acc))))
        n = r.get("preticked_toggles", 0) or 0
        if n:
            pen.append(("preticked_toggles", min(CAP_PRETICKED, W_PRETICKED * n)))
    t = len(r.get("pre_consent_trackers") or [])
    if t:
        pen.append(("pre_consent_trackers", min(CAP_TRACKER, W_TRACKER * t)))
    s = max(0, 100 - sum(p for _, p in pen))
    return s, grade(s), pen


def necessary_only(r):
    """Accept-only notice that states the site uses only necessary cookies: nothing to reject."""
    return (r.get("reject_clicks") is None and not r.get("pay_or_ok")
            and bool(NECESSARY_ONLY.search(r.get("banner_text") or "")))


def grade(s):
    if s is None:
        return "?"
    for g, floor in (("A", 90), ("B", 75), ("C", 60), ("D", 40)):
        if s >= floor:
            return g
    return "F"
