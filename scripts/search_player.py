#!/usr/bin/env python3
"""
Usage: python search_player.py [SEARCH_TERM]
Example: python search_player.py kanec
"""
import asyncio
import sys
import httpx  # pip install httpx if needed

BASE_URL = "https://hllrecords.com/api/search?query="

async def search_player_page(name: str) -> dict:
    """Fetch raw HTML for HLL Records profile asynchronously."""
    url = f"{BASE_URL}{name}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=15)
        response.raise_for_status()  # Raise for 4xx/5xx errors
        return response.json()

async def main():
    if len(sys.argv) < 1:
        print("Usage: python hll_scrape_test.py <SEARCH_TERM>")
        sys.exit(1)

    search_term = sys.argv[1].strip()  

    print(f"Fetching HLL Records query results for HLL Name: {search_term}")
    print("-" * 50)

    try:
        data = await search_player_page(search_term)
    except httpx.HTTPStatusError as e:
        print(f"HTTP error: {e.response.status_code} - {e}")
        sys.exit(1)
    except httpx.RequestError as e:
        print(f"Request failed: {e}")
        sys.exit(1)

    print("Scraped data:")
    for item in data["results"]:
        print(f"{item["externalId"]}: {item["name"]}")
    print("-" * 50)
    print("Done.")
    return data

if __name__ == "__main__":
    asyncio.run(main())