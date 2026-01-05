.PHONY: dev prod help

# Default target
help:
	@echo "Available commands:"
	@echo "  make dev    - Run bot in development mode"
	@echo "  make prod   - Run bot in production mode"
	@echo ""
	@echo "Alternative: python run.py <env>"

dev:
	@ENVIRONMENT=dev python run.py dev

prod:
	@ENVIRONMENT=prod python run.py prod

