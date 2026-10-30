"""Render the static leaderboard (site/index.html) and per-site badges from data/latest.json.

Facts only: every number on the page comes from the run's results.json, and
every row links to that site's screenshots and evidence.json.
"""
import json
from collections import Counter
from html import escape
from pathlib import Path

from .badge import badge_for, fact
from .scoring import necessary_only
from .scoring import (CAP_EXTRA_CLICK, CAP_PRETICKED, CAP_TRACKER, SCORING_VERSION, W_EXTRA_CLICK,
                      W_NO_REJECT, W_PAY_OR_OK, W_PRETICKED, W_TRACKER)

PATH_LABEL = {
    "first_layer_button": "button on layer 1",
    "untick_and_save_layer1": "untick boxes + save (layer 1)",
    "second_layer_button": "button on layer 2",
    "untick_and_save_layer2": "untick boxes + save (layer 2)",
    "per_purpose_and_save_layer2": "reject each purpose + save (layer 2)",
    "none_found": "none found",
}


def coverage(sites):
    c = Counter(s["status"] for s in sites)
    measured = [s for s in sites if s["status"] == "measured"]
    return {
        "total": len(sites),
        "measured": c["measured"],
        "no_banner": c["no_banner"],
        "unmeasurable": c["unmeasurable"],
        "verified": sum(1 for s in measured if s.get("verified")),
        "reject_layer1": sum(1 for s in measured if s.get("reject_path") == "first_layer_button"),
        "reject_harder": sum(1 for s in measured if s.get("reject_clicks") and s.get("accept_clicks")
                             and s["reject_clicks"] > s["accept_clicks"]),
        "no_reject": sum(1 for s in measured if s.get("reject_clicks") is None and not necessary_only(s)),
        "pay_or_ok": sum(1 for s in measured if s.get("pay_or_ok")),
        "with_trackers": sum(1 for s in sites if s["status"] != "unmeasurable" and s.get("pre_consent_trackers")),
        "llm_sites": sum(1 for s in sites if s.get("llm_used")),
        "llm_calls": sum(len(s.get("llm_calls") or []) for s in sites),
        "llm_decided": sum(1 for s in sites if s.get("llm_located")),
    }


def _trk(s):
    n = len(s.get("pre_consent_trackers") or [])
    return f"{n} tracker" + ("" if n == 1 else "s")


def _n(v):
    return "–" if v is None else str(v)


def _row(s, ev_base):
    dom = escape(s["domain"])
    ev = f"{ev_base}/{dom}"
    shots = " ".join(f'<a href="{ev}/{escape(x)}">{escape(x.split("_", 1)[0])}</a>' for x in s.get("screenshots") or [])
    trk = s.get("pre_consent_trackers") or []
    trk_title = escape(", ".join(t["domain"] for t in trk))
    msg, _ = fact(s)
    if s["status"] == "measured":
        path = PATH_LABEL.get(s.get("reject_path"), s.get("reject_path") or "")
        if necessary_only(s):
            path = "none needed: notice says only necessary cookies"
        if s.get("pay_or_ok"):
            path += " · pay-or-ok"
        if s.get("llm_located"):
            path += f' <span class="dim">· LLM located: {escape(", ".join(s["llm_located"]))}</span>'

        verified = {True: "yes", False: "no", None: "–"}[s.get("verified")]
    elif s["status"] == "no_banner":
        path, verified = "no consent banner seen", "–"
    else:
        path, verified = escape(s.get("reason") or "unmeasurable"), "–"
    li = s.get("preticked_legit_interest") or 0
    pre = f'{s.get("preticked_toggles") or 0}' + (f' <span class="dim">({li} LI)</span>' if li else "")
    g = escape(s.get("grade") or "?")
    return (
        f'<tr class="st-{s["status"]}"><td class="num">{s.get("rank", "")}</td><td><b>{dom}</b></td>'
        f'<td class="grade g{g}">{g}</td><td class="num">{_n(s.get("score"))}</td>'
        f'<td class="num">{_n(s.get("accept_clicks"))}</td><td class="num">{_n(s.get("reject_clicks"))}</td>'
        f'<td>{path}</td><td class="num">{pre if s["status"] == "measured" else "–"}</td>'
        f'<td class="num" title="{trk_title}">{len(trk) if s["status"] != "unmeasurable" else "–"}</td>'
        f'<td>{verified}</td><td class="ev">{shots} <a href="{ev}/evidence.json">json</a></td>'
        f'<td><img src="badges/{dom}.svg" alt="reject: {escape(msg)}" height="20"></td></tr>'
    )


