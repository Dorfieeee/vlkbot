import asyncio
import os
import sqlite3
import sys

import aiosqlite
from config import DB_PATH
from database import create_training


async def populate_initial_trainings() -> None:
    """
    Insert all trainings from TRAININGS dict into the database.
    Skips entries that already exist (by name).
    """

    if len(sys.argv) <= 1:
        print("Usage: python script.py [dev|prod]")
        sys.exit(1)

    env = sys.argv[1].lower()

    if env not in {"dev", "prod"}:
        print(f"Invalid environment: {env!r}. Allowed: dev, prod")
        sys.exit(1)

    if env == "dev":
        from discord_config.dev import REKRUT_ROLE_ID, TRAINING_ROLES, MEMBER_ROLE_ID
    elif env == "prod":
        from discord_config.prod import REKRUT_ROLE_ID, TRAINING_ROLES, MEMBER_ROLE_ID


    TRAININGS = {
        "Taktická příprava": {
            "id": "tactic_basics",
            "role_id": TRAINING_ROLES["tac_prep_course"],
            "required_roles": [REKRUT_ROLE_ID],
            "is_mandatory": True,
            "img": "https://images-ext-1.discordapp.net/external/WaoYGSPgAsFePw3VupyFmHKlPz9cFo6ZwnlWoPPYgvk/https/i.postimg.cc/mgQf2yb3/taktick-p-prava.png?format=webp&quality=lossless&width=1600&height=900",
            "desc": """Tento výcvik je pořádán pro Rekruty klanu VLKㆍ.\n\nCo se na něm dozvíš:\n• jak hra funguje - zabírání bodů, stavění nodů, zásoby, garrysny, OPčka atd..\n• tipy a triky pro lepší viditelnost ve hře (ideální grafické nastavení)\n• na které role se ve hře zaměřit a kterým se raději vyhnout\n• důležitost flexibility ve tvé squadě. Jak se pohybovat po mapě""",
        },
        "AR výcvik": {
            "id": "ar_basics",
            "role_id": TRAINING_ROLES["ar_course"],
            "required_roles": [REKRUT_ROLE_ID, MEMBER_ROLE_ID],
            "is_mandatory": True,
            "img": "https://images-ext-1.discordapp.net/external/IAZ_SYxxAR-VFdAcBTeMg6AA6QdL4iUZwl9CsVVjcoc/https/i.postimg.cc/Pf0vgY2z/AR-v-cvik.jpg?format=webp&width=1220&height=568",
            "desc": """Tento výcvik je pořádán pro Rekruty klanu VLKㆍ.\n\nO co se jedná:\n• projdete si komplexní výcvik na “opíčí dráze”\n• na konci výcviku Vám bude doporučeno na co se zaměřit a v čem se zlepšovat""",
        },
        "AR výcvik+": {
            "id": "ar_pro",
            "role_id": TRAINING_ROLES["ar_pro_course"],
            "required_roles": [MEMBER_ROLE_ID],
            "img": "https://images-ext-1.discordapp.net/external/IAZ_SYxxAR-VFdAcBTeMg6AA6QdL4iUZwl9CsVVjcoc/https/i.postimg.cc/Pf0vgY2z/AR-v-cvik.jpg?format=webp&width=1220&height=568",
            "desc": """Tento výcvik je pořádán pro klanové hráče.\n\nO co se jedná:\n• projdete si komplexní výcvik na “opíčí dráze”\n• na konci výcviku Vám bude doporučeno na co se zaměřit a v čem se zlepšovat""",
        },
        "Základy AT": {
            "id": "at_basics",
            "role_id": TRAINING_ROLES["at_basic_course"],
            "required_roles": [REKRUT_ROLE_ID, MEMBER_ROLE_ID],
            "is_mandatory": False,
            "img": "https://images-ext-1.discordapp.net/external/MosbdgSUj9qftpshKWBCbOTZml3dYmIFEdY-fp9a3BI/https/i.postimg.cc/rFHxF5hp/z-klady-AT.jpg?format=webp&width=1220&height=659",
            "desc": """Tento výcvik je pořádán pro Rekruty klanu VLKㆍ.\n\nCo tě čeká:\nTeoretická část + ukázky...\n• průraznost tanků: kam střílet a kam nestřílet podle typu pancíře\n• seznámení se s AT třídou...\n• přehled zbraní: trubky, děla, satchel, AT miny, AP miny, granáty\n\nPraktická část:\n• střelba z Panzerschrecku a bazooky na 50 m, 100 m, 150 m, 200 m\n• ukázka i na 730–740 m a 910–950 m""",
        },
        "Parkour": {
            "id": "parkour",
            "role_id": TRAINING_ROLES["parkour_course"],
            "required_roles": [MEMBER_ROLE_ID],
            "img": "https://images-ext-1.discordapp.net/external/mftoSUoEPHQkKNR2PEVGbBI7GaeFjexUvTWFaiklgek/https/i.postimg.cc/FK95tXXM/parkour3.png?format=webp&quality=lossless&width=1220&height=700",
            "desc": """Tento výcvik je pořádán pro klanové hráče. Tento výcvik organizují (a pořádají) ostřílení veteráni klanu VLK.\n\nV tomto výcviku se dozvíte:\n• vysvětlení jumping / vaulting mechaniky\n• ukázka window glitche\n• ukázka spotů\n• typy budov""",
        },
        "Pokročilé AT": {
            "id": "at_pro",
            "role_id": TRAINING_ROLES["at_pro_course"],
            "required_roles": [MEMBER_ROLE_ID],
            "img": "https://images-ext-1.discordapp.net/external/Cia53vqxiyKv07BCauhzIchuu4Ws-nCv_rHdHeyDxeE/https/i.postimg.cc/YC3KDF7M/pokro-il-AT.webp?format=webp&width=1220&height=686",
            "desc": """Cílem tréninku je dokázat zničit nepřátelský garrison nebo dělo pomocí náměrů z Garandu nebo Kar.\n\nCo se naučíte:\n• přesná střelba na vzdálenosti s Panzershreckem na 405 m, 500 m, 550 m, 730 m, 910 m, 800 m\n• přesná střelba na vzdálenosti s Bazukou na 300 m, 380 m, 400 m, 435 m, 475 m, 500 m, 742 m""",
        },
        "Trénink v pěchotě": {
            "id": "infantry_basics",
            "role_id": TRAINING_ROLES["infantry_course"],
            "required_roles": [],
            "img": "https://images-ext-1.discordapp.net/external/G3qLIH5LHtysHy6Z2hPjTAmZTLlLcrLCWjsQgezGnN4/https/i.postimg.cc/x8zqLRW0/tr-nink-v-p-chot.jpg?format=webp&width=1220&height=673",
            "desc": """Co se na něm dozvíš:\n• jak se hýbat\n• co hrát a nehrát\n• jak být užitečný pro tým a svojí squadu""",
        },
        "Trénink v tanku": {
            "id": "tank_basics",
            "role_id": TRAINING_ROLES["tank_course"],
            "required_roles": [],
            "img": "https://images-ext-1.discordapp.net/external/iJBRUIZd0bZp1fg4NzwI9oDAhVwZ4GfrmkG_PXAPNnQ/https/i.postimg.cc/4xzFNHNq/tr-nink-v-tanku.jpg?format=webp&width=500&height=276",
            "desc": """Základní výcvik pro všechny, kteří chtějí rozšířit řady tankistů VLK.\nTento výcvik pořádá Tankový Náborář (popřípadě Tankový Velitel) za asistence Instruktora.\n\nCo se na něm dozvíš:\n• druhy tanků ve hře a jejich role\n• role posádky tanku a jejich úkoly\n• průraznost děl a odolnost pancíře všech tanků\n• jak tanky efektivně ničit\n• jak dokáže pěchota ovlivnit tank (jak z pozice nepřítele tak z pozice spoluhráčů)""",
        },
        "Squad Leader": {
            "id": "sl_basics",
            "role_id": TRAINING_ROLES["sl_course"],
            "required_roles": [MEMBER_ROLE_ID],
            "img": "https://images-ext-1.discordapp.net/external/q8TZBY2a3y1F70PrtBUqsuyndAILIJY2bTR9ORTFUK0/https/i.postimg.cc/D059xWR8/squad-leader.png?format=webp&quality=lossless&width=1000&height=563",
            "desc": """Tento výcvik je pořádán pro klanové hráče. Tento výcvik organizují (a pořádají) ostřílení veteráni klanu VLK.\n\nV tomto výcviku se dozvíte:\n• jak vést squadu\n• jak pracovat s mapou\n• OP placement\n• tipy triky""",
        },
        "Commander": {
            "id": "cmd_basics",
            "role_id": TRAINING_ROLES["cmd_course"],
            "required_roles": [],
            "img": "https://images-ext-1.discordapp.net/external/Kdmun_g4KkhugEca-JhWTuDxK7RYpGQ2A_hMfXq4jp4/https/i.postimg.cc/xTJ5xJwh/commander.jpg?format=webp&width=1220&height=686",
            "desc": """Tento výcvik je pořádán pro komunitní ale i klanové hráče. Tento výcvik organizují (a pořádají) ostřílení veteráni klanu VLK.\n\nV tomto výcviku se dozvíte:\n• jak fungují Commandérovi abillity\n• co jako Commandér dělat a nedělat\n• tipy a triky""",
        },
        "Recon": {
            "id": "recon_basics",
            "role_id": TRAINING_ROLES["recon_course"],
            "required_roles": [],
            "img": "https://images-ext-1.discordapp.net/external/MVlT-0cMw-vghf8URjAZ6suFjGeSYtgjCVJMpzVK9yI/https/i.postimg.cc/g2rxq81L/recon.jpg?format=webp&width=1220&height=673",
            "desc": """Provedem vás základy odstřelovače, jak nadmiřovat, předmiřovat, jak by se měl sniper chovat v případě, kdy obléhá nepřátelskou artynu, kde a za jaké situace stavět své OP, výhodné spoty atd...""",
        },
        "MG": {
            "id": "mg_basics",
            "role_id": TRAINING_ROLES["mg_course"],
            "required_roles": [],
            "img": "https://images-ext-1.discordapp.net/external/K730d2zFNXrGWEKi6zE09YCkOmf36llIjmf0I5xeU3s/https/i.postimg.cc/Dy7hThg2/mg.jpg?format=webp&width=1220&height=686",
            "desc": """Tento výcvik je určen pro všechny se zájmem o roli MG.\n\nO co se jedná:\n• během výcviku si projdete klíčové aspekty používání kulometu – od správného rozložení pozice až po efektivní palebné krytí pro tým\n• naučíte se využívat terén ve svůj prospěch, kdy a jak se přesouvat\n• součástí je i praktická část zaměřená na potlačování nepřítele\n\nNa konci výcviku obdržíte zpětnou vazbu s doporučením, na co se zaměřit a co zlepšit, aby vaše role MG byla co nejefektivnější v ostré akci.""",
        },
        "Základy HLL": {
            "id": "hll_basics",
            "role_id": TRAINING_ROLES["hll_basics"],
            "required_roles": [],
            "is_mandatory": False,
            "img": "https://images-ext-1.discordapp.net/external/o6fjxW7PypIf-0RQyj_vER5aAsNSRkFa1rrmy_ArAE0/https/i.postimg.cc/GtGZYjsF/image.png?format=webp&quality=lossless&width=2032&height=1694",
            "desc": """Co tě čeká:\nVysvětlíme základní mechaniky Hell Let Loose a jak se stát dobrým a užitečným hráčem.""",
        },
    }

    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        try:
            # Get existing training names to avoid duplicates
            cursor = await conn.execute("SELECT name FROM trainings")
            existing_names = {row[0] for row in await cursor.fetchall()}

            inserted_count = 0
            skipped_count = 0

            for name, data in TRAININGS.items():
                if name in existing_names:
                    print(f"Skipping existing training: {name}")
                    skipped_count += 1
                    continue

                level = "komunita"          # default — change logic if needed
                if REKRUT_ROLE_ID in data["required_roles"]:
                    level = "rekrut"
                elif MEMBER_ROLE_ID in data["required_roles"]:
                    level = "valkyria"

                # You can make this more sophisticated later
                is_mandatory = data["is_mandatory"] if "is_mandatory" in data else False

                await create_training(
                    id=data["id"],
                    name=name,
                    description=data["desc"],
                    level=level,
                    assigned_role=str(data["role_id"]),          # role_id → assigned_role
                    is_mandatory=is_mandatory,
                    required_roles=[str(r) for r in data["required_roles"]],
                    img=data["img"],              # ← add this if you updated the function
                )

                inserted_count += 1
                print(f"Created training: {name} (level: {level})")

            await conn.commit()
            print(f"\nPopulation finished:")
            print(f"  Inserted: {inserted_count}")
            print(f"  Skipped (already exists): {skipped_count}")
            print(f"  Total in dict: {len(TRAININGS)}")

        except sqlite3.Error as e:
            await conn.rollback()
            print(f"Database error: {e}")
        except Exception as e:
            await conn.rollback()
            print(f"Unexpected error: {e}")


if __name__ == "__main__":
    print("Starting initial trainings population...\n")
    asyncio.run(populate_initial_trainings())