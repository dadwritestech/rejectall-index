"""Measure one site: one page load, no login, no CAPTCHA interaction.

Flow:
  1. Load the homepage in a fresh context (no cookies), log every request.
  2. If a bot wall or challenge shows, stop: "unmeasurable".
  3. Scan all frames for consent buttons (deterministic rules; LLM only if the
     rules see a consent UI but cannot label its buttons).
  4. Count clicks to accept (not clicked) and walk the reject path, clicking it
     for real, up to two layers deep. Verify the banner went away.
  5. Requests before the first click are "pre-consent".
"""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import patterns
from .trackers import summarize

SCAN_JS = (Path(__file__).parent / "scan.js").read_text(encoding="utf-8")
SCAN_ARGS = {
    "cookieRe": patterns.COOKIE_TEXT.pattern,
    "cmpRe": patterns.CMP_HINT.pattern,
    "liRe": patterns.LEGIT_INTEREST.pattern,
}
CONSENT_FRAME = re.compile(r"consent|privacy-?mgmt|sp_message|cmp|cookie|gdpr|sourcepoint|trustarc|truste", re.I)
CHALLENGE_FRAME = re.compile(r"challenges\.cloudflare\.com|hcaptcha\.com|captcha-delivery\.com|perimeterx|px-captcha|arkoselabs|funcaptcha", re.I)

SETTLE_S = 6.0        # wait after load before scanning; fixed so runs are comparable
LAYER_WAIT_S = 1.0    # re-scan interval after opening settings (up to 10 s)
AFTER_WAIT_S = 4.0    # wait after the final reject click


def scan(page, tag):
    """Scan every frame. Returns (buttons, toggles, frame texts, groups), annotated with frame index."""
    buttons, toggles, texts = [], [], []
    groups = {}  # "frame:group" -> {"area", "text"}
    for fi, frame in enumerate(page.frames):
        try:
            res = frame.evaluate(SCAN_JS, dict(SCAN_ARGS, scanTag=f"{tag}f{fi}"))
        except Exception:
            continue
        texts.append({"frame": fi, "url": res["url"][:200], "title": res["title"], "text": res["bodyText"]})
        if fi > 0 and not _frame_visible(frame):
            continue  # hidden iframes (pre-loaded ad CMPs, trackers) are not what the user sees
        consent_frame = fi > 0 and bool(CONSENT_FRAME.search(frame.url or ""))
        for gid, g in res["groups"].items():
            groups[f"{fi}:{gid}"] = g
        if fi > 0:
            groups[f"{fi}:frame"] = {"area": _frame_area(frame), "text": res["bodyText"][:3000]}
        for b in res["buttons"]:
            b["frame"] = fi
            b["frame_url"] = (frame.url or "")[:200]
            if consent_frame:
                b["context"] = True
            # Group = one banner: the overlay root inside a frame, or the whole consent iframe.
            if b["group"] is not None:
                b["group"] = f"{fi}:{b['group']}"
            elif fi > 0:
                b["group"] = f"{fi}:frame"
            b["overlay"] = b["group"] is not None
            b["role"] = patterns.classify(b["text"])
            b["group_area"] = groups.get(b["group"], {}).get("area", 0)
            buttons.append(b)
        for t in res["toggles"]:
            t["frame"] = fi
            toggles.append(t)
    return buttons, toggles, texts, groups


def _frame_area(frame):
    try:
        box = frame.frame_element().bounding_box()
        return int(box["width"] * box["height"]) if box else 0
    except Exception:
        return 0


def _sig(buttons):
    return sorted((b["frame_url"], b["text"], b["role"]) for b in buttons if b["context"] and b["role"] and b["overlay"])


def stable_scan(page, step=2.0, max_extra=4):
    """Scan until the set of labelled overlay buttons stops changing: CMPs often
    inject a second, bigger banner a few seconds after load."""
    prev = scan(page, "a0")
    for n in range(1, max_extra + 1):
        time.sleep(step)
        cur = scan(page, f"a{n}")
        if _sig(cur[0]) == _sig(prev[0]) and _sig(cur[0]):
            return cur
        if not _sig(cur[0]) and not _sig(prev[0]) and n >= 2:
            return cur  # nothing appeared in 4 s more; stop waiting
        prev = cur
    return prev


def wait_new_layer(page, before, step, max_wait=10.0):
    """Re-scan until a labelled consent button appears that was not on the previous
    layer (second layers often load into a fresh iframe), or until max_wait."""
    seen = {(b["frame_url"], b["text"]) for b in before if b["context"] and b["role"]}
    waited, n = 0.0, 0
    while True:
        time.sleep(step)
        waited += step
        n += 1
        b2, t2, _, _ = scan(page, f"b{n}")
        if any(b["context"] and b["role"] and (b["frame_url"], b["text"]) not in seen for b in b2) or waited >= max_wait:
            return b2, t2


def _frame_visible(frame):
    try:
        el = frame.frame_element()
        box = el.bounding_box()
        return bool(box and box["width"] > 20 and box["height"] > 20 and el.is_visible())
    except Exception:
        return False


def _rank(b, anchor=None):
    # Prefer the same banner (group) as the anchor button, then the same frame, then overlays, then top-most.
    if anchor is None:
        # No anchor yet: the most prominent banner wins (largest on-screen overlay).
        return (0 if b["overlay"] else 1, -b.get("group_area", 0), b["box"][1])
    same_group = b["group"] is not None and b["group"] == anchor.get("group")
    return (0 if same_group else 1, 0 if b["frame"] == anchor["frame"] else 1, 0 if b["overlay"] else 1, b["box"][1])


def pick(buttons, role, anchor=None):
    cands = [b for b in buttons if b["context"] and b["role"] == role]
    return sorted(cands, key=lambda b: _rank(b, anchor))[0] if cands else None


def detect_bot_wall(status, texts, frame_urls):
    main = texts[0] if texts else {"title": "", "text": ""}
    body = main["text"] or ""
    if any(CHALLENGE_FRAME.search(u or "") for u in frame_urls) and len(body) < 3000:
        return "challenge frame"
    if patterns.BOT_WALL.search(main["title"] or ""):
        return f"title: {main['title'][:80]}"
    if len(body) < 3000 and patterns.BOT_WALL.search(body):
        return "challenge text: " + patterns.BOT_WALL.search(body).group(0)
    if status and status in (401, 403, 429, 503) and len(body) < 3000:
        return f"http {status}"
    return None


def preticked(toggles):
    """Pre-ticked, user-changeable, non-necessary toggles, deduped by (frame, label)."""
    seen, out = set(), []
    for t in toggles:
        if not t["checked"] or t["disabled"]:
            continue
        if patterns.NECESSARY.search(t["label"] or "") and not t["legit_interest"]:
            continue
        key = (t["frame"], t["label"])
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


class Site:
    """Holds the page, the request log and the evidence for one measurement."""

    def __init__(self, page, out_dir):
        self.page = page
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        self.requests = []
        self.events = []
        self.shots = []
        page.context.on("request", self._on_request)

    def _on_request(self, req):
        try:
            u = urlsplit(req.url)
        except ValueError:
            return
        if u.scheme not in ("http", "https"):
            return
        self.requests.append({"t": round(time.time() - self.t0, 2), "host": u.hostname or "",
                              "url": f"{u.scheme}://{u.netloc}{u.path}"[:300], "type": req.resource_type})

    def now(self):
        return round(time.time() - self.t0, 2)

    def shot(self, name):
        p = self.out / f"{name}.jpg"
        try:
            self.page.screenshot(path=str(p), type="jpeg", quality=60, timeout=15000)
            self.shots.append(p.name)
        except Exception as e:
            self.events.append({"t": self.now(), "event": "screenshot_failed", "name": name, "error": str(e)[:200]})

    def click(self, b, why):
        frame = self.page.frames[b["frame"]] if b["frame"] < len(self.page.frames) else None
        ev = {"t": self.now(), "event": "click", "why": why, "text": b.get("text") or b.get("label", ""), "id": b["id"]}
        if frame is None:
            ev["result"] = "frame_gone"
            self.events.append(ev)
            return False
        loc = frame.locator(f'[data-rai-id="{b["id"]}"]').first
        try:
            loc.click(timeout=5000)
            ev["result"] = "ok"
        except Exception:
            try:
                loc.evaluate("el => el.click()", timeout=5000)
                ev["result"] = "ok_js"
            except Exception as e:
                ev["result"] = "failed: " + str(e)[:160]
        self.events.append(ev)
        return ev["result"].startswith("ok")

    def still_visible(self, b):
        try:
            frame = self.page.frames[b["frame"]]
            el = frame.locator(f'[data-rai-id="{b["id"]}"]').first
            if not el.is_visible(timeout=2000):
                return False
            # Playwright ignores opacity; banners often fade out on an ancestor.
            if not el.evaluate("e => !e.checkVisibility || e.checkVisibility({opacityProperty: true, visibilityProperty: true})"):
                return False
            box, vp = el.bounding_box(timeout=2000), self.page.viewport_size
            return bool(box) and (vp is None or _on_screen((box["x"], box["y"], box["width"], box["height"]), vp))
        except Exception:
            return False


def measure(page, url, domain, out_dir, tracker_list, locator=None, settle=SETTLE_S,
            layer_wait=LAYER_WAIT_S, after_wait=AFTER_WAIT_S, scan_step=2.0):
    s = Site(page, out_dir)
    r = {"domain": domain, "url": url, "status": None, "reason": None, "final_url": None,
         "accept_clicks": None, "reject_clicks": None, "reject_second_layer": None,
         "reject_path": None, "preticked_toggles": 0, "preticked_legit_interest": 0,
         "pay_or_ok": False, "verified": None, "llm_used": False, "llm_calls": [],
         "pre_consent_trackers": [], "trackers_after_reject": [], "cmp_hint": None}
    status = None
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        status = resp.status if resp else None
        try:
            page.wait_for_load_state("load", timeout=15000)
        except Exception:
            s.events.append({"t": s.now(), "event": "load_timeout"})
        time.sleep(settle)
    except Exception as e:
        r["status"], r["reason"] = "unmeasurable", "load_error: " + str(e).split("\n")[0][:160]
        s.shot("01_landing")
        return _finish(r, s, tracker_list, domain, None)
    r["http_status"] = status
    r["final_url"] = page.url

    b1, t1, texts, groups1 = stable_scan(page, scan_step)
    wall = detect_bot_wall(status, texts, [f.url for f in page.frames])
    s.shot("01_landing")
    if wall:
        r["status"], r["reason"] = "unmeasurable", "bot wall: " + wall
        return _finish(r, s, tracker_list, domain, None)

    accept = pick(b1, "accept")
    anchor = accept
    # Only consider the accept button's own banner; widen to its frame only if that
    # banner offers no alternative at all (some CMPs split buttons across containers).
    pool1 = b1
    if anchor is not None and anchor.get("group"):
        same = [b for b in b1 if b["group"] == anchor["group"]]
        if any(b["role"] in ("reject", "settings", "save", "pay") and b["context"] for b in same):
            pool1 = same
        else:
            pool1 = [b for b in b1 if b["frame"] == anchor["frame"] and b["overlay"]]
    reject = pick(pool1, "reject", anchor)
    settings = pick(pool1, "settings", anchor)
    save = pick(pool1, "save", anchor)
    pay = pick(pool1, "pay", anchor)
    if anchor is None:
        anchor = reject

    # LLM fallback: a consent UI is on screen but rules could not label it fully.
    consent_visible = any(b["context"] and b["overlay"] for b in b1)
    need_llm = (consent_visible and not accept and not reject) or (accept and not reject and not settings and not pay)
    if need_llm and locator is not None:
        if anchor is not None and anchor.get("group"):
            pool = [b for b in b1 if b["group"] == anchor["group"]]
        else:
            pool = [b for b in b1 if b["context"] and b["overlay"]]
        if pool:
            pool = [b for b in pool if b["role"] is None or b is accept]  # rules win over the LLM
            roles, log = locator.locate([{"id": b["id"], "text": b["text"]} for b in pool])
            r["llm_used"] = True
            log["layer"] = 1
            log["result"] = roles
            r["llm_calls"].append(log)
            byid = {b["id"]: b for b in pool}
            for bid, role in roles.items():
                b = byid[bid]
                if role == "accept" and not accept:
                    accept = dict(b, role="accept", via="llm")
                elif role == "reject" and not reject:
                    reject = dict(b, role="reject", via="llm")
                elif role == "settings" and not settings:
                    settings = dict(b, role="settings", via="llm")
            anchor = accept or reject or settings or anchor
            r["llm_located"] = [k for k, v in (("accept", accept), ("reject", reject), ("settings", settings))
                                if v and v.get("via") == "llm"]

    if not accept and not reject:
        r["status"] = "no_banner"
        r["reason"] = "no consent buttons found" + (" (consent-like overlay seen)" if consent_visible else "")
        return _finish(r, s, tracker_list, domain, None)

    r["status"] = "measured"
    r["cmp_hint"] = _cmp_hint(b1, texts)
    banner_text = groups1.get((anchor or {}).get("group"), {}).get("text", "")
    r["banner_text"] = banner_text[:600]
    r["pay_or_ok"] = not reject and (bool(pay) or bool(patterns.PAY_TEXT.search(banner_text)))
    others = {b["group"] for b in b1 if b["context"] and b["role"] == "accept" and b["group"]
              and b["group"] != (anchor or {}).get("group")}
    r["extra_banners"] = [groups1.get(g, {}).get("text", "")[:200] for g in sorted(others)]
    r["accept_clicks"] = 1 if accept else None
    r["layer1"] = _brief(b1)
    pre1 = preticked([t for t in t1 if t["visible"]])
    choosable1 = [t for t in t1 if t["visible"] and not t["disabled"]]
    first_click = None

    if reject:
        first_click = s.now()
        s.click(reject, "reject_layer1")
        r.update(reject_clicks=1, reject_second_layer=False, reject_path="first_layer_button")
    elif save and (pre1 or choosable1):
        # Toggles on the first layer: untick any pre-ticked ones, then save. With every
        # optional box already off, "accept selection" is a one-click reject.
        first_click = s.now()
        for t in pre1:
            s.click(t, "untick")
        s.click(save, "save_layer1")
        r.update(reject_clicks=len(pre1) + 1, reject_second_layer=False, reject_path="untick_and_save_layer1")
    elif settings:
        first_click = s.now()
        s.click(settings, "open_settings")
        b2, t2 = wait_new_layer(page, b1, layer_wait)
        s.shot("02_layer2")
        r["layer2"] = _brief(b2)
        # Layer 2 is often a new dialog: anchor on frame only, not the old group.
        a2 = {"frame": anchor["frame"], "group": None} if anchor else None
        reject2 = pick(b2, "reject", a2)
        save2 = pick(b2, "save", a2)
        pre2 = preticked([t for t in t2 if t["visible"]])
        allpre2 = preticked(t2)
        r["preticked_toggles"] = len(allpre2)
        r["preticked_legit_interest"] = sum(1 for t in allpre2 if t["legit_interest"])
        r["preticked_hidden"] = len(allpre2) - len(pre2)
        if reject2 is None and save2 is None and locator is not None:
            pool = [b for b in b2 if b["context"] and b["role"] is None]
            if pool:
                roles, log = locator.locate([{"id": b["id"], "text": b["text"]} for b in pool])
                r["llm_used"] = True
                log["layer"] = 2
                log["result"] = roles
                r["llm_calls"].append(log)
                for bid, role in roles.items():
                    if role == "reject":
                        reject2 = dict(next(b for b in pool if b["id"] == bid), via="llm")
                        r.setdefault("llm_located", []).append("reject_layer2")
        # Layer 2 may open in a new iframe; judge per-purpose rejects in the frame the best reject lives in.
        f2 = reject2["frame"] if reject2 else (a2 or {}).get("frame")
        rej2 = [b for b in b2 if b["context"] and b["role"] == "reject" and (f2 is None or b["frame"] == f2)]
        alls = [b for b in rej2 if patterns.ALL_WORD.search(b["text"])]
        texts2 = [patterns.normalize(b["text"]) for b in rej2]
        per_purpose = not alls and len(rej2) >= 2 and len(set(texts2)) < len(texts2)
        if alls:
            reject2 = sorted(alls, key=lambda b: _rank(b, a2))[0]
        if reject2 and not per_purpose:
            s.click(reject2, "reject_layer2")
            r.update(reject_clicks=2, reject_second_layer=True, reject_path="second_layer_button")
        elif per_purpose and save2:
            # Only per-purpose "reject" buttons: click each, then save. No reject-all exists.
            for b in rej2:
                s.click(b, "reject_purpose")
            s.click(save2, "save_layer2")
            r.update(reject_clicks=1 + len(rej2) + 1, reject_second_layer=True, reject_path="per_purpose_and_save_layer2")
        elif save2:
            for t in pre2:
                s.click(t, "untick")
            s.click(save2, "save_layer2")
            r.update(reject_clicks=1 + len(pre2) + 1, reject_second_layer=True,
                     reject_path="untick_and_save_layer2")
        else:
            r.update(reject_clicks=None, reject_second_layer=True, reject_path="none_found")
    else:
        r.update(reject_clicks=None, reject_second_layer=None, reject_path="none_found")

    if not r["preticked_toggles"] and pre1:
        r["preticked_toggles"] = len(pre1)
        r["preticked_legit_interest"] = sum(1 for t in pre1 if t["legit_interest"])

    if first_click is not None and r["reject_clicks"] is not None:
        time.sleep(after_wait)
        b3, _, _, _ = scan(page, "c")
        vp = page.viewport_size or {"width": 10 ** 5, "height": 10 ** 5}
        # Banners often slide out of view before leaving the DOM: only on-screen buttons count.
        left = [b["text"][:60] for b in b3 if b["context"] and b["overlay"] and b["role"] in ("accept", "reject", "save")
                and _on_screen(b["box"], vp)]
        r["remaining_consent_buttons"] = left
        r["verified"] = not s.still_visible(accept or reject) and not left
        s.shot("03_after_reject")
    return _finish(r, s, tracker_list, domain, first_click)


