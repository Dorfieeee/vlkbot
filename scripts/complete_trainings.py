import asyncio
import csv
from datetime import UTC, datetime
from io import StringIO
from typing import List, Optional
import sys

from config import DB_PATH
from database import (
    create_player_training,
    get_player,
    get_player_trainings,
    get_training,
    update_player_training,
)
from models import Player, PlayerTrainingDetail, Training


async def migrate_old_trainings():
    if len(sys.argv) <= 1:
        print("Usage: python script.py file_path")
        sys.exit(1)

    file_path = sys.argv[1].lower()

    if not file_path:
        print(f"Invalid file_path: {file_path!r}.")
        sys.exit(1)
    # Read CSV from file
    with open(file_path, 'r', encoding='utf-8') as f:
        csv_data = f.read()

    # Parse CSV
    reader = csv.DictReader(StringIO(csv_data))
    rows: List[dict] = list(reader)

    # List of training columns
    training_ids = [
        "ar_basics",
        "ar_pro",
        "at_basics",
        "cmd_basics",
        "parkour",
        "at_pro",
        "recon_basics",
        "sl_basics",
        "tactic_basics",
        "infantry_basics",
        "tank_basics",
        "mg_basics",
    ]

    for row in rows:
        player_id_str = row["player_id"]
        player: Optional[Player] = await get_player(player_id=player_id_str)  # Assuming typing allows str; adjust if needed
        if not player:
            print(f"Player not found for player_id: {player_id_str}")
            continue

        for tid in training_ids:
            if row.get(tid, "0") == "1":
                training: Optional[Training] = await get_training(tid)
                if not training:
                    print(f"Training not found: {tid}")
                    continue

                existing_pts: List[PlayerTrainingDetail] = await get_player_trainings(
                    player_id=player.id, training_id=tid
                )

                now = datetime.now(UTC)
                if existing_pts:
                    pt = existing_pts[0]
                    if pt.status != "completed":
                        success = await update_player_training(
                            pt_id=pt.id,
                            status="completed",
                            completed_at=now if pt.completed_at is None else pt.completed_at,
                        )
                        if success:
                            print(f"Updated to completed: player {player.id}, training {tid}")
                        else:
                            print(f"Failed to update: player {player.id}, training {tid}")
                else:
                    new_id = await create_player_training(
                        player_id=player.id,
                        training_id=tid,
                        message_id=None,
                        status="completed",
                        completed_at=now,
                    )
                    if new_id:
                        print(f"Created completed record: player {player.id}, training {tid}")
                    else:
                        print(f"Failed to create: player {player.id}, training {tid}")


if __name__ == "__main__":
    asyncio.run(migrate_old_trainings())