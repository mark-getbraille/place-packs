"""A polite web client for the chain store-locator collectors (placepacks/chains).

What "polite" means here (the owner's rules of 26 November 2026, notes/helper-rules.txt):
  - every request names the project in its User-Agent (USER_AGENT), so a chain can see who is asking;
  - at least `pause` seconds (never less than MIN_PAUSE, one second) between two requests to the same host;
  - a fixed number of requests per run (the chain's "budget"): when it is spent, the collector stops (BudgetSpent);
  - a server error or a dropped connection is tried again after a growing wait (WAITS), a few times only;
  - a refusal is never worked around. HTTP 401, 403, 407, 429 or 451, or an anti-bot challenge page (Cloudflare's
    "Just a moment...", Akamai's "Access Denied", DataDome's captcha-delivery, Imperva/Incapsula, PerimeterX) stops
    the collector at once with Blocked: the run summary then says "blocked" for that chain. No CAPTCHA is solved,
    no browser is faked, no cookie or login is used.
Answers are asked for with gzip, to save the chain's bandwidth and ours.

Only the Python standard library is used. Tests give a stand-in `opener` (see Polite.__init__).
"""

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "place-packs-chain-locators/1 (+https://github.com/mark-getbraille/place-packs)"
MIN_PAUSE = 1.0                  # seconds between two requests to one host, whatever a chain's setting says
WAITS = (15, 60, 180)            # seconds before each new try after a server error or a dropped connection
TIMEOUT = 60                     # seconds a request may take
MAX_BYTES = 30 * 1024 * 1024     # an answer larger than this is cut off (no store page or API answer is this big)

# Words of the anti-bot challenge pages. A page with one of them is a refusal, whatever its HTTP status.
CHALLENGES = ("<title>just a moment", "cf-chl-", "/cdn-cgi/challenge-platform", "captcha-delivery.com",
              "_incapsula_resource", "px-captcha", "perimeterx", "<title>access denied</title>",
              "errors.edgesuite.net", "please verify you are a human", "are you a robot")
REFUSED = {401, 403, 407, 429, 451}


class Blocked(Exception):
    """The chain's site refused us (an HTTP refusal or a challenge page). The collector stops; never retried."""


class BudgetSpent(Exception):
    """The chain's request budget for this run is used up. The collector stops (its rows are incomplete)."""


class NotFound(Exception):
    """HTTP 404 or 410: a store page that has gone. A collector usually skips it and goes on."""


class RequestFailed(Exception):
    """A request that still failed after every retry (server errors, timeouts)."""


def challenge(text):
    """True when a page is an anti-bot challenge (see CHALLENGES). Only the first 20,000 characters are looked at:
    a challenge page is small, and a real store page that merely mentions a word deep inside is not one."""
    head = (text or "")[:20000].lower()
    return any(word in head for word in CHALLENGES)


def _urllib_opener(request, timeout):
    """Send a request with urllib. Returns (status, headers dict, body bytes); an HTTP error is an answer too."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            return r.status, dict(r.headers.items()), r.read(MAX_BYTES)
    except urllib.error.HTTPError as e:
        try:
            body = e.read(MAX_BYTES)
        except Exception:  # noqa: BLE001 - an error without a body
            body = b""
        return e.code, dict(e.headers.items()) if e.headers else {}, body


class Polite:
    """One chain's client for one run. budget: the most requests it may send; pause: seconds between two requests
    to one host (at least MIN_PAUSE). opener(request, timeout) -> (status, headers, body) and sleep/clock are for
    tests; deadline: a clock() time after which no new request is sent (the job's time limit: BudgetSpent);
    agent: the User-Agent (default USER_AGENT; the local-directory collectors name themselves, placepacks/
    directories). .used is the number of requests sent; .hosts the hosts asked."""

    def __init__(self, budget, pause=1.5, opener=None, sleep=time.sleep, clock=time.monotonic, waits=WAITS,
                 deadline=None, agent=USER_AGENT):
        """See the class docstring."""
        self.budget, self.pause, self.deadline = int(budget), max(MIN_PAUSE, float(pause)), deadline
        self.agent = agent
        self.opener, self.sleep, self.clock, self.waits = opener or _urllib_opener, sleep, clock, tuple(waits)
        self.used, self.last, self.hosts = 0, {}, set()

    def _wait_for(self, host):
        """Sleep until `pause` seconds have passed since the last request to host."""
        if host in self.last:
            left = self.last[host] + self.pause - self.clock()
            if left > 0:
                self.sleep(left)

    def fetch(self, url, data=None, headers=None):
        """The body of url as text (GET, or POST of `data`: a dict is sent as JSON). Raises Blocked, BudgetSpent,
        NotFound or RequestFailed (see the module docstring)."""
        host = urllib.parse.urlsplit(url).hostname or ""
        send = {"User-Agent": self.agent, "Accept-Encoding": "gzip",
                "Accept": "application/json, text/html;q=0.9, application/xml;q=0.9, */*;q=0.5"}
        send.update(headers or {})
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode("utf-8")
            send.setdefault("Content-Type", "application/json")
        for attempt in range(len(self.waits) + 1):
            if self.used >= self.budget:
                raise BudgetSpent(f"the budget of {self.budget} requests is spent")
            if self.deadline is not None and self.clock() >= self.deadline:
                raise BudgetSpent("the time limit of the run is reached")
            self._wait_for(host)
            self.used += 1
            self.hosts.add(host)
            request = urllib.request.Request(url, data=data, headers=send, method="POST" if data else "GET")
            try:
                status, got_headers, body = self.opener(request, TIMEOUT)
                error = ""
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                status, got_headers, body, error = 0, {}, b"", f"{type(e).__name__}: {e}"
            self.last[host] = self.clock()
            lowered = {str(k).lower(): v for k, v in (got_headers or {}).items()}
            if body[:2] == b"\x1f\x8b":                  # gzip, asked for or a .gz sitemap
                try:
                    body = gzip.decompress(body)
                except (OSError, EOFError):
                    pass
            text = body.decode(_charset(lowered.get("content-type", "")), "replace")
            if status in REFUSED:
                page = ", a challenge page" if challenge(text) else ""
                raise Blocked(f"{host} refused the request (HTTP {status}{page})")
            if challenge(text) and not (200 <= status < 300 and len(text) > 200000):
                raise Blocked(f"{host} answered with an anti-bot challenge page (HTTP {status})")
            if status in (404, 410):
                raise NotFound(f"{url}: HTTP {status}")
            if 200 <= status < 300:
                return text
            error = error or f"HTTP {status}"
            if attempt < len(self.waits) and (status == 0 or status >= 500 or status == 408):
                self.sleep(self.waits[attempt])
                continue
            raise RequestFailed(f"{url}: {error}")
        raise RequestFailed(f"{url}: no answer")                     # not reached

    def json(self, url, data=None, headers=None):
        """fetch() read as JSON. A page that is not JSON (an error page) raises RequestFailed."""
        text = self.fetch(url, data, headers)
        try:
            return json.loads(text)
        except ValueError:
            raise RequestFailed(f"{url}: the answer is not JSON ({' '.join(text[:80].split())!r})") from None


def _charset(content_type):
    """The charset named in a Content-Type header, else utf-8."""
    for part in content_type.split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "charset" and value.strip():
            try:
                "".encode(value.strip().strip('"'))
                return value.strip().strip('"')
            except LookupError:
                break
    return "utf-8"
