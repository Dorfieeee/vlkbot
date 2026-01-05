# Configuration Files

This directory contains environment-specific configuration files for Discord IDs (channels, roles, guilds).

## Structure

- `dev.py` - Development environment IDs
- `prod.py` - Production environment IDs

## Usage

Set the `ENVIRONMENT` environment variable to switch between environments:

```bash
# Development (default)
export ENVIRONMENT=dev
python main.py

# Production
export ENVIRONMENT=prod
python main.py
```

Or add to your `.env` file:
```
ENVIRONMENT=prod
```

## What Goes Where

### In `.env` (secrets and environment-specific values):
- `DISCORD_TOKEN` - Bot token (secret)
- `API_BASE_URL` - API endpoint
- `API_BEARER_TOKEN` - API authentication (secret)
- `ENVIRONMENT` - Which config to load (dev/prod)

### In `discord_config/dev.py` and `discord_config/prod.py` (non-secret IDs):
- `GUILD_ID` - Discord server ID
- `HLL_ROLE_ID` - Role ID for VIP claims
- `VIP_CLAIM_SUPPORT_ROLE_ID` - Support role ID
- `MEMBER_ROLE_ID` - Member role ID
- `COMMUNITY_ROLE_ID` - Community role ID
- `LOG_CHANNEL_ID` - Logging channel ID

## Adding New Environments

To add a new environment (e.g., `staging`):

1. Create `discord_config/staging.py` with the same structure
2. Update `config.py` to handle the new environment:

```python
elif ENVIRONMENT == "staging":
    from discord_config.staging import (...)
```

## Benefits

- ✅ IDs are version-controlled (unlike `.env`)
- ✅ Easy to switch between environments
- ✅ Clear separation of secrets vs. configuration
- ✅ No need to comment/uncomment code
- ✅ Can have different IDs per environment without conflicts

