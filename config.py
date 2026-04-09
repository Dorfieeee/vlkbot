"""Configuration and environment variables."""
import os
from pathlib import Path
from dotenv import load_dotenv


# --- Paths ------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "db.sqlite3"


# --- Environment variables --------------------------------------------------

# First, load base .env to get ENVIRONMENT variable (if set there)
# This allows ENVIRONMENT to be set in .env file
load_dotenv(BASE_DIR / ".env", override=False)

# Determine which environment to use (dev, prod, etc.)
# Can be set via: 1) Environment variable, 2) .env file, 3) Command line
# Defaults to 'dev' for safety
ENVIRONMENT = os.getenv("ENVIRONMENT", "dev").lower()

# Now load environment-specific .env file (e.g., .env.dev, .env.prod)
# This will override any values from base .env
env_file = BASE_DIR / f".env.{ENVIRONMENT}"
if env_file.exists():
    load_dotenv(env_file, override=True)

# Load environment-specific Discord IDs
if ENVIRONMENT == "prod":
    from discord_config.prod import (
        GUILD_ID,
        HLL_ROLE_ID,
        LOG_CHANNEL_ID,
        TRAINING_LOG_CHANNEL_ID,
        MEMBER_CHAT_CHANNEL_ID,
        REKRUT_CHAT_CHANNEL_ID,
        REKRUT_TANK_CHAT_CHANNEL_ID,
        SUPPORT_ROLE_ID,
        MEMBER_ROLE_ID,
        MIX_EVENT_ROLE_ID,
        COMMUNITY_ROLE_ID,
        REKRUT_ROLE_ID,
        REKRUT_TANK_ROLE_ID,
        REKRUT_INF_ROLE_ID,
        MEMBER_TANK_ROLE_ID,
        TRAINING_ROLES,
        LFP_TRAINING_ROLES,
    )
else:
    from discord_config.dev import (
        GUILD_ID,
        HLL_ROLE_ID,
        LOG_CHANNEL_ID,
        TRAINING_LOG_CHANNEL_ID,
        MEMBER_CHAT_CHANNEL_ID,
        REKRUT_CHAT_CHANNEL_ID,
        REKRUT_TANK_CHAT_CHANNEL_ID,
        SUPPORT_ROLE_ID,
        MEMBER_ROLE_ID,
        MIX_EVENT_ROLE_ID,
        COMMUNITY_ROLE_ID,
        REKRUT_ROLE_ID,
        REKRUT_TANK_ROLE_ID,
        REKRUT_INF_ROLE_ID,
        MEMBER_TANK_ROLE_ID,
        TRAINING_ROLES,
        LFP_TRAINING_ROLES,
    )

# Secrets and API configuration (still from .env)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL")  # e.g. https://api.example.com
API_BASE_URL_2 = os.getenv("API_BASE_URL_2")  # e.g. https://api.example.com
API_BASE_URL_3 = os.getenv("API_BASE_URL_3")  # e.g. https://api.example.com
BASE_URL = os.getenv("BASE_URL")  # e.g. https://api.example.com
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")

# --- Validation -------------------------------------------------------------

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Add it to your environment or .env file.")

if not API_BASE_URL or not API_BEARER_TOKEN:
    raise RuntimeError(
        "API_BASE_URL and API_BEARER_TOKEN must be set to talk to your remote API. "
        "Add them to your environment or .env file."
    )


# --- Constants --------------------------------------------------------------

INFINITE_VIP_DATE = "3000-01-01T00:00:00+00:00"
SERVER_URLS = [
    API_BASE_URL,
    API_BASE_URL_2,
    API_BASE_URL_3,
]
SERVER_NUMBERS = [1, 6]
MAX_CONCURRENT_SEARCHES = 3
SEARCH_TIMEOUT_MINUTES = 10
FREE_VIP_REWARD_LENGTH=10

