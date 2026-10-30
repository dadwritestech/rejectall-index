"""Shields-style SVG badge stating one measured fact: how many clicks "reject" takes.

The badge shows the click count, not the score: a count is a fact anyone can
re-check against the screenshots; the score is our weighting.
"""
from html import escape

from .scoring import necessary_only

# Approximate Verdana 11px advance widths (the font shields.io uses), in px.
_NARROW = set("fijlrtI!.,:;'|()[] ")
_WIDE = set("mwMW@%")


def _w(text):
    return sum(4 if c in _NARROW else 10 if c in _WIDE else 7 for c in text) + 10


def fact(r):
    """(message, colour) for a site result."""
    if r.get("status") == "unmeasurable":
        return "unmeasurable", "#9f9f9f"
    if r.get("status") == "no_banner":
        return "no banner", "#007ec6"
    if r.get("pay_or_ok"):
        return "pay or ok", "#e05d44"
    n = r.get("reject_clicks")
    if necessary_only(r):
        return "not needed", "#007ec6"
    if n is None:
        return "no option", "#e05d44"
    acc = r.get("accept_clicks") or 1
    colour = "#44cc11" if n <= acc else "#dfb317" if n - acc == 1 else "#fe7d37"
    return f"{n} click" + ("" if n == 1 else "s"), colour


def badge(label, message, colour):
    lw, mw = _w(label), _w(message)
    total = lw + mw
    L, M = escape(label), escape(message)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" role="img" aria-label="{L}: {M}">'
        f'<title>{L}: {M}</title>'
        f'<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)"><rect width="{lw}" height="20" fill="#555"/>'
        f'<rect x="{lw}" width="{mw}" height="20" fill="{colour}"/>'
        f'<rect width="{total}" height="20" fill="url(#s)"/></g>'
        f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{lw / 2}" y="15" fill="#010101" fill-opacity=".3">{L}</text><text x="{lw / 2}" y="14">{L}</text>'
        f'<text x="{lw + mw / 2}" y="15" fill="#010101" fill-opacity=".3">{M}</text>'
        f'<text x="{lw + mw / 2}" y="14">{M}</text></g></svg>'
    )


def badge_for(r):
    msg, colour = fact(r)
    return badge("reject", msg, colour)
