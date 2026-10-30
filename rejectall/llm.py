"""LLM fallback: only used to *locate* buttons when the deterministic rules find a
consent UI but cannot tell which button is which. It never scores anything.
Every call (prompt, answer, latency, error) is returned for the evidence log.

The key for the shared local llama-server is read at run time from the
LLAMA_API_KEY env var or from the llama-server process command line. It is never
written to disk.
"""
import json
import os
import re
import subprocess
import time
import urllib.request

ENDPOINT = os.environ.get("REJECTALL_LLM_URL", "http://localhost:8080/v1/chat/completions")
MODEL = os.environ.get("REJECTALL_LLM_MODEL", "gemma-4-12b")


def find_key():
    if os.environ.get("LLAMA_API_KEY"):
        return os.environ["LLAMA_API_KEY"]
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like 'llama-server%'\" | % { $_.CommandLine }"],
            capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    m = re.search(r"--api-key\s+(\S+)", out or "")
    return m.group(1).strip('"') if m else None


class Locator:
    """Small, rate-limited client. Disables itself after repeated stalls."""

    def __init__(self, key=None, timeout=60, max_failures=3):
        self.key = key if key is not None else find_key()
        self.timeout = timeout
        self.failures = 0
        self.max_failures = max_failures

    @property
    def available(self):
        return bool(self.key) and self.failures < self.max_failures

    def locate(self, buttons):
        """buttons: list of {"id","text"}. Returns (roles dict id->role, log dict)."""
        shown = buttons[:30]
        lines = "\n".join(f"{i}: {b['text'][:60]}" for i, b in enumerate(shown))
        prompt = (
            "These are clickable labels from a website's cookie consent banner.\n"
            f"{lines}\n"
            "Which index accepts all cookies, which rejects all non-essential cookies, "
            "and which opens cookie settings? Use null if none. "
            'Answer only JSON: {"accept": n|null, "reject": n|null, "settings": n|null}'
        )
        log = {"model": MODEL, "prompt": prompt, "answer": None, "error": None, "ms": None}
        if not self.available:
            log["error"] = "llm unavailable (no key or disabled after stalls)"
            return {}, log
        body = json.dumps({
            "model": MODEL, "temperature": 0, "max_tokens": 60,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(ENDPOINT, data=body, headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
            text = data["choices"][0]["message"]["content"]
            log["answer"] = text
            self.failures = 0
        except Exception as e:  # stall, refusal, bad gateway: log and move on
            self.failures += 1
            log["error"] = f"{type(e).__name__}: {e}"[:300]
            return {}, log
        finally:
            log["ms"] = int((time.time() - t0) * 1000)
        return parse_answer(text, shown), log


def parse_answer(text, shown):
    m = re.search(r"\{.*?\}", text or "", re.S)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    roles = {}
    for role in ("accept", "reject", "settings"):
        i = obj.get(role)
        if isinstance(i, int) and 0 <= i < len(shown):
            roles.setdefault(shown[i]["id"], role)
    return roles