CSS = """
:root{--bg:#f6f3ee;--ink:#1d1b18;--dim:#6f6a62;--line:#ddd6cb;--red:#b3261e;--card:#fffdf9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Georgia,'Times New Roman',serif}
header,main,footer{max-width:1200px;margin:0 auto;padding:0 24px}
header{padding-top:40px}h1{font-size:44px;line-height:1.05;margin:0 0 8px;letter-spacing:-.5px}
h1 em{color:var(--red);font-style:normal}h2{font-size:22px;margin:40px 0 12px;border-bottom:2px solid var(--ink);padding-bottom:4px}
.sub{color:var(--dim);font-size:17px;margin:0}.vantage{margin:16px 0 0;padding:10px 14px;border-left:4px solid var(--red);background:var(--card)}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0}
.stat{background:var(--card);border:1px solid var(--line);padding:12px 14px}.stat b{display:block;font-size:30px;font-family:system-ui,sans-serif}
.stat span{color:var(--dim);font-size:13px}
table{width:100%;border-collapse:collapse;font:13px/1.4 system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--card)}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
th{position:sticky;top:0;background:var(--ink);color:#fff;font-weight:600;cursor:pointer;white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums}.dim{color:var(--dim)}
.grade{font-weight:700;text-align:center}.gA{color:#2e7d32}.gB{color:#558b2f}.gC{color:#b28704}.gD{color:#e65100}.gF{color:var(--red)}
tr.st-unmeasurable td{color:var(--dim)}.ev a{margin-right:4px}a{color:#0b57d0}
.shame{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.shame div{background:var(--card);border:1px solid var(--line);border-top:4px solid var(--red);padding:12px 14px}
.shame b{font-size:18px}.shame p{margin:4px 0 0;font:13px/1.4 system-ui,sans-serif;color:var(--dim)}
footer{color:var(--dim);font-size:13px;padding:32px 24px 48px}code{font-size:12px}
"""

SORT_JS = """
document.querySelectorAll('th').forEach((th,i)=>th.onclick=()=>{const tb=th.closest('table').tBodies[0];
const rows=[...tb.rows];const dir=th.dataset.d=th.dataset.d==='1'?'-1':'1';
const v=r=>{const t=r.cells[i].innerText.trim();const n=parseFloat(t);return isNaN(n)?(t==='–'?Infinity:t):n};
rows.sort((a,b)=>{const x=v(a),y=v(b);return (x>y?1:x<y?-1:0)*dir});rows.forEach(r=>tb.appendChild(r))});
"""


