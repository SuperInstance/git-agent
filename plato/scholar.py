#!/usr/bin/env python3
"""
PLATO Scholar — Deep code analysis agent that extracts patterns from source files.

The Scholar reads actual source code (not just metadata) and generates higher-quality
tiles about architecture patterns, design decisions, algorithms, and domain knowledge.

Usage:
  python3 plato_scholar.py analyze SuperInstance/plato-kernel
  python3 plato_scholar.py analyze SuperInstance/plato-kernel --file src/kernel.py
  python3 plato_scholar.py batch SuperInstance --limit 5
"""

import json, urllib.request, sys, os, time, re, base64, argparse
from typing import List, Optional, Dict

# Config
DEEPINFRA_API_KEY = os.environ.get("DEEPINFRA_API_KEY", "RhZPtvuy4cXzu02LbBSffbXeqs5Yf2IZ")
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"
PLATO_URL = "http://localhost:8847/submit"
STATE_FILE = "/tmp/plato-scholar-state.json"

SCHOLAR_SYSTEM = """You are PLATO Scholar, a deep code analysis agent. Analyze the provided source code and generate 3-5 knowledge tiles about:

1. Architecture patterns (how components fit together)
2. Design decisions (why things are done a certain way)
3. Algorithms and data structures used
4. Domain knowledge embedded in the code
5. Potential improvements or gotchas

Output ONLY a JSON array of tiles:
[{"domain": "kebab-case-room-name", "question": "...", "answer": "...", "confidence": 0.0-1.0}]

No markdown fences. Pure JSON array."""

def api_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()

def github_get(path, token=None):
    token = token or os.environ.get("GITHUB_TOKEN", "")
    url = f"https://api.github.com{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "plato-scholar/1.0",
    }
    if token:
        headers["Authorization"] = f"token {token}"
    try:
        status, body = api_get(url, headers)
        return json.loads(body.decode())
    except Exception as e:
        print(f"  GitHub error: {e}")
        return None

def github_get_file(owner, repo, path, token=None):
    """Get file content from GitHub."""
    data = github_get(f"/repos/{owner}/{repo}/contents/{path}", token)
    if data and isinstance(data, dict) and "content" in data:
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return None

def github_get_tree(owner, repo, token=None):
    """Get the file tree of a repo."""
    data = github_get(f"/repos/{owner}/{repo}/git/trees/main?recursive=1", token)
    if not data:
        data = github_get(f"/repos/{owner}/{repo}/git/trees/master?recursive=1", token)
    if data and "tree" in data:
        return [item["path"] for item in data["tree"] if item["type"] == "blob"]
    return []

def is_code_file(path):
    """Check if a file is worth analyzing."""
    exts = {".py", ".rs", ".go", ".js", ".ts", ".toml", ".yaml", ".yml", ".md"}
    return any(path.endswith(e) for e in exts)

def select_analysis_files(files, max_files=5):
    """Select the most important files to analyze."""
    priority_keywords = ["main", "core", "kernel", "engine", "server", "handler",
                         "lib", "mod", "config", "protocol", "agent"]
    scored = []
    for f in files:
        if not is_code_file(f):
            continue
        score = 0
        name = os.path.basename(f).lower()
        for kw in priority_keywords:
            if kw in name:
                score += 10
        # Prefer root-level and src-level files
        depth = f.count("/")
        score -= depth
        # Skip test files (lower priority)
        if "test" in name or "spec" in name:
            score -= 5
        scored.append((score, f))
    scored.sort(reverse=True)
    return [f for _, f in scored[:max_files]]

def call_deepinfra(context, token=None):
    """Call Seed-2.0-mini for analysis."""
    payload = json.dumps({
        "model": "ByteDance/Seed-2.0-mini",
        "messages": [
            {"role": "system", "content": SCHOLAR_SYSTEM},
            {"role": "user", "content": context}
        ],
        "temperature": 0.3,
        "max_tokens": 2000
    }).encode()

    req = urllib.request.Request(DEEPINFRA_URL, method="POST", data=payload)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {DEEPINFRA_API_KEY}")
    req.add_header("User-Agent", "plato-scholar/1.0")

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode())
            content = body["choices"][0]["message"]["content"]
            content = re.sub(r"^```json\s*", "", content.strip())
            content = re.sub(r"```\s*$", "", content.strip())
            tiles = json.loads(content)
            if isinstance(tiles, dict):
                for k in ("tiles", "results", "data"):
                    if k in tiles:
                        tiles = tiles[k]
                        break
                else:
                    tiles = [tiles]
            return tiles if isinstance(tiles, list) else None
    except Exception as e:
        print(f"  DeepInfra error: {e}")
        return None

