"""Run the index: one site at a time, one page load per site, polite pauses."""
import datetime as dt
import json
import os
import shutil
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import measure as M
from .llm import Locator
from .scoring import SCORING_VERSION, score
from .trackers import TrackerList, fetch_lists

# Where the measurement runs from. Banners differ by country, so this is printed on every page.
VANTAGE = {"country": os.environ.get("REJECTALL_VANTAGE_COUNTRY", "DE"),
           "description": os.environ.get("REJECTALL_VANTAGE_DESCRIPTION",
                                         "One residential connection in Germany (the maintainer's machine)"),
           "locale": "de-DE", "timezone": "Europe/Berlin"}
PAUSE_S = 3.0
VIEWPORT = {"width": 1366, "height": 900}


def browser_ua(browser):
    pg = browser.new_page()
    ua = pg.evaluate("navigator.userAgent")
    pg.close()
    # Headless Chromium announces itself as "HeadlessChrome"; we send the plain
    # Chrome token instead. This is the only fingerprint change; no stealth plugins.
    return ua.replace("HeadlessChrome", "Chrome")


def run(sites, root, date=None, use_llm=True, log=print):
    root = Path(root)
    date = date or dt.date.today().isoformat()
    out = root / "data" / "runs" / date
    lists = fetch_lists(root / "cache")
    tl = TrackerList.load(lists["services"], lists["entities"])
    locator = Locator() if use_llm else None
    if locator is not None and not locator.key:
        log("llm: no key found; fallback disabled for this run")
    results_path = out / "results.json"
    done = {}
    if results_path.exists():
        done = {r["domain"]: r for r in json.loads(results_path.read_text(encoding="utf-8"))["sites"]}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ua = browser_ua(browser)
        meta = {"date": date, "vantage": VANTAGE, "user_agent": ua, "browser": f"chromium {browser.version}",
                "tracker_list": "Disconnect services.json + entities.json (CC BY-NC-SA 4.0)",
                "tracker_list_sha256": tl.sha256, "scoring_version": SCORING_VERSION,
                "timing_s": {"settle": M.SETTLE_S, "layer_wait": M.LAYER_WAIT_S, "after_wait": M.AFTER_WAIT_S,
                             "pause_between_sites": PAUSE_S},
                "llm": {"model": "gemma-4-12b (local llama-server)", "role": "locate buttons only",
                        "enabled": bool(locator and locator.key)}}
        for i, site in enumerate(sites, 1):
            dom = site["domain"]
            if dom in done:
                continue
            sdir = out / "sites" / dom
            if sdir.exists():
                shutil.rmtree(sdir)
            t0 = time.time()
            ctx = browser.new_context(viewport=VIEWPORT, locale=VANTAGE["locale"],
                                      timezone_id=VANTAGE["timezone"], user_agent=ua)
            page = ctx.new_page()
            try:
                r = M.measure(page, site["url"], dom, sdir, tl, locator)
            except Exception as e:
                r = {"domain": dom, "url": site["url"], "status": "unmeasurable",
                     "reason": "crash: " + str(e).split("\n")[0][:160], "pre_consent_trackers": []}
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass
            r["rank"] = site["rank"]
            r["seconds"] = round(time.time() - t0, 1)
            r["score"], r["grade"], r["penalties"] = score(r)
            done[dom] = r
            _write(results_path, meta, sites, done)
            log(f"[{i:3}/{len(sites)}] {dom:28} {r['status']:12} acc={r.get('accept_clicks')} "
                f"rej={r.get('reject_clicks')} trk={len(r.get('pre_consent_trackers') or [])} "
                f"llm={'y' if r.get('llm_used') else 'n'} score={r['score']} {r['seconds']}s "
                f"{r.get('reason') or ''}")
            time.sleep(PAUSE_S)
        browser.close()
    _write(results_path, meta, sites, done)
    latest = root / "data" / "latest.json"
    shutil.copyfile(results_path, latest)
    return json.loads(results_path.read_text(encoding="utf-8"))


def _write(path, meta, sites, done):
    path.parent.mkdir(parents=True, exist_ok=True)
    order = [s["domain"] for s in sites]
    rows = [done[d] for d in order if d in done]
    slim = []
    for r in rows:
        r = {k: v for k, v in r.items() if k not in ("events", "layer1", "layer2")}
        slim.append(r)
    path.write_text(json.dumps({"meta": meta, "sites": slim}, indent=1, ensure_ascii=False), encoding="utf-8")
