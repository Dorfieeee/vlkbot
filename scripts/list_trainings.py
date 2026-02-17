import asyncio
from collections import Counter

from database import get_player_trainings, get_trainings


async def run():

    trs = await get_trainings()

    pts = await get_player_trainings()

    pts_counter = Counter([pt.training_id for pt in pts if pt.status == "assigned" or pt.status == "interested"])

    out = ""

    for t in trs:
        role = f"<@{t.assigned_role}>"
        out += f"{t.name}\n"
        out += f"↳ Počet přihlášených: {pts_counter[t.id]} {role}\n"

    print(out)

if __name__ == "__main__":
    asyncio.run(run())