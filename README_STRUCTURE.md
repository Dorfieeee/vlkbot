# Project Structure

This document describes the organization of the VIP Discord bot codebase.

## Directory Structure

```
vlk_discord_bot/
├── main.py              # Entry point - starts the bot
├── bot.py               # Bot initialization, commands, and event handlers
├── config.py            # Configuration and environment variables
├── models.py            # Data classes (API_Player, PlayerSearchResult)
├── database.py          # SQLite database operations
├── api_client.py        # API client for game server communication
├── utils.py             # Utility functions (logging, search tracking, VIP processing)
├── views/               # Discord UI components
│   ├── __init__.py      # Package exports
│   ├── vip_claim.py     # VIP claim button and modal
│   └── player_select.py # API_Player selection dropdown and view
├── .env                 # Environment variables (not in git)
└── db.sqlite3       # SQLite database (generated at runtime)
```

## Module Descriptions

### `main.py`
- Entry point for the application
- Handles bot startup and shutdown
- Manages API client lifecycle

### `bot.py`
- Bot instance initialization
- Discord event handlers (`on_ready`, `setup_hook`)
- Slash commands (`/post_vip_claim`)
- Bot configuration and command registration

### `config.py`
- Environment variable loading
- Configuration constants (VIP_DAYS, SERVER_NUMBER, etc.)
- Path configuration (BASE_DIR, DB_PATH)
- Environment validation

### `models.py`
- `API_Player`: Represents a player profile from the game API
- `PlayerSearchResult`: Represents search results

### `database.py`
- SQLite database initialization
- CRUD operations for VIP claims
- Functions: `init_db()`, `has_claimed()`, `is_player_claimed()`, `record_claim()`

### `api_client.py`
- `ApiClient`: HTTP client for game server API
- Methods:
  - `fetch_player_by_game_id()`: Get player profile
  - `edit_player_account()`: Link Discord to game account
  - `add_vip()`: Grant/extend VIP status
  - `search_players()`: Search for players by name

### `utils.py`
- `send_log_message()`: Log to Discord channel
- `send_response_or_followup()`: Smart interaction response
- `process_vip_reward()`: Core VIP processing logic

### `views/`
#### `vip_claim.py`
- `VipClaimView`: Persistent view with claim button
- `VipClaimModal`: Modal for entering player name

#### `player_select.py`
- `PlayerSelect`: Dropdown menu for selecting from search results
- `PlayerSelectView`: View containing dropdown and action buttons

## Running the Bot

```bash
python main.py
```

## Environment Variables

Required variables in `.env`:
- `DISCORD_TOKEN`: Discord bot token
- `API_BASE_URL`: Game server API base URL
- `API_BEARER_TOKEN`: Bearer token for API authentication
- `GUILD_ID`: Discord server ID
- `HLL_ROLE_ID`: Required role ID for claiming VIP
- `LOG_CHANNEL_ID`: Channel for logging
- `BASE_URL`: Base URL for player profile links

## Benefits of This Structure

1. **Separation of Concerns**: Each module has a single, clear responsibility
2. **Maintainability**: Easy to find and modify specific functionality
3. **Testability**: Components can be tested independently
4. **Scalability**: Easy to add new features without affecting existing code
5. **Readability**: Smaller, focused files are easier to understand
6. **Reusability**: Components can be imported and reused as needed

## Migration Notes

- Original `main.py` is backed up as `main.py.old`
- All functionality remains the same
- No changes to `.env` configuration required
- Database schema unchanged

