## VLK Discord Bot

Simple seasonal Discord bot for linking a player's game account to their Discord account
and granting a one-time 10-day VIP reward.

### Setup

- **Requirements**: Python 3.12+, `uv` (optional but recommended).
- Install dependencies:

```bash
uv sync
```

- Create a `.env` file in the project root:

```bash
DISCORD_TOKEN=your_discord_bot_token_here
API_BASE_URL=https://your-game-api.example.com
API_BEARER_TOKEN=your_api_bearer_token_here
# Optional: restrict VIP button usage to a specific channel
```

### Running the bot

```bash
uv run python main.py
```

### Running with Docker

Build the image:

```bash
docker build -t vlk-discord-bot .
```

Run it (reusing your local `.env` for configuration):

```bash
docker run --rm \
  --env-file .env \
  vlk-discord-bot
```

If you want the local SQLite DB (`claims.sqlite3`) to persist outside the container, mount a volume:

```bash
docker run --rm \
  --env-file .env \
  -v "$(pwd)/claims.sqlite3:/app/claims.sqlite3" \
  vlk-discord-bot
```

### Running with Docker Compose

With `docker-compose.yml` in this folder and your `.env` configured, you can simply run:

```bash
docker compose up --build
```

This will:
- Build the image from the local `Dockerfile`.
- Load all environment variables from `.env`.
- Persist `claims.sqlite3` on the host via a bind mount.

### Usage

1. Invite the bot to your server with the `applications.commands` and standard bot permissions.
2. In the channel where you want the claim button to live, run:

```text
!post_vip_claim
```

3. Players click the button, enter their game ID, and the bot:
   - Checks a local SQLite database to ensure they haven't already claimed.
   - Looks up their player record via your remote API.
   - Links their Discord ID on the remote service.
   - Grants 10 days of VIP (if they are not already VIP).
   - Records the claim locally and responds with an ephemeral confirmation.


