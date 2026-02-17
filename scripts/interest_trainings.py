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


async def migrate_interest_from_csv():
    if len(sys.argv) <= 1:
        print("Usage: python script.py file_path")
        sys.exit(1)

    file_path = sys.argv[1]

    # Read CSV from file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            csv_data = f.read()
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)

    # Parse CSV
    reader = csv.DictReader(StringIO(csv_data))
    rows: List[dict] = list(reader)

    # List of training columns (same as before)
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

    print(f"Starting migration from CSV: {file_path}")
    print(f"Processing {len(rows)} players...\n")

    processed = 0
    skipped = 0
    created = 0
    updated = 0
    errors = 0

    for row in rows:
        player_id_str = row.get("player_id", "").strip()
        if not player_id_str:
            print(f"Skipping row - missing player_id")
            errors += 1
            continue

        player: Optional[Player] = await get_player(player_id=player_id_str)
        if not player:
            print(f"Player not found for player_id: {player_id_str}")
            errors += 1
            continue

        processed += 1

        for tid in training_ids:
            # Only process if marked as interested (1)
            if row.get(tid, "0").strip() != "1":
                continue

            training: Optional[Training] = await get_training(tid)
            if not training:
                print(f"Training not found: {tid} for player {player.id}")
                errors += 1
                continue

            # Get existing records (should usually be 0 or 1)
            existing_pts: List[PlayerTrainingDetail] = await get_player_trainings(
                player_id=player.id, training_id=tid
            )

            now = datetime.now(UTC)

            if existing_pts:
                pt = existing_pts[0]  # assuming we take the first / only one

                if pt.status == "completed":
                    # Skip - already completed, we don't downgrade or touch it
                    skipped += 1
                    # Optional: print(f"Skipped (already completed): player {player.id}, training {tid}")
                    continue

                # Otherwise: interested, in_progress, pending, etc. → we can update to interested
                success = await update_player_training(
                    pt_id=pt.id,
                    status="interested",
                    # Do NOT overwrite completed_at if it exists
                    completed_at=pt.completed_at,
                )
                if success:
                    updated += 1
                    print(f"Updated to interested: player {player.id}, training {tid}")
                else:
                    print(f"Failed to update to interested: player {player.id}, training {tid}")
                    errors += 1

            else:
                # No existing record → create new one as interested
                new_id = await create_player_training(
                    player_id=player.id,
                    training_id=tid,
                    message_id=None,
                    status="interested",
                    completed_at=None,           # not completed yet
                )
                if new_id:
                    created += 1
                    print(f"Created interested record: player {player.id}, training {tid}")
                else:
                    print(f"Failed to create interested record: player {player.id}, training {tid}")
                    errors += 1

    print("\n" + "="*60)
    print("Migration summary:")
    print(f"  Players processed:     {processed}")
    print(f"  Records created:       {created}")
    print(f"  Records updated:       {updated}")
    print(f"  Records skipped:       {skipped} (already completed)")
    print(f"  Errors encountered:    {errors}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(migrate_interest_from_csv())