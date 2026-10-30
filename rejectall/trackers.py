"""Match request hosts against Disconnect's public tracker list.

The list (CC BY-NC-SA 4.0) is downloaded at run time into cache/ and its
sha256 is written into every run's metadata. It is not committed here.
"""
import hashlib
import json
import urllib.request
from pathlib import Path

import tldextract

SERVICES_URL = "https://raw.githubusercontent.com/disconnectme/disconnect-tracking-protection/master/services.json"
ENTITIES_URL = "https://raw.githubusercontent.com/disconnectme/disconnect-tracking-protection/master/entities.json"

# Categories that count as tracking. "Content" (embeds/CDNs), "Email*", "Anti-fraud"
# and "ConsentManagers" are excluded: loading a consent manager before consent is expected.
TRACKING_CATEGORIES = {
    "Advertising", "Analytics", "Social", "FingerprintingInvasive", "FingerprintingGeneral", "Cryptomining",
}

# Offline extractor: uses the public-suffix snapshot bundled with tldextract.
_extract = tldextract.TLDExtract(suffix_list_urls=())


def site_of(host):
    """Registrable domain (eTLD+1) of a host."""
    e = _extract(host or "")
    return e.top_domain_under_public_suffix or (host or "").lower()


def fetch_lists(cache_dir):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, url in (("services", SERVICES_URL), ("entities", ENTITIES_URL)):
        p = cache_dir / f"disconnect-{name}.json"
        if not p.exists():
            urllib.request.urlretrieve(url, p)
        out[name] = p
    return out


class TrackerList:
    def __init__(self, services, entities):
        self.domain_info = {}  # tracker domain -> (entity, category)
        for cat, items in services["categories"].items():
            if cat not in TRACKING_CATEGORIES:
                continue
            for item in items:
                for entity, urls in item.items():
                    for key, domains in urls.items():
                        if not isinstance(domains, list):
                            continue
                        for d in domains:
                            self.domain_info.setdefault(d.lower(), (entity, cat))
        # entity -> all domains it owns (properties + resources), for first-party exclusion
        self.entity_domains = {}
        for entity, v in entities.get("entities", {}).items():
            self.entity_domains[entity] = {d.lower() for d in v.get("properties", []) + v.get("resources", [])}

    @classmethod
    def load(cls, services_path, entities_path):
        s = Path(services_path).read_bytes()
        e = Path(entities_path).read_bytes()
        tl = cls(json.loads(s), json.loads(e))
        tl.sha256 = hashlib.sha256(s).hexdigest()[:16] + "/" + hashlib.sha256(e).hexdigest()[:16]
        return tl

    def lookup(self, host):
        """(matched_domain, entity, category) if host is on the list, else None."""
        host = (host or "").lower().rstrip(".")
        parts = host.split(".")
        for i in range(len(parts) - 1):
            cand = ".".join(parts[i:])
            if cand in self.domain_info:
                ent, cat = self.domain_info[cand]
                return cand, ent, cat
        return None

    def third_party_tracker(self, host, site_domain):
        """Tracker match for host, unless it is first-party for site_domain."""
        m = self.lookup(host)
        if not m:
            return None
        matched, entity, cat = m
        site = site_of(site_domain)
        if site_of(host) == site:
            return None
        if site in self.entity_domains.get(entity, ()):
            return None  # same owner, e.g. doubleclick.net on google.com
        return {"domain": matched, "entity": entity, "category": cat}


def summarize(requests, tracker_list, site_domain):
    """Distinct third-party tracker domains among request dicts {url, host, ...}."""
    found = {}
    for r in requests:
        m = tracker_list.third_party_tracker(r["host"], site_domain)
        if m:
            f = found.setdefault(m["domain"], dict(m, requests=0))
            f["requests"] += 1
    return sorted(found.values(), key=lambda x: (-x["requests"], x["domain"]))