def render(data, ev_base):
    meta, sites = data["meta"], data["sites"]
    cov = coverage(sites)
    measured = [s for s in sites if s["status"] == "measured"]
    shame = sorted(measured, key=lambda s: (s["score"], s.get("rank", 0)))[:8]
    v = meta["vantage"]

    def stat(n, label):
        return f'<div class="stat"><b>{n}</b><span>{label}</span></div>'

    stats = "".join([
        stat(f'{cov["measured"]}/{cov["total"]}', "sites with a banner measured"),
        stat(cov["no_banner"], "no consent banner seen"),
        stat(cov["unmeasurable"], "unmeasurable (bot wall / load error)"),
        stat(cov["reject_layer1"], "offer reject on the first layer"),
        stat(cov["reject_harder"], "make reject take more clicks than accept"),
        stat(cov["no_reject"], "no reject path found within two layers"),
        stat(cov["pay_or_ok"], "pay-or-ok walls"),
        stat(cov["with_trackers"], "fired third-party trackers before any choice"),
    ])
    cards = "".join(
        f'<div><b>{escape(s["domain"])}</b> <span class="grade g{s["grade"]}">{s["grade"]} · {s["score"]}</span>'
        f'<p>accept {_n(s.get("accept_clicks"))} click · reject {_n(s.get("reject_clicks"))}'
        f'{" · pay-or-ok" if s.get("pay_or_ok") else ""} · {_trk(s)} before consent'
        f'{" · " + str(s.get("preticked_toggles")) + " pre-ticked" if s.get("preticked_toggles") else ""}</p></div>'
        for s in shame)
    rows = "".join(_row(s, ev_base) for s in sorted(sites, key=lambda s: (s["score"] is None, s["score"] or 0, s.get("rank", 0))))
    heads = ["Tranco", "Site", "Grade", "Score", "Accept", "Reject", "Reject path", "Pre-ticked",
             "Trackers before consent", "Verified", "Evidence", "Badge"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RejectAll Index: how many clicks does it take to say no?</title><style>{CSS}</style></head><body>
<header><h1>How many clicks does it take to say <em>no</em>?</h1>
<p class="sub">The RejectAll Index measures cookie banners on {cov["total"]} of the most visited websites: clicks to reject vs. accept,
pre-ticked boxes, and trackers fired before you choose anything. Run of {escape(meta["date"])}.</p>
<p class="vantage"><b>Vantage point:</b> {escape(v["description"])}; country {escape(v["country"])}, browser locale {escape(v["locale"])},
timezone {escape(v["timezone"])}. Banners differ by country: these results describe what a visitor from Germany sees, nothing else.</p>
<div class="stats">{stats}</div></header>
<main><h2>Hall of Shame</h2><div class="shame">{cards}</div>
<h2>All sites</h2>
<table><thead><tr>{"".join(f"<th>{h}</th>" for h in heads)}</tr></thead><tbody>{rows}</tbody></table>
<h2>How this is measured</h2>
<p>One fresh headless Chromium {escape(meta["browser"])} profile per site, no stored cookies, one page load, a {meta["timing_s"]["pause_between_sites"]:g}s pause between sites.
Buttons are found and classified by fixed text rules. When the rules find no accept or reject button, a local LLM (gemma-4-12b) is asked
only which button is which; it never decides a score. It was consulted on {cov["llm_sites"]} sites ({cov["llm_calls"]} calls) and its answer decided a button on {cov["llm_decided"]}; rows say so, and every call is logged in that site's evidence.json.
Bot walls and CAPTCHAs are never solved or bypassed: those sites are listed as unmeasurable.
Trackers are third-party requests (by registrable domain and Disconnect entity) to domains in the Disconnect tracking-protection list
(Advertising, Analytics, Social, Fingerprinting, Cryptomining) seen before the first click.</p>
<p>Score v{SCORING_VERSION} starts at 100: −{W_EXTRA_CLICK} per extra click reject needs over accept (max −{CAP_EXTRA_CLICK}),
−{W_NO_REJECT} if no reject path is found within two layers, −{W_PAY_OR_OK} for a pay-or-ok wall,
−{W_PRETICKED} per pre-ticked toggle (max −{CAP_PRETICKED}), −{W_TRACKER} per tracker domain fired before consent (max −{CAP_TRACKER}).
Grades: A ≥ 90, B ≥ 75, C ≥ 60, D ≥ 40, F below. "Verified" means the banner was gone after the reject path and no consent buttons remained.</p>
<p>Limitations: only the largest banner is measured; settings are followed two layers deep; pre-ticked legitimate-interest toggles on tabs that
were never opened are not counted; a single run from a single connection.</p></main>
<footer>Sites: Tranco list <a href="{escape(data.get("tranco", {}).get("permalink", "https://tranco-list.eu/"))}">{escape(data.get("tranco", {}).get("list_id", ""))}</a>,
first {cov["total"]} domains that serve a web page. Tracker list: {escape(meta["tracker_list"])}, sha256 <code>{escape((meta.get("tracker_list_sha256") or "")[:16])}</code>.
User agent: <code>{escape(meta["user_agent"])}</code>. This page states measured facts about public web pages; each row links to its screenshots and raw evidence.</footer>
<script>{SORT_JS}</script></body></html>"""


def build(root, out=None):
    root = Path(root)
    out = Path(out) if out else root / "site"
    data = json.loads((root / "data" / "latest.json").read_text(encoding="utf-8"))
    sites_file = root / "data" / "sites.json"
    if sites_file.exists():
        data["tranco"] = json.loads(sites_file.read_text(encoding="utf-8")).get("tranco", {})
    (out / "badges").mkdir(parents=True, exist_ok=True)
    for s in data["sites"]:
        (out / "badges" / f"{s['domain']}.svg").write_text(badge_for(s), encoding="utf-8")
    ev_base = f"../data/runs/{data['meta']['date']}/sites"
    (out / "index.html").write_text(render(data, ev_base), encoding="utf-8")
    return f"wrote {out / 'index.html'} and {len(data['sites'])} badges"
