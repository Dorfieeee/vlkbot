# Environment Setup Guide

This project supports environment-specific configuration, similar to npm's `npm run dev` / `npm run prod`.

## Quick Start

### Option 1: Using Makefile (Recommended - Most npm-like)

```bash
# Development
make dev

# Production
make prod
```

### Option 2: Using run.py Script

```bash
# Development
python run.py dev

# Production
python run.py prod
```

### Option 3: Direct Environment Variable

```bash
# Development
ENVIRONMENT=dev python main.py

# Production
ENVIRONMENT=prod python main.py
```

## Environment Files

The project automatically loads environment-specific `.env` files:

- **Development**: `.env.dev`
- **Production**: `.env.prod`
- **Fallback**: `.env` (if environment-specific file doesn't exist)

### Setting Up Your .env Files

1. **Create `.env.dev`** for development:
```bash
# Development Environment Variables
DISCORD_TOKEN=your_dev_bot_token_here
API_BASE_URL=https://api-dev.example.com
BASE_URL=https://api-dev.example.com
API_BEARER_TOKEN=your_dev_api_token_here
ENVIRONMENT=dev
```

2. **Create `.env.prod`** for production:
```bash
# Production Environment Variables
DISCORD_TOKEN=your_prod_bot_token_here
API_BASE_URL=https://api.example.com
BASE_URL=https://api.example.com
API_BEARER_TOKEN=your_prod_api_token_here
ENVIRONMENT=prod
```

## How It Works

1. **Environment Detection**: The `ENVIRONMENT` variable determines which config to load
   - Defaults to `dev` if not set
   - Can be set via: environment variable, `.env` file, or command line

2. **Config Loading**:
   - Loads `.env.{ENVIRONMENT}` file (e.g., `.env.dev`, `.env.prod`)
   - Falls back to `.env` if environment-specific file doesn't exist
   - Loads Discord IDs from `discord_config/{ENVIRONMENT}.py`

3. **File Structure**:
   ```
   .env.dev          # Development secrets (DISCORD_TOKEN, API keys, etc.)
   .env.prod         # Production secrets
   discord_config/
     ├── dev.py      # Development Discord IDs (channels, roles)
     └── prod.py     # Production Discord IDs
   ```

## What Goes Where

### In `.env.dev` / `.env.prod` (Secrets):
- `DISCORD_TOKEN` - Bot token
- `API_BASE_URL` - API endpoint
- `API_BEARER_TOKEN` - API authentication token
- `ENVIRONMENT` - Which environment to use (optional, can be set via command)

### In `discord_config/dev.py` / `discord_config/prod.py` (Non-secrets):
- `GUILD_ID` - Discord server ID
- `HLL_ROLE_ID` - Role ID for VIP claims
- `VIP_CLAIM_SUPPORT_ROLE_ID` - Support role ID
- `MEMBER_ROLE_ID` - Member role ID
- `COMMUNITY_ROLE_ID` - Community role ID
- `LOG_CHANNEL_ID` - Logging channel ID

## Benefits

✅ **Separate configs per environment** - No more commenting/uncommenting code  
✅ **Version-controlled IDs** - Discord IDs are in git, secrets are not  
✅ **Easy switching** - Just run `make dev` or `make prod`  
✅ **Safe defaults** - Defaults to `dev` to prevent accidental production runs  
✅ **Clean separation** - Secrets in `.env`, IDs in Python files

## Troubleshooting

**Problem**: "Config loaded successfully" but wrong IDs are used  
**Solution**: Check that `ENVIRONMENT` is set correctly and the corresponding `discord_config/{env}.py` file has the right IDs

**Problem**: `.env.dev` not loading  
**Solution**: Make sure the file exists and is named exactly `.env.dev` (not `.env.dev.txt`)

**Problem**: Makefile commands not found  
**Solution**: Install `make` or use `python run.py dev` instead

