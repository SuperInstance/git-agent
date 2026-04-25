#!/usr/bin/env python3
"""
PLATO Librarian — Tile quality control, deduplication, and cross-referencing.

Scans PLATO rooms for:
1. Duplicate tiles (same question/answer)
2. Low-quality tiles (short answers, low confidence)
3. Cross-references between rooms
4. Room statistics and health metrics

Usage:
  python3 plato_librarian.py audit
  python3 plato_librarian.py audit --room gpu-optimization
  python3 plato_librarian.py dedup --room architecture
  python3 plato_librarian.py stats
  python3 plato_librarian.py cross-reference
"""

import json, urllib.request, sys, os, re, argparse, hashlib
from collections import defaultdict
from typing import Dict, List

PLATO_URL = "http://localhost:8847"

def plato_get(path):
    req = urllib.request.Request(f"{PLATO_URL}{path}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def plato_post(path, data):
    req = urllib.request.Request(f"{PLATO_URL}{path}", method="POST",
                                  data=json.dumps(data).encode(),
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

def get_all_rooms():
    data = plato_get("/status")
    return list(data.get("rooms", {}).keys())

def get_room_tiles(room):
    try:
        data = plato_get(f"/room/{room}")
        return data.get("tiles", [])
    except:
        return []

def tile_hash(tile):
    """Generate a hash for dedup based on question + answer."""
    q = tile.get("question", "").strip().lower()
    a = tile.get("answer", "").strip().lower()[:200]
    return hashlib.md5(f"{q}::{a}".encode()).hexdigest()

def audit_room(room):
    """Audit a single room for quality."""
    tiles = get_room_tiles(room)
    if not tiles:
        return {"room": room, "tiles": 0, "issues": []}

    issues = []
    hashes = {}
    
    for tile in tiles:
        h = tile_hash(tile)
        
        # Check for duplicates
        if h in hashes:
            issues.append({
                "type": "duplicate",
                "tile": tile.get("question", "")[:60],
                "duplicate_of": hashes[h][:60]
            })
        hashes[h] = tile.get("question", "")
        
        # Check quality
        answer = tile.get("answer", "")
        if len(answer) < 20:
            issues.append({
                "type": "short_answer",
                "tile": tile.get("question", "")[:60],
                "answer_length": len(answer)
            })
        
        conf = tile.get("confidence", 0)
        if conf < 0.3:
            issues.append({
                "type": "low_confidence",
                "tile": tile.get("question", "")[:60],
                "confidence": conf
            })
        
        # Check for absolute claims (deadband protocol)
        text = f"{tile.get('question', '')} {answer}"
        absolutes = re.findall(r'\b(always|never|all|none|every|no one|impossible)\b', text, re.IGNORECASE)
        if absolutes:
            issues.append({
                "type": "absolute_claim",
                "tile": tile.get("question", "")[:60],
                "words": absolutes[:3]
            })
    
    return {
        "room": room,
        "tiles": len(tiles),
        "issues": len(issues),
        "issue_types": defaultdict(int, {i["type"]: sum(1 for j in issues if j["type"] == i["type"]) for i in issues}),
        "details": issues[:10]
    }

def dedup_room(room):
    """Find and report duplicates in a room."""
    tiles = get_room_tiles(room)
    if not tiles:
        return {"room": room, "duplicates": 0}
    
    seen = {}
    duplicates = []
    
    for tile in tiles:
        h = tile_hash(tile)
        if h in seen:
            duplicates.append({
                "question": tile.get("question", "")[:80],
                "original": seen[h][:80]
            })
        else:
            seen[h] = tile.get("question", "")
    
    return {"room": room, "total": len(tiles), "duplicates": len(duplicates), "details": duplicates}

def cross_reference():
    """Find tiles that reference concepts across rooms."""
    rooms = get_all_rooms()
    # Only check rooms with reasonable tile counts
    room_tiles = {}
    for room in rooms:
        tiles = get_room_tiles(room)
        if tiles:
            room_tiles[room] = tiles
    
    # Find shared keywords
    keyword_rooms = defaultdict(set)
    for room, tiles in room_tiles.items():
        for tile in tiles:
            text = f"{tile.get('question', '')} {tile.get('answer', '')}"
            words = set(re.findall(r'\b[a-z]{4,}\b', text.lower()))
            for w in words - {'that', 'this', 'with', 'from', 'have', 'been', 'they', 'their', 'which', 'would', 'about', 'could', 'other', 'than'}:
                keyword_rooms[w].add(room)
    
    # Find keywords that appear in 3+ rooms
    cross_refs = []
    for keyword, rms in sorted(keyword_rooms.items(), key=lambda x: -len(x[1])):
        if len(rms) >= 3:
            cross_refs.append({
                "keyword": keyword,
                "rooms": sorted(rms),
                "room_count": len(rms)
            })
    
    return {"cross_references": cross_refs[:20], "rooms_analyzed": len(room_tiles)}

def main():
    parser = argparse.ArgumentParser(description="PLATO Librarian — Tile quality control")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("stats", help="Overall PLATO statistics")
    
    audit_p = sub.add_parser("audit", help="Audit tile quality")
    audit_p.add_argument("--room", help="Specific room to audit")

    dedup_p = sub.add_parser("dedup", help="Find duplicate tiles")
    dedup_p.add_argument("--room", help="Specific room to dedup")
    
    sub.add_parser("cross-reference", help="Find cross-room connections")

    args = parser.parse_args()

    if args.command == "stats":
        rooms = get_all_rooms()
        total_tiles = 0
        room_stats = {}
        for room in rooms:
            tiles = get_room_tiles(room)
            total_tiles += len(tiles)
            if tiles:
                room_stats[room] = len(tiles)
        
        print(f"📚 PLATO Library Statistics")
        print(f"   Rooms: {len(rooms)}")
        print(f"   Total tiles: {total_tiles}")
        print(f"   Rooms with tiles: {len(room_stats)}")
        print(f"\n   Top 10 rooms by tiles:")
        for room, count in sorted(room_stats.items(), key=lambda x: -x[1])[:10]:
            print(f"     {room}: {count}")

    elif args.command == "audit":
        if args.room:
            result = audit_room(args.room)
            print(json.dumps(result, indent=2, default=str))
        else:
            rooms = get_all_rooms()
            total_issues = 0
            for room in sorted(rooms):
                result = audit_room(room)
                if result["issues"] > 0:
                    total_issues += result["issues"]
                    print(f"  {room}: {result['tiles']} tiles, {result['issues']} issues")
                    for issue in result.get("details", [])[:3]:
                        print(f"    ⚠️  {issue['type']}: {issue.get('tile', '')[:60]}")
            print(f"\nTotal issues found: {total_issues}")

    elif args.command == "dedup":
        if args.room:
            result = dedup_room(args.room)
            print(json.dumps(result, indent=2))
        else:
            rooms = get_all_rooms()
            total_dups = 0
            for room in rooms:
                result = dedup_room(room)
                if result["duplicates"] > 0:
                    total_dups += result["duplicates"]
                    print(f"  {room}: {result['duplicates']} duplicates")
            print(f"\nTotal duplicates: {total_dups}")

    elif args.command == "cross-reference":
        result = cross_reference()
        print(f"🔗 Cross-Reference Analysis ({result['rooms_analyzed']} rooms)")
        for ref in result["cross_references"]:
            rooms_str = ", ".join(ref["rooms"][:5])
            print(f"  '{ref['keyword']}' → {ref['room_count']} rooms: {rooms_str}")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()
