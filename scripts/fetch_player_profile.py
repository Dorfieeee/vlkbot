#!/usr/bin/env python3
"""
Quick test script: receive a Steam ID and scrape HLL Records profile data asynchronously.
Usage: python hll_scrape_test.py [STEAM_ID]
Example: python hll_scrape_test.py 76561198199051397
"""
import asyncio
import re
import sys
import httpx  # pip install httpx if needed

# Optional: use BeautifulSoup for cleaner parsing (pip install beautifulsoup4)
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

BASE_URL = "https://hllrecords.com/profiles/"

async def fetch_profile_page(hll_id: str, period: str = "") -> str:
    """Fetch raw HTML for HLL Records profile asynchronously."""
    period_param = f"?period={period}" if period != "" else ""
    url = f"{BASE_URL}{hll_id}{period_param}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Raise for 4xx/5xx errors
        return response.text


# scrape_with_regex remains unchanged (sync, as it's quick parsing)
def scrape_with_regex(html: str) -> dict:
    """Grep-style extraction using regex on page text (and raw HTML fallback)."""
    numeric_keys = {"total_matches", "total_hours", "matches_played", "hours_played", "win_rate_pct",
                    "total_kills", "kpm", "total_deaths", "dpm", "kd_ratio", "longest_killstreak",
                    "team_kills", "team_kills_pct", "avg_match_pct", "avg_minutes", "comp_matches",
                    "melee_kills", "melee_kd", "melee_deaths", "melee_deaths_every_n_matches",
                    "melee_killstreak_current", "most_deaths_artillery",
                    "infantry_best", "mg_best", "sniper_best", "armor_best", "artillery_best"}

    if HAS_BS4:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
    else:
        text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)

    data = {"hll_id": None, "profile_url": None}

    # Steam ID from URL
    steam_match = re.search(r"profiles/([a-z0-9]+)", html)
    if steam_match:
        data["hll_id"] = steam_match.group(1)
        data["profile_url"] = f"{BASE_URL}{data['hll_id']}"

    # Scalar stats: allow minimal spacing (site often has "2,267(0.27KPM)")
    patterns = [
        (r"Total on servers\s*(\d+)\s*matches\s*/\s*([\d.]+)\s*hours", "total_matches", "total_hours"),
        (r"Matchesplayed\s*(\d+)\s*matches\s*/\s*([\d.]+)\s*hours", "matches_played", "hours_played"),
        (r"Matches played\s*(\d+)\s*matches\s*/\s*([\d.]+)\s*hours", "matches_played", "hours_played"),
        (r"Win rate\s*([\d.]+)\s*%", "win_rate_pct"),
        (r"Total kills\s*([\d,]+)\s*\(\s*([\d.]+)\s*KPM\)", "total_kills", "kpm"),
        (r"Total deaths\s*([\d,]+)\s*\(\s*([\d.]+)\s*DPM\)", "total_deaths", "dpm"),
        (r"Team kills\s*(\d+)\s*\(\s*([\d.]+)\s*%", "team_kills", "team_kills_pct"),
        (r"Average match time played\s*([\d.]+)\s*%\s*\(\s*([\d.]+)\s*minutes\)", "avg_match_pct", "avg_minutes"),
        (r"Overall K/D ratio\s*([\d.]+)", "kd_ratio"),
        (r"Longest killstreak\s*(\d+)\s*kills", "longest_killstreak"),
        (r"Averagematch time played\s*([\d.]+)%\s*\(([\d.]+)\s*minutes\)", "avg_match_pct", "avg_minutes"),
        (r"First seen\s*(\d+\s+\w+\s+\d{4})", "first_seen"),
        (r"Competitive HLL\s*(\d+)\s*matches", "comp_matches"),
        (r"Most deaths to artillery\s*(\d+)\s*deaths", "most_deaths_artillery"),
        (r"Melee kills\s*(\d+)\s*\(\s*([\d.]+)\s*KD\)", "melee_kills", "melee_kd"),
        (r"Melee deaths\s*(\d+)\s*\(\s*once every (\d+) matches", "melee_deaths", "melee_deaths_every_n_matches"),
        (r"Current melee killstreak\s*(\d+)\s*melee kills", "melee_killstreak_current"),
        (r"Infantry\s*(\d+)\s*on", "infantry_best"),
        (r"Machine Gun\s*(\d+)\s*on", "mg_best"),
        (r"Sniper\s*(\d+)\s*on", "sniper_best"),
        (r"Armor\s*(\d+)\s*on", "armor_best"),
        (r"Artillery\s*(\d+)\s*on", "artillery_best"),
    ]

    def try_parse(src):
        for pattern in patterns:
            match = re.search(pattern[0], src, re.IGNORECASE)
            if match:
                keys = pattern[1:]
                for i, key in enumerate(keys):
                    if i < len(match.groups()):
                        val = match.group(i + 1).replace(",", "").strip()
                        if key in numeric_keys and val.replace(".", "").replace("-", "").isdigit():
                            try:
                                data[key] = float(val)
                            except ValueError:
                                data[key] = val
                        else:
                            data[key] = int(val) if val.isdigit() else val

    try_parse(text)
    try_parse(html)

    # Player name: title or first heading
    title = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    if title:
        data["page_title"] = title.group(1).strip()

    # Profile avatar: Steam CDN URL (from _next/image url= param or direct in HTML)
    avatar_match = re.search(r"avatars\.steamstatic\.com/([a-f0-9]+_full\.jpg)", html, re.I)
    if not avatar_match:
        # URL-encoded in _next/image: url=https%3A%2F%2Favatars.steamstatic.com%2F...
        encoded = re.search(
            r"url=https%3A%2F%2Favatars\.steamstatic\.com%2F([a-f0-9]+_full\.jpg)",
            html,
            re.I,
        )
        if encoded:
            avatar_match = encoded
    if avatar_match:
        data["profile_avatar_url"] = f"https://avatars.steamstatic.com/{avatar_match.group(1)}"

    # --- List extractions (from HTML or text) ---
    # Most played servers: "1. [VLK 1](url) 25" in HTML
    servers = re.findall(r"\d+\.\s*\[([^\]]+)\][](https://hllrecords\.com/[^)]+\)\s*(\d+)", html)
    if not servers:
        # Text fallback: "VLK 1 25", "Circle 6 22" in the servers section
        servers_section = re.search(r"Most played servers\s*(.*?)(?:Most played game modes|$)", text, re.DOTALL | re.I)
        if servers_section:
            block = servers_section.group(1)
            servers = re.findall(r"(VLK\s*\d+|Circle\s*\d+)\s+(\d+)", block, re.I)
    if servers:
        data["most_played_servers"] = [(name.strip(), int(n)) for name, n in servers[:15]]

    # Most played game modes: only the dedicated section "1. Warfare 175" etc (first 3)
    modes_section = re.search(r"Most played game modes\s*(.*?)(?:Most played maps|Weapon usage|$)", text, re.DOTALL | re.I)
    if modes_section:
        modes = re.findall(r"(\d+)\.\s*(Warfare|Offensive|Skirmish)\s*(\d+)", modes_section.group(1), re.I)
        if modes:
            data["game_modes"] = [(m[1], int(m[2])) for m in modes]

    # Weapon usage: "WEAPON NAME | 21.13% 479" or "21.13% 479" on next line
    weapons = re.findall(r"([A-Z0-9\[\]\s]+(?:HOWITZER|GARAND|THOMPSON|MP40|GEWEHR|SPRINGFIELD)[^|%\d]*)\s*[\s|]*([\d.]+)%\s*(\d+)", html, re.I)
    if not weapons:
        weapons = re.findall(r"([\d.]+)%\s*(\d+)\s*\|\s*([A-Z0-9\[\]\s]+)", text)  # % count | Name
        if weapons:
            data["weapon_usage"] = [(w[2].strip(), float(w[0]), int(w[1])) for w in weapons[:10]]
    else:
        data["weapon_usage"] = [(w[0].strip(), float(w[1]), int(w[2])) for w in weapons[:10]]

    # Most played maps: section "Most played maps" then "1. Map Name 28"
    maps_section = re.search(r"Most played maps\s*(.*?)(?:Loading versus|Weapon usage|Names|$)", text, re.DOTALL | re.I)
    if maps_section:
        maps = re.findall(r"(\d+)\.\s*([^\d\n]+?(?:Warfare|Offensive|Skirmish)(?:\s*\([^)]+\))?)\s+(\d+)", maps_section.group(1), re.I)
        if maps:
            data["most_played_maps"] = [(m[1].strip(), int(m[2])) for m in maps[:15]]

    # Most killed / most died to: from "Most killed" and "Most died to" sections (name then number)
    # Pattern: link or plain name followed by newline or space and a number
    most_killed = re.findall(r"Most killed[\s\S]*?(\d+)\.\s*\[?([^\]]+?)\]?\s*(\d+)(?=\s*\d+\.|\s*\[)", html)
    if not most_killed:
        pass  # keep optional
    # Simpler: after "Most killed" section, lines like "1. name 46"
    killed_section = re.search(r"Most killed\s*(.*?)(?:Most died to|Melee|$)", text, re.DOTALL | re.I)
    if killed_section:
        entries = re.findall(r"(\d+)\.\s*([^\d\n]+?)\s+(\d+)\s*(?=\d+\.|$)", killed_section.group(1))
        if entries:
            data["most_killed"] = [(e[1].strip(), int(e[2])) for e in entries[:15]]
    died_section = re.search(r"Most died to\s*(.*?)(?:Melee|$)", text, re.DOTALL | re.I)
    if died_section:
        entries = re.findall(r"(\d+)\.\s*([^\d\n]+?)\s+(\d+)\s*(?=\d+\.|$)", died_section.group(1))
        if entries:
            data["most_died_to"] = [(e[1].strip(), int(e[2])) for e in entries[:15]]

    return data

async def main():
    if len(sys.argv) < 2:
        print("Usage: python hll_scrape_test.py <HLL_ID> [PERIOD]")
        print("HLL ID should be 17 digits or 32 alphanumeric (e.g. 76561198199051397)")
        sys.exit(1)

    hll_id = sys.argv[1].strip()

    if len(sys.argv) > 2:
        period = sys.argv[2].strip()
    else:
        period = ""
    

    print(f"Fetching HLL Records profile for HLL ID: {hll_id}")
    print("-" * 50)

    try:
        html = await fetch_profile_page(hll_id, period)
    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code} - {e}")
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Request failed: {e}")
        sys.exit(1)

    data = scrape_with_regex(html)
    data["hll_id"] = data.get("hll_id") or hll_id
    data["profile_url"] = data.get("profile_url") or f"{BASE_URL}{hll_id}"

    print("Scraped data:")
    for k, v in sorted(data.items()):
        if v is None:
            continue
        if isinstance(v, list):
            for i, item in enumerate(v[:10]):  # limit long lists
                safe = str(item).encode("ascii", errors="replace").decode("ascii")
                print(f"  {k}[{i}]: {safe}")
            if len(v) > 10:
                print(f"  ... ({len(v)} total)")
        else:
            safe_v = str(v).encode("ascii", errors="replace").decode("ascii")
            print(f"  {k}: {safe_v}")
    print("-" * 50)
    print("Done.")
    return data

if __name__ == "__main__":
    asyncio.run(main())