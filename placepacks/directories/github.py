"""A small client for GitHub's REST API, for the collectors that read and write this repository's releases outside
the pack build: the Yellow Pages lookup job (tools/yp_lookup.py, run in the owner's cloud session, where the API
answers without a token argument: the session's proxy signs the requests) and the web-details workflow (where the
job's own GITHUB_TOKEN is given as GH_TOKEN).

What it does: find a release by its tag (or make it), list its files, download one (the file itself, from
GitHub's storage, is fetched without the token: GitHub sends it to a signed address that refuses a second
signature), upload one, delete one; and read the published packs' list (packs.json in the release "packs") to find
a region's newest pack of a part (packs_of).
Only the Python standard library is used. Tests replace `opener`.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
AGENT = "place-packs-collectors (+https://github.com/mark-getbraille/place-packs)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is handed back to the caller (download() follows it itself, without the token)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Do not follow."""
        return None


def _urllib_opener(request, sink=None, timeout=300):
    """Send a request without following redirects. Returns (status, headers dict, body bytes); with sink (an open
    file), a successful answer's body is copied into it in pieces instead (a pack can be a gigabyte) and b"" is
    returned."""
    import shutil
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as r:
            if sink is not None and r.status == 200:
                shutil.copyfileobj(r, sink, 1024 * 1024)
                return r.status, dict(r.headers.items()), b""
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        body = e.read() if e.fp else b""
        return e.code, dict(e.headers.items()) if e.headers else {}, body


class GitHubError(RuntimeError):
    """The API answered with an error (the status and its message are in the text)."""


class GitHub:
    """The REST client for one repository (default: GITHUB_REPOSITORY, else the project's own). token: GH_TOKEN or
    GITHUB_TOKEN when set (in Actions); none in the owner's cloud session (its proxy signs the requests)."""

    def __init__(self, repo=None, token=None, opener=None):
        """See the class docstring."""
        from placepacks.uploaded import repo as default_repo
        self.repo = repo or default_repo()
        self.token = token if token is not None else (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
                                                      or "")
        self.opener = opener or _urllib_opener

    def _send(self, method, url, data=None, headers=None, signed=True, sink=None):
        """(status, headers, body) of one request; JSON data is sent as JSON; sink: see _urllib_opener."""
        send = {"User-Agent": AGENT, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token and signed:
            send["Authorization"] = f"Bearer {self.token}"
        send.update(headers or {})
        if data is not None and not isinstance(data, bytes):
            data = json.dumps(data).encode("utf-8")
            send.setdefault("Content-Type", "application/json")
        return self.opener(urllib.request.Request(url, data=data, headers=send, method=method), sink)

    def call(self, method, path, data=None, ok=(200, 201, 204)):
        """The JSON answer of an API call (path: "/repos/..." or a full address). Raises GitHubError."""
        url = path if path.startswith("http") else API + path
        status, _, body = self._send(method, url, data)
        if status not in ok:
            raise GitHubError(f"{method} {url}: HTTP {status} {body[:200].decode('utf-8', 'replace')}")
        return json.loads(body) if body.strip() else {}

    def release(self, tag):
        """The release of a tag (dict), or None when there is none."""
        status, _, body = self._send("GET", f"{API}/repos/{self.repo}/releases/tags/{urllib.parse.quote(tag)}")
        if status == 404:
            return None
        if status != 200:
            raise GitHubError(f"release {tag}: HTTP {status} {body[:200].decode('utf-8', 'replace')}")
        return json.loads(body)

    def ensure_release(self, tag, title, notes):
        """The release of a tag, made (not marked latest) when there is none."""
        found = self.release(tag)
        if found:
            return found
        return self.call("POST", f"/repos/{self.repo}/releases", {"tag_name": tag, "name": title, "body": notes,
                                                                    "make_latest": "false"})

    def assets(self, release):
        """Every file of a release: [{"id", "name", "size", ...}], page by page."""
        out, page = [], 1
        while True:
            got = self.call("GET", f"/repos/{self.repo}/releases/{release['id']}/assets?per_page=100&page={page}")
            out += got
            if len(got) < 100:
                return out
            page += 1

    def download(self, asset, path):
        """Download a release file (an assets() item) to path. Returns path."""
        url = f"{API}/repos/{self.repo}/releases/assets/{asset['id']}"
        with open(path + ".partial", "wb") as f:
            status, headers, _ = self._send("GET", url, headers={"Accept": "application/octet-stream"}, sink=f)
            for _ in range(3):
                if status not in (301, 302, 303, 307, 308):
                    break
                location = {k.lower(): v for k, v in headers.items()}.get("location", "")
                status, headers, _ = self._send("GET", location, headers={"Accept": "application/octet-stream"},
                                                signed=False, sink=f)
        if status != 200:
            os.remove(path + ".partial")
            raise GitHubError(f"download {asset.get('name')}: HTTP {status}")
        os.replace(path + ".partial", path)
        return path

    def upload(self, release, path, name=None, content_type="application/gzip"):
        """Upload a file to a release under name (default: its own); an older file of the same name is replaced.
        Returns the new asset."""
        name = name or os.path.basename(path)
        for old in self.assets(release):
            if old["name"] == name:
                self.delete(old)
        with open(path, "rb") as f:
            data = f.read()
        url = f"{UPLOADS}/repos/{self.repo}/releases/{release['id']}/assets?name={urllib.parse.quote(name)}"
        status, _, body = self._send("POST", url, data, headers={"Content-Type": content_type})
        if status not in (200, 201):
            raise GitHubError(f"upload {name}: HTTP {status} {body[:200].decode('utf-8', 'replace')}")
        return json.loads(body)

    def delete(self, asset):
        """Delete a release file."""
        self.call("DELETE", f"/repos/{self.repo}/releases/assets/{asset['id']}", ok=(204, 404))

    def packs_of(self, folder, manifest=None):
        """The published packs' list: {(region, part): {"name", "release", "size", "sha256"}} from packs.json in the
        release "packs" (downloaded into folder unless manifest, a path, is given)."""
        if manifest is None:
            rel = self.release("packs")
            item = next((a for a in self.assets(rel) if a["name"] == "packs.json"), None) if rel else None
            if not item:
                return {}
            manifest = self.download(item, os.path.join(folder, "packs.json"))
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
        packs = data.get("packs", [])
        if isinstance(packs, dict):             # packs.json keeps its packs by key ({"us-vermont": {...}, ...})
            packs = list(packs.values())
        return {(p["region"], p["part"]): p for p in packs
                if isinstance(p, dict) and p.get("region") and p.get("part")}

    def download_pack(self, info, folder):
        """Download one pack (a packs_of() item) from its release into folder; checked by its SHA-256. Returns the
        path."""
        from placepacks.uploaded import sha256_of
        rel = self.release(info.get("release") or "packs")
        item = next((a for a in self.assets(rel) if a["name"] == info["name"]), None) if rel else None
        if not item:
            raise GitHubError(f"{info['name']} is not in the release {info.get('release')}")
        path = self.download(item, os.path.join(folder, info["name"]))
        if info.get("sha256") and sha256_of(path) != info["sha256"]:
            os.remove(path)
            raise GitHubError(f"{info['name']}: its SHA-256 is not the one in packs.json")
        return path
