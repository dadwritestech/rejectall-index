import json
import xml.etree.ElementTree as ET

from rejectall.badge import badge_for, fact
from rejectall.site import build, coverage
from rejectall.scoring import score


def site(**kw):
    r = {"domain": "x.test", "rank": 1, "status": "measured", "accept_clicks": 1, "reject_clicks": 1,
         "reject_path": "first_layer_button", "pay_or_ok": False, "preticked_toggles": 0,
         "pre_consent_trackers": [], "verified": True, "screenshots": ["01_landing.jpg"], "llm_used": False,
         "llm_calls": []}
    r.update(kw)
    r["score"], r["grade"], r["penalties"] = score(r)
    return r


def test_badge_states_the_fact():
    assert fact(site()) == ("1 click", "#44cc11")
    assert fact(site(reject_clicks=2, reject_path="second_layer_button"))[0] == "2 clicks"
    assert fact(site(reject_clicks=None, reject_path="none_found"))[0] == "no option"
    assert fact(site(pay_or_ok=True, reject_clicks=None))[0] == "pay or ok"
    assert fact(site(status="unmeasurable"))[0] == "unmeasurable"
    assert fact(site(status="no_banner"))[0] == "no banner"


def test_badge_is_valid_svg_and_escapes():
    svg = badge_for(site())
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and "reject: 1 click" in root.get("aria-label")


def test_build_writes_page_badges_and_coverage(tmp_path):
    sites = [site(domain="good.test"), site(domain="bad.test", rank=2, reject_clicks=None, reject_path="none_found",
             pre_consent_trackers=[{"domain": "doubleclick.net"}]),
             site(domain="wall.test", rank=3, status="unmeasurable", reason="bot wall: captcha"),
             site(domain="quiet.test", rank=4, status="no_banner", accept_clicks=None, reject_clicks=None)]
    meta = {"date": "2026-10-30", "vantage": {"country": "DE", "description": "Test box in Germany",
            "locale": "de-DE", "timezone": "Europe/Berlin"}, "browser": "chromium 1", "user_agent": "UA",
            "tracker_list": "Disconnect", "tracker_list_sha256": "ab" * 32, "timing_s": {"pause_between_sites": 3}}
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "latest.json").write_text(json.dumps({"meta": meta, "sites": sites}), encoding="utf-8")
    build(tmp_path)
    html = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "Test box in Germany" in html and "Hall of Shame" in html
    assert "bot wall: captcha" in html
    assert "../data/runs/2026-10-30/sites/good.test/01_landing.jpg" in html
    assert {p.name for p in (tmp_path / "site" / "badges").iterdir()} == {f"{s['domain']}.svg" for s in sites}
    c = coverage(sites)
    assert (c["measured"], c["no_banner"], c["unmeasurable"], c["no_reject"], c["with_trackers"]) == (2, 1, 1, 1, 1)
    # Worst measured site leads the Hall of Shame.
    assert html.index("bad.test") < html.index("good.test")
