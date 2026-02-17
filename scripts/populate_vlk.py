import asyncio
import os
import sqlite3
import sys

import aiosqlite
from config import DB_PATH
from database import edit_or_create_player


async def populate_vlk() -> None:
    """
    Skips entries that already exist (by player_id).
    """

    if len(sys.argv) <= 1:
        print("Usage: python script.py file_path")
        sys.exit(1)

    file_path = sys.argv[1].lower()

    if not file_path:
        print(f"Invalid file_path: {file_path!r}.")
        sys.exit(1)

    lines = []
    with open(file_path, 'r', encoding='utf-8') as file:
        lines = file.readlines()

    players = [{'player_name': p[0], 'player_id': p[1], 'discord_id': p[2]} for p in [l.strip().split(',') for l in lines[1:]]]

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.cursor()

        try:
            cursor = await conn.execute("SELECT player_id FROM players")
            existing_ids = {row[0] for row in await cursor.fetchall()}

            inserted_count = 0
            skipped_count = 0

            for p in players:
                if p["player_id"] in existing_ids:
                    print(f"Skipping existing player: {p["player_name"]}")
                    skipped_count += 1
                    continue

                await edit_or_create_player(
                    player_id=p['player_id'],
                    player_name=p['player_name'],
                    discord_id=int(p['discord_id']),
                )

                inserted_count += 1
                print(f"Created player: {p['player_name']}")

            await conn.commit()
            print(f"\nPopulation finished:")
            print(f"  Inserted: {inserted_count}")
            print(f"  Skipped (already exists): {skipped_count}")
            print(f"  Total in dict: {len(players)}")

        except sqlite3.Error as e:
            await conn.rollback()
            print(f"Database error: {e}")
        except Exception as e:
            await conn.rollback()
            print(f"Unexpected error: {e}")


if __name__ == "__main__":
    print("Starting initial trainings population...\n")
    asyncio.run(populate_vlk())