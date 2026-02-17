import asyncio
from collections import Counter
import sys
from database import get_player_trainings, get_trainings


async def main():
    trs = await get_trainings()
    if not trs:
        print("No trainings found")
        sys.exit(1)

    pts = await get_player_trainings(limit=1_000_000)

    print([pt.training_id for pt in pts])

    pts_counter = Counter([pt.training_id for pt in pts if pt.status == "assigned" or pt.status == "interested"])

    print(pts_counter)

if __name__ == "__main__":
    asyncio.run(main())