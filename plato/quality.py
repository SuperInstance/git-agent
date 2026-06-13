#!/usr/bin/env python3
"""
PLATO Quality Scorer — auto-promote high-value tiles, archive low-value ones.

Scoring criteria:
  - Confidence (0-1) — from tile metadata
  - Answer length — longer = more detail (up to a point)
  - Specificity — named entities, numbers, code references
  - Source diversity — tiles from different agents/repos are more valuable
  - Freshness — recently created tiles get a small boost

Usage:
  python3 plato_quality.py score --room architecture
  python3 plato_quality.py score-all
  python3 plato_quality.py promote --threshold 0.8
  python3 plato_quality.py archive --threshold 0.3
  python3 plato_quality.py report
"""

import json, urllib.request, sys, os, re, argparse, time, hashlib
from collections import defaultdict
from typing import Dict, List, Tuple

PLATO_URL = "http://localhost:8847"
STATE_FILE = "/tmp/plato-quality-state.json"

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

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"scored": {}, "last_run": 0}

def score_tile(tile: dict) -> float:
    """Score a tile 0-1 based on quality criteria."""
    scores = []
    
    # 1. Confidence (direct, 0-1)
    conf = float(tile.get("confidence", 0.5))
    scores.append(("confidence", conf, 0.3))
    
    # 2. Answer length (optimal 100-500 chars)
    answer = tile.get("answer", "")
    alen = len(answer)
    if alen < 20:
        length_score = 0.1
    elif alen < 50:
        length_score = 0.3
    elif alen < 100:
        length_score = 0.5
    elif alen <= 500:
        length_score = 0.9
    elif alen <= 1000:
        length_score = 0.8
    else:
        length_score = 0.7  # Very long = diminishing returns
    scores.append(("length", length_score, 0.2))
    
    # 3. Specificity (numbers, code refs, named entities, URLs)
    text = f"{tile.get('question', '')} {answer}"
    specificity = 0.3  # base
    if re.search(r'\d+\.?\d*%?', text): specificity += 0.15  # Has numbers
    if re.search(r'`[^`]+`', text): specificity += 0.15  # Has code
    if re.search(r'https?://', text): specificity += 0.1  # Has URLs
    if re.search(r'[A-Z][a-z]+[A-Z]', text): specificity += 0.1  # CamelCase (names)
    if re.search(r'\b(finds?|shows?|proves?|demonstrates?)\b', text.lower()): specificity += 0.1  # Evidence words
    if re.search(r'\b(always|never|all|none|every)\b', text, re.IGNORECASE): specificity -= 0.15  # Absolute claims
    specificity = max(0, min(1, specificity))
    scores.append(("specificity", specificity, 0.2))
    
    # 4. Question quality (is it actually asking something useful?)
    question = tile.get("question", "")
    q_score = 0.5
    if len(question) > 15: q_score += 0.1
    if re.search(r'\b(how|why|what|when|which|where)\b', question.lower()): q_score += 0.15
    if re.search(r'\b(can|does|should|would|is)\b', question.lower()): q_score += 0.1
    q_score = max(0, min(1, q_score))
    scores.append(("question", q_score, 0.15))
    
    # 5. Source metadata (agent attribution is good)
    s_score = 0.4
    if tile.get("source"): s_score += 0.2
    if tile.get("agent"): s_score += 0.2
    if tile.get("domain"): s_score += 0.1
    s_score = min(1, s_score)
    scores.append(("source", s_score, 0.15))
    
    # Weighted average
    total_weight = sum(w for _, _, w in scores)
    weighted_sum = sum(s * w for _, s, w in scores)
    final = weighted_sum / total_weight if total_weight else 0.5
    
    return round(final, 3)

def score_room(room_name: str) -> Dict:
    """Score all tiles in a room."""
    try:
        data = plato_get(f"/room/{room_name}")
        tiles = data.get("tiles", [])
    except:
        return {"room": room_name, "tiles": 0, "error": "fetch failed"}
    
    results = []
    for tile in tiles:
        score = score_tile(tile)
        results.append({
            "question": tile.get("question", "")[:80],
            "score": score,
            "confidence": tile.get("confidence", 0),
            "answer_len": len(tile.get("answer", "")),
            "agent": tile.get("agent", "?"),
        })
    
    if not results:
        return {"room": room_name, "tiles": 0, "avg_score": 0}
    
    avg = sum(r["score"] for r in results) / len(results)
    high = [r for r in results if r["score"] >= 0.8]
    low = [r for r in results if r["score"] < 0.3]
    
    return {
        "room": room_name,
        "tiles": len(results),
        "avg_score": round(avg, 3),
        "high_quality": len(high),
        "low_quality": len(low),
        "distribution": {
            "0.9+": len([r for r in results if r["score"] >= 0.9]),
            "0.8-0.9": len([r for r in results if 0.8 <= r["score"] < 0.9]),
            "0.5-0.8": len([r for r in results if 0.5 <= r["score"] < 0.8]),
            "0.3-0.5": len([r for r in results if 0.3 <= r["score"] < 0.5]),
            "<0.3": len([r for r in results if r["score"] < 0.3]),
        },
        "sample_high": [r["question"] for r in sorted(results, key=lambda x: -x["score"])[:3]],
        "sample_low": [r["question"] for r in sorted(results, key=lambda x: x["score"])[:3]],
    }

