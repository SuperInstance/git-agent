#!/usr/bin/env python3
"""PLATO Scout — GitHub repo analyzer that submits knowledge tiles to PLATO.

Modes:
    scout <owner/repo>      Analyze a single repo.
    scout-org <org>         Discover and analyze top repos in an org.
    daemon                  Continuously scout repos based on fleet activity.
    stats                   Show scouting statistics.

Requirements: Python 3.8+ (stdlib only).
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"
DEEPINFRA_API_KEY = "RhZPtvuy4cXzu02LbBSffbXeqs5Yf2IZ"
DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"
DEEPINFRA_MODEL = "ByteDance/Seed-2.0-mini"
PLATO_SUBMIT_URL = "http://localhost:8847/submit"
STATE_FILE = "/tmp/plato-scout-state.json"

SCOUT_SYSTEM_PROMPT = (
    "You are PLATO Scout, a knowledge extraction agent. "
    "Analyze the provided GitHub repo data and generate 3-5 knowledge tiles in JSON array format. "
    "Each tile should capture a key insight about the repo's architecture, purpose, patterns, or domain knowledge. "
    "Tiles must have: domain (kebab-case room name), question, answer, confidence (0-1), source (owner/repo), agent (plato-scout). "
    "Output ONLY a JSON array, no markdown fences."
)

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "scouted_repos": {},
        "tiles_submitted": 0,
        "tiles_accepted": 0,
        "tiles_rejected": 0,
        "github_calls": 0,
        "deepinfra_calls": 0,
        "errors": [],
    }


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError as exc:
        log_error(f"Failed to write state file: {exc}")


def log_error(msg: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    entry = f"[{ts}] {msg}"
    print(entry, file=sys.stderr)
    state = load_state()
    state["errors"].append(entry)
    # Keep last 200 errors
    state["errors"] = state["errors"][-200:]
    save_state(state)

# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def _request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[bytes] = None,
    timeout: int = 60,
) -> tuple:
    """Return (status_code, body_bytes). Raises urllib.error.HTTPError on failure."""
    req = urllib.request.Request(url, method=method, data=data)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def api_request(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[bytes] = None,
    retries: int = 1,
) -> tuple:
    """Make an HTTP request with retry logic. Returns (status, body_bytes) or (None, None) on failure."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            s, b = _request(url, method=method, headers=headers, data=data)
            return s, b
        except urllib.error.HTTPError as exc:
            last_exc = exc
            body_text = exc.read() if hasattr(exc, 'read') else b''
            log_error(f"HTTP {exc.code} from {url[:80]}: {body_text[:200]}")
            if exc.code == 404:
                return 404, b"{}"
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return exc.code, body_text
        except Exception as exc:
            last_exc = exc
            log_error(f"Request exception for {url[:80]}: {exc}")
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    return None, None


def github_headers() -> Dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "plato-scout/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github_get(path: str, params: Optional[str] = None) -> Optional[dict]:
    url = f"{GITHUB_API}{path}"
    if params:
        url = f"{url}?{params}"
    status, body = api_request(url, headers=github_headers())
    state = load_state()
    state["github_calls"] = state.get("github_calls", 0) + 1
    save_state(state)
    if status is None:
        return None
    if status == 404:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        log_error(f"GitHub JSON decode error for {url}: {exc}")
        return None

# ---------------------------------------------------------------------------
# GitHub data fetchers
# ---------------------------------------------------------------------------

def fetch_repo_metadata(owner: str, repo: str) -> Optional[dict]:
    return github_get(f"/repos/{owner}/{repo}")


def fetch_readme(owner: str, repo: str) -> str:
    data = github_get(f"/repos/{owner}/{repo}/readme")
    if not data:
        return ""
    content = data.get("content", "")
    # GitHub returns base64-encoded content
    import base64
    try:
        return base64.b64decode(content).decode("utf-8", errors="replace")[:8000]
    except Exception:
        return content[:8000]


def fetch_directory_listing(owner: str, repo: str, path: str = "", depth: int = 0) -> List[str]:
    if depth > 2:
        return []
    data = github_get(f"/repos/{owner}/{repo}/contents/{path}")
    if not data or not isinstance(data, list):
        return []
    entries = []
    for item in data:
        item_type = item.get("type", "")
        item_path = item.get("path", "")
        if item_type == "dir":
            entries.append(item_path + "/")
            if depth < 2:
                entries.extend(fetch_directory_listing(owner, repo, item_path, depth + 1))
        else:
            entries.append(item_path)
    return entries[:500]


def fetch_commits(owner: str, repo: str) -> List[dict]:
    data = github_get(f"/repos/{owner}/{repo}/commits", params="per_page=10")
    if not data or not isinstance(data, list):
        return []
    commits = []
    for c in data:
        commit = c.get("commit", {})
        commits.append({
            "sha": c.get("sha", "")[:12],
            "message": commit.get("message", "").split("\n")[0],
            "author": commit.get("author", {}).get("name", ""),
            "date": commit.get("author", {}).get("date", ""),
        })
    return commits


def fetch_issues(owner: str, repo: str) -> List[dict]:
    data = github_get(f"/repos/{owner}/{repo}/issues", params="state=open&per_page=10")
    if not data or not isinstance(data, list):
        return []
    issues = []
    for i in data:
        # Filter out pull requests (GitHub returns PRs in issues endpoint)
        if "pull_request" in i:
            continue
        issues.append({
            "number": i.get("number"),
            "title": i.get("title", ""),
            "state": i.get("state", ""),
            "created_at": i.get("created_at", ""),
            "labels": [l.get("name", "") for l in i.get("labels", [])],
        })
    return issues

# ---------------------------------------------------------------------------
# LLM / DeepInfra
# ---------------------------------------------------------------------------

def call_deepinfra(context: str) -> Optional[List[dict]]:
    url = f"{DEEPINFRA_BASE}/chat/completions"
    payload = {
        "model": DEEPINFRA_MODEL,
        "messages": [
            {"role": "system", "content": SCOUT_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPINFRA_API_KEY}",
        "User-Agent": "plato-scout/1.0",
    }
    status, body = api_request(url, method="POST", headers=headers, data=json.dumps(payload).encode("utf-8"))
    if status != 200:
        log_error(f"DeepInfra returned {status} for {url}")
    state = load_state()
    state["deepinfra_calls"] = state.get("deepinfra_calls", 0) + 1
    save_state(state)
    if status is None:
        return None
    try:
        resp = json.loads(body.decode("utf-8"))
        content = resp["choices"][0]["message"]["content"]
        # Strip markdown fences if present
        content = re.sub(r"^```json\s*", "", content.strip())
        content = re.sub(r"```\s*$", "", content.strip())
        tiles = json.loads(content.strip())
        if isinstance(tiles, dict):
            # Sometimes models wrap in an object
            for k in ("tiles", "results", "data", "knowledge_tiles"):
                if k in tiles:
                    tiles = tiles[k]
                    break
            else:
                tiles = [tiles]
        if not isinstance(tiles, list):
            log_error(f"DeepInfra returned non-list JSON: {type(tiles)}")
            return None
        return tiles
    except (KeyError, json.JSONDecodeError, IndexError) as exc:
        log_error(f"DeepInfra response parse error: {exc}")
        log_error(f"Response: {body[:200] if body else 'empty'}")
        return None

# ---------------------------------------------------------------------------
# PLATO submission
# ---------------------------------------------------------------------------

def submit_tile(tile: dict) -> bool:
    try:
        headers = {"Content-Type": "application/json"}
        data = json.dumps(tile).encode("utf-8")
        status, _ = api_request(PLATO_SUBMIT_URL, method="POST", headers=headers, data=data, retries=0)
        return status is not None and 200 <= status < 300
    except Exception as exc:
        log_error(f"PLATO submission failed: {exc}")
        return False

# ---------------------------------------------------------------------------
# Scouting logic
# ---------------------------------------------------------------------------

def build_context(owner: str, repo: str, metadata: dict, readme: str, dirs: List[str], commits: List[dict], issues: List[dict]) -> str:
    context = f"""GitHub Repository: {owner}/{repo}

Metadata:
- Description: {metadata.get("description", "N/A")}
- Language: {metadata.get("language", "N/A")}
- Topics: {", ".join(metadata.get("topics", []))}
- Stars: {metadata.get("stargazers_count", 0)}
- Forks: {metadata.get("forks_count", 0)}
- Open Issues: {metadata.get("open_issues_count", 0)}
- Default Branch: {metadata.get("default_branch", "main")}
- Created: {metadata.get("created_at", "N/A")}
- Updated: {metadata.get("updated_at", "N/A")}

README (first 2000 chars):
{readme[:2000]}

Directory Structure (sample):
{chr(10).join(dirs[:50])}

Recent Commits (last 5):
"""
    for c in commits[:5]:
        context += f"- [{c['sha']}] {c['message']} by {c['author']} ({c['date']})\n"
    context += "\nOpen Issues (last 5):\n"
    for i in issues[:5]:
        context += f"- #{i['number']} {i['title']} [{', '.join(i['labels'])}]\n"
    return context


def normalize_tile(tile: dict, owner: str, repo: str) -> Optional[dict]:
    if not isinstance(tile, dict):
        return None
    domain = tile.get("domain", "")
    question = tile.get("question", "")
    answer = tile.get("answer", "")
    if not domain or not question or not answer:
        return None
    # Normalize domain to kebab-case
    domain = re.sub(r"[^a-zA-Z0-9\-_]", "-", domain).lower().strip("-")
    if not domain:
        domain = "general"
    return {
        "domain": domain,
        "question": str(question).strip(),
        "answer": str(answer).strip(),
        "confidence": max(0.0, min(1.0, float(tile.get("confidence", 0.5)))),
        "source": f"{owner}/{repo}",
        "agent": "plato-scout",
    }


def scout_repo(owner: str, repo: str) -> dict:
    start = time.time()
    state = load_state()
    repo_key = f"{owner}/{repo}"
    print(f"\n🔍 Scouting {repo_key} ...")

    metadata = fetch_repo_metadata(owner, repo)
    if metadata is None:
        print(f"   ⚠️  Skipping {repo_key} (not found or error)")
        return {"repo": repo_key, "tiles_generated": 0, "tiles_accepted": 0, "time": 0.0}

    readme = fetch_readme(owner, repo)
    dirs = fetch_directory_listing(owner, repo)
    commits = fetch_commits(owner, repo)
    issues = fetch_issues(owner, repo)

    context = build_context(owner, repo, metadata, readme, dirs, commits, issues)
    tiles = call_deepinfra(context)

    accepted = 0
    if tiles:
        for raw_tile in tiles:
            tile = normalize_tile(raw_tile, owner, repo)
            if not tile:
                continue
            state["tiles_submitted"] = state.get("tiles_submitted", 0) + 1
            if submit_tile(tile):
                accepted += 1
                state["tiles_accepted"] = state.get("tiles_accepted", 0) + 1
            else:
                state["tiles_rejected"] = state.get("tiles_rejected", 0) + 1

    elapsed = time.time() - start
    state["scouted_repos"][repo_key] = {
        "last_scouted": datetime.now(timezone.utc).isoformat(),
        "tiles_generated": len(tiles) if tiles else 0,
        "tiles_accepted": accepted,
    }
    save_state(state)

    print(f"   ✅ {repo_key} — tiles: {len(tiles) if tiles else 0}, accepted: {accepted}, time: {elapsed:.1f}s")
    return {"repo": repo_key, "tiles_generated": len(tiles) if tiles else 0, "tiles_accepted": accepted, "time": elapsed}

# ---------------------------------------------------------------------------
# Org discovery
# ---------------------------------------------------------------------------

def discover_org_repos(org: str, limit: int = 10) -> List[str]:
    print(f"\n🔎 Discovering repos for: {org} ...")
    # Try org first, then user
    data = github_get(f"/orgs/{org}/repos", params=f"sort=pushed&direction=desc&per_page={limit}")
    if not data or not isinstance(data, list):
        data = github_get(f"/users/{org}/repos", params=f"sort=pushed&direction=desc&per_page={limit}")
    if not data or not isinstance(data, list):
        log_error(f"Could not list repos for org {org}")
        return []
    repos = []
    for r in data:
        name = r.get("name")
        if name:
            repos.append(name)
    return repos[:limit]

# ---------------------------------------------------------------------------
# Daemon mode helpers
# ---------------------------------------------------------------------------

def get_recently_pushed_repos() -> List[str]:
    """Search GitHub for repos with pushes in the last hour.
    Uses the search API with 'pushed:>YYYY-MM-DDTHH:MM:SSZ' qualifier."""
    one_hour_ago = (datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)).isoformat()
    query = f"pushed:>{one_hour_ago}"
    # GitHub search API has a max per_page of 100
    data = github_get("/search/repositories", params=f"q={urllib.parse.quote(query)}&sort=updated&order=desc&per_page=50")
    if not data or not isinstance(data, dict):
        return []
    items = data.get("items", [])
    repos = []
    for item in items:
        full_name = item.get("full_name")
        if full_name:
            repos.append(full_name)
    return repos


def should_scout(repo_key: str, min_interval_hours: int = 24) -> bool:
    state = load_state()
    record = state.get("scouted_repos", {}).get(repo_key)
    if not record:
        return True
    last = record.get("last_scouted")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - last_dt
        return delta.total_seconds() > min_interval_hours * 3600
    except Exception:
        return True

# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_scout(args: argparse.Namespace) -> int:
    repo_spec = args.repo
    if "/" not in repo_spec:
        print("Error: repo must be in owner/repo format", file=sys.stderr)
        return 1
    owner, repo = repo_spec.split("/", 1)
    scout_repo(owner, repo)
    return 0


def cmd_scout_org(args: argparse.Namespace) -> int:
    org = args.org
    limit = args.limit
    repos = discover_org_repos(org, limit)
    if not repos:
        print(f"No repos found for org {org}")
        return 1
    for repo in repos:
        scout_repo(org, repo)
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    interval = args.interval
    print(f"🤖 Daemon started. Interval: {interval}s. Press Ctrl+C to stop.")
    while True:
        try:
            repos = get_recently_pushed_repos()
            if repos:
                print(f"   Found {len(repos)} recently pushed repos.")
                for repo_key in repos:
                    if should_scout(repo_key):
                        if "/" not in repo_key:
                            continue
                        owner, repo = repo_key.split("/", 1)
                        scout_repo(owner, repo)
                    else:
                        print(f"   ⏭️  Skipping {repo_key} (scouted recently)")
            else:
                print(f"   No recently pushed repos found.")
            print(f"   😴 Sleeping {interval}s ...")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n👋 Daemon stopped.")
            break
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    state = load_state()
    print("\n📊 PLATO Scout Statistics")
    print("-" * 40)
    print(f"Repos scouted      : {len(state.get('scouted_repos', {}))}")
    print(f"Tiles submitted    : {state.get('tiles_submitted', 0)}")
    print(f"Tiles accepted     : {state.get('tiles_accepted', 0)}")
    print(f"Tiles rejected     : {state.get('tiles_rejected', 0)}")
    print(f"GitHub API calls   : {state.get('github_calls', 0)}")
    print(f"DeepInfra API calls: {state.get('deepinfra_calls', 0)}")
    print(f"Errors logged      : {len(state.get('errors', []))}")
    print("-" * 40)
    return 0

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="PLATO Scout — GitHub repo analyzer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_scout = subparsers.add_parser("scout", help="Analyze a single repo")
    p_scout.add_argument("repo", help="Owner/repo (e.g., SuperInstance/oracle1-workspace)")

    p_org = subparsers.add_parser("scout-org", help="Discover and analyze repos in an org")
    p_org.add_argument("org", help="GitHub organization name")
    p_org.add_argument("--limit", type=int, default=10, help="Max repos to scout (default: 10)")

    p_daemon = subparsers.add_parser("daemon", help="Continuously scout new repos")
    p_daemon.add_argument("--interval", type=int, default=300, help="Sleep seconds between checks (default: 300)")

    p_stats = subparsers.add_parser("stats", help="Show scouting statistics")

    args = parser.parse_args()

    if args.command == "scout":
        return cmd_scout(args)
    elif args.command == "scout-org":
        return cmd_scout_org(args)
    elif args.command == "daemon":
        return cmd_daemon(args)
    elif args.command == "stats":
        return cmd_stats(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