def _on_screen(box, vp):
    x, y, w, h = box
    return x < vp["width"] and y < vp["height"] and x + w > 0 and y + h > 0


def _cmp_hint(buttons, texts):
    names = ["onetrust", "didomi", "cookiebot", "usercentrics", "sourcepoint", "quantcast", "trustarc",
             "borlabs", "iubenda", "osano", "consentmanager", "funding choices", "cookieyes", "complianz", "axeptio"]
    hay = " ".join(b.get("frame_url", "") for b in buttons).lower()
    for n in names:
        if n.replace(" ", "") in hay:
            return n
    return None


def _brief(buttons):
    ctx = [b for b in buttons if b["context"]]
    ctx.sort(key=lambda b: (b["role"] is None, not b["overlay"]))
    return [{"text": b["text"][:60], "role": b["role"], "frame": b["frame"], "group": b["group"],
             "overlay": b["overlay"]} for b in ctx][:40]


def _finish(r, s, tracker_list, domain, first_click):
    cut = first_click if first_click is not None else float("inf")
    pre = [q for q in s.requests if q["t"] < cut]
    r["pre_consent_trackers"] = summarize(pre, tracker_list, domain)
    r["pre_consent_requests"] = len(pre)
    if first_click is not None:
        post = [q for q in s.requests if q["t"] >= first_click]
        pre_domains = {t["domain"] for t in r["pre_consent_trackers"]}
        r["trackers_after_reject"] = [t for t in summarize(post, tracker_list, domain) if t["domain"] not in pre_domains]
    r["first_click_t"] = first_click
    r["screenshots"] = s.shots
    r["events"] = s.events
    (s.out / "requests.json").write_text(json.dumps(s.requests, indent=0), encoding="utf-8")
    (s.out / "evidence.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
    return r