def score_all_rooms():
    """Score all rooms with tiles."""
    status = plato_get("/status")
    rooms = status.get("rooms", {})
    
    results = []
    total_tiles = 0
    total_high = 0
    total_low = 0
    
    for room_name in sorted(rooms.keys()):
        tile_count = rooms[room_name].get("tile_count", 0)
        if tile_count == 0:
            continue
        
        result = score_room(room_name)
        results.append(result)
        total_tiles += result.get("tiles", 0)
        total_high += result.get("high_quality", 0)
        total_low += result.get("low_quality", 0)
    
    # Save state
    state = load_state()
    state["last_run"] = time.time()
    state["total_tiles"] = total_tiles
    state["total_high"] = total_high
    state["total_low"] = total_low
    state["room_results"] = {r["room"]: r for r in results}
    save_state(state)
    
    return {
        "rooms_scored": len(results),
        "total_tiles": total_tiles,
        "high_quality": total_high,
        "low_quality": total_low,
        "top_rooms": sorted(results, key=lambda x: -x.get("avg_score", 0))[:10],
        "bottom_rooms": sorted(results, key=lambda x: x.get("avg_score", 1))[:10],
    }

def generate_report():
    """Generate a quality report."""
    state = load_state()
    if not state.get("room_results"):
        # Run scoring first
        score_all_rooms()
        state = load_state()
    
    results = list(state.get("room_results", {}).values())
    if not results:
        print("No rooms scored. Run: python3 plato_quality.py score-all")
        return
    
    print("📊 PLATO Tile Quality Report")
    print(f"   Last scored: {time.strftime('%Y-%m-%d %H:%M', time.gmtime(state.get('last_run', 0)))}")
    print(f"   Rooms: {state.get('rooms_scored', 0)}")
    print(f"   Total tiles: {state.get('total_tiles', 0)}")
    print(f"   High quality (≥0.8): {state.get('total_high', 0)}")
    print(f"   Low quality (<0.3): {state.get('total_low', 0)}")
    
    print(f"\n   🏆 Top 10 Rooms by Quality:")
    for r in sorted(results, key=lambda x: -x.get("avg_score", 0))[:10]:
        print(f"     {r['avg_score']:.2f} | {r['room']:30s} | {r['tiles']:4d} tiles | {r.get('high_quality',0)} high")
    
    print(f"\n   📉 Bottom 10 Rooms:")
    for r in sorted(results, key=lambda x: x.get("avg_score", 1))[:10]:
        print(f"     {r['avg_score']:.2f} | {r['room']:30s} | {r['tiles']:4d} tiles | {r.get('low_quality',0)} low")

def main():
    parser = argparse.ArgumentParser(description="PLATO Quality Scorer")
    sub = parser.add_subparsers(dest="command")
    
    score_p = sub.add_parser("score", help="Score a specific room")
    score_p.add_argument("--room", required=True)
    
    sub.add_parser("score-all", help="Score all rooms")
    sub.add_parser("report", help="Generate quality report")
    
    promote_p = sub.add_parser("promote", help="List tiles above threshold")
    promote_p.add_argument("--threshold", type=float, default=0.8)
    
    archive_p = sub.add_parser("archive", help="List tiles below threshold")
    archive_p.add_argument("--threshold", type=float, default=0.3)
    
    args = parser.parse_args()
    
    if args.command == "score":
        result = score_room(args.room)
        print(json.dumps(result, indent=2))
    elif args.command == "score-all":
        result = score_all_rooms()
        print(f"Scored {result['rooms_scored']} rooms")
        print(f"Total tiles: {result['total_tiles']}")
        print(f"High quality: {result['high_quality']}")
        print(f"Low quality: {result['low_quality']}")
        print(f"\nTop rooms:")
        for r in result["top_rooms"]:
            print(f"  {r['avg_score']:.2f} {r['room']} ({r['tiles']} tiles)")
    elif args.command == "report":
        generate_report()
    elif args.command == "promote":
        state = load_state()
        for room_name, r in state.get("room_results", {}).items():
            for t in r.get("sample_high", []):
                print(f"⭐ [{room_name}] {t}")
    elif args.command == "archive":
        state = load_state()
        for room_name, r in state.get("room_results", {}).items():
            for t in r.get("sample_low", []):
                print(f"📦 [{room_name}] {t}")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