def submit_tile(tile, owner, repo):
    """Submit a tile to PLATO."""
    tile["source"] = f"{owner}/{repo}"
    tile["agent"] = "plato-scholar"
    if "domain" not in tile or "question" not in tile or "answer" not in tile:
        return False
    tile["domain"] = re.sub(r"[^a-zA-Z0-9\-_]", "-", tile["domain"]).lower().strip("-")
    tile["confidence"] = max(0.0, min(1.0, float(tile.get("confidence", 0.5))))
    data = json.dumps(tile).encode()
    req = urllib.request.Request(PLATO_URL, method="POST", data=data)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("status") in ("accepted", "ok")
    except Exception as e:
        print(f"  PLATO submit error: {e}")
        return False

def analyze_repo(owner, repo, max_files=5):
    """Deep-analyze a repo's source code."""
    start = time.time()
    token = os.environ.get("GITHUB_TOKEN", "")
    print(f"\n🎓 Scholar analyzing {owner}/{repo} ...")

    # Get file tree
    files = github_get_tree(owner, repo, token)
    if not files:
        print(f"  ⚠️ No files found")
        return {"repo": f"{owner}/{repo}", "files_analyzed": 0, "tiles": 0, "accepted": 0}

    # Select important files
    selected = select_analysis_files(files, max_files)
    print(f"  Selected {len(selected)} files for analysis")

    all_tiles = []
    accepted = 0

    for filepath in selected:
        content = github_get_file(owner, repo, filepath, token)
        if not content or len(content) < 50:
            continue

        # Truncate large files
        if len(content) > 3000:
            content = content[:3000] + "\n... (truncated)"

        context = f"""Repository: {owner}/{repo}
File: {filepath}

```{filepath.split('.')[-1]}
{content}
```

Analyze this code and extract knowledge tiles."""

        tiles = call_deepinfra(context, token)
        if tiles:
            for tile in tiles:
                if submit_tile(tile, owner, repo):
                    accepted += 1
                all_tiles.append(tile)
            print(f"  📄 {filepath}: {len(tiles)} tiles")
        else:
            print(f"  📄 {filepath}: no tiles generated")

        time.sleep(1)  # Rate limit

    elapsed = time.time() - start
    print(f"  ✅ {owner}/{repo} — files: {len(selected)}, tiles: {len(all_tiles)}, accepted: {accepted}, time: {elapsed:.1f}s")

    return {
        "repo": f"{owner}/{repo}",
        "files_analyzed": len(selected),
        "tiles": len(all_tiles),
        "accepted": accepted,
        "time": round(elapsed, 1)
    }

def main():
    parser = argparse.ArgumentParser(description="PLATO Scholar — Deep code analysis")
    sub = parser.add_subparsers(dest="command")

    analyze_p = sub.add_parser("analyze", help="Deep-analyze a repo")
    analyze_p.add_argument("repo", help="owner/repo")
    analyze_p.add_argument("--file", help="Specific file to analyze")
    analyze_p.add_argument("--max-files", type=int, default=5, help="Max files to analyze")

    batch_p = sub.add_parser("batch", help="Analyze top repos")
    batch_p.add_argument("owner", help="GitHub user or org")
    batch_p.add_argument("--limit", type=int, default=5, help="Max repos")

    args = parser.parse_args()

    if args.command == "analyze":
        owner, repo = args.repo.split("/")
        if args.file:
            # Analyze single file
            content = github_get_file(owner, repo, args.file)
            if content:
                ctx = f"Repository: {owner}/{repo}\nFile: {args.file}\n\n```\n{content[:3000]}\n```\n\nAnalyze this code."
                tiles = call_deepinfra(ctx)
                if tiles:
                    for t in tiles:
                        submit_tile(t, owner, repo)
                    print(f"Generated {len(tiles)} tiles from {args.file}")
                else:
                    print("No tiles generated")
            else:
                print(f"Could not fetch {args.file}")
        else:
            result = analyze_repo(owner, repo, args.max_files)
            print(json.dumps(result, indent=2))

    elif args.command == "batch":
        token = os.environ.get("GITHUB_TOKEN", "")
        data = github_get(f"/users/{args.owner}/repos?sort=pushed&per_page={args.limit}", token)
        if not data:
            data = github_get(f"/orgs/{args.owner}/repos?sort=pushed&per_page={args.limit}", token)
        if data and isinstance(data, list):
            results = []
            for r in data:
                result = analyze_repo(r["owner"]["login"], r["name"], 3)
                results.append(result)
            print(f"\n📊 Batch complete: {len(results)} repos")
            total_tiles = sum(r["tiles"] for r in results)
            total_accepted = sum(r["accepted"] for r in results)
            print(f"Total tiles: {total_tiles}, accepted: {total_accepted}")
        else:
            print(f"No repos found for {args.owner}")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
