"""Site list: walk the Tranco list in rank order and keep domains that serve a web page.

Tranco's top ranks are full of infrastructure domains (CDNs, DNS, APIs) with no
homepage. Each domain gets one GET; anything that answers with HTML counts as a
website if the status is 2xx, or 401/403/429/503 (it may be a bot wall, which
the measurement then reports as "unmeasurable"). Domains whose homepage redirects
to a different registrable domain are aliases and are dropped. Every skip is recorded with its reason.
"""
import csv
import json
import ssl
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from .trackers import site_of

TRANCO_LATEST = "https://tranco-list.eu/api/lists/date/latest"


def tranco(cache_dir, n=1000):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(TRANCO_LATEST, timeout=30) as r:
        meta = json.loads(r.read())
    list_id = meta["list_id"]
    p = cache_dir / f"tranco-{list_id}-{n}.csv"
    if not p.exists():
        urllib.request.urlretrieve(f"https://tranco-list.eu/download/{list_id}/{n}", p)
    with open(p, newline="") as f:
        rows = [(int(rank), dom.strip()) for rank, dom in csv.reader(f)]
    return {"list_id": list_id, "created_on": meta.get("created_on"), "permalink": f"https://tranco-list.eu/list/{list_id}"}, rows


def probe(domain, ua, timeout=10):
    """One GET of https://domain/ (then https://www.domain/). Returns (final_url | None, reason)."""
    ctx = ssl.create_default_context()
    last = "no response"
    for host in (domain, "www." + domain):
        req = urllib.request.Request(f"https://{host}/", headers={"User-Agent": ua, "Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                ctype = r.headers.get("Content-Type", "")
                if "html" in ctype:
                    return r.geturl(), "html"
                last = f"not html ({ctype[:40] or 'no content-type'})"
        except urllib.error.HTTPError as e:
            # 4xx/5xx HTML counts only where it may be a bot wall; 404s are API hosts.
            if e.code in (401, 403, 429, 503) and "html" in (e.headers.get("Content-Type") or ""):
                return e.geturl() if hasattr(e, "geturl") else f"https://{host}/", f"html (http {e.code})"
            last = f"http {e.code}"
        except Exception as e:
            last = type(e).__name__
    return None, last


def pick_sites(rows, ua, want=100, workers=6):
    """Walk rows in rank order until `want` distinct websites are found."""
    kept, skipped, seen = [], [], set()
    i = 0
    with ThreadPoolExecutor(workers) as ex:
        while len(kept) < want and i < len(rows):
            batch = rows[i:i + workers * 2]
            i += len(batch)
            for (rank, dom), (final, why) in zip(batch, ex.map(lambda rd: probe(rd[1], ua), batch)):
                if len(kept) >= want:
                    break
                if final is None:
                    skipped.append({"rank": rank, "domain": dom, "reason": why})
                    continue
                site = site_of(urlsplit(final).hostname or dom)
                if site != site_of(dom):
                    # An alias (youtu.be, amazonaws.com -> amazon.com): the target is measured under its own rank.
                    skipped.append({"rank": rank, "domain": dom, "reason": f"redirects to {site}"})
                    continue
                if site in seen:
                    skipped.append({"rank": rank, "domain": dom, "reason": "duplicate"})
                    continue
                seen.add(site)
                kept.append({"rank": rank, "domain": dom, "url": f"https://{dom}/", "probe": why, "probe_final": final})
    return kept, skipped
