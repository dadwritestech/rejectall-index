import functools
import http.server
import json
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from rejectall.trackers import TrackerList

ROOT = Path(__file__).resolve().parent
FIX = ROOT / "fixtures"

# A tiny, hand-written tracker list so tests never need the network.
SERVICES = {"categories": {
    "Analytics": [{"Google": {"https://google.com": ["google-analytics.com"]}}],
    "Advertising": [{"Google": {"https://google.com": ["doubleclick.net"]}}],
    "Content": [{"Cdnco": {"https://cdn.example": ["cdn.example"]}}],
}}
ENTITIES = {"entities": {"Google": {"properties": ["google.com", "youtube.com"], "resources": ["doubleclick.net", "google-analytics.com"]}}}
FAKE_HOSTS = ("google-analytics.com", "doubleclick.net")


@pytest.fixture(scope="session")
def tracker_list():
    return TrackerList(SERVICES, ENTITIES)


@pytest.fixture(scope="session")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIX))
    handler.log_message = lambda *a, **k: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, locale="de-DE")

    def fake(route):
        route.fulfill(status=200, body="", content_type="application/javascript")

    ctx.route(lambda u: any(h in u for h in FAKE_HOSTS), fake)
    pg = ctx.new_page()
    yield pg
    ctx.close()
