#!/usr/bin/env python3
"""Script runner for different environments - similar to npm scripts."""
import os
import sys
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    """Main entry point - can be called from pyproject.toml scripts."""
    # Get environment from command line or default to dev
    if len(sys.argv) > 1:
        environment = sys.argv[1].lower()
    else:
        environment = os.getenv("ENVIRONMENT", "dev").lower()
    
    # Set environment variable
    os.environ["ENVIRONMENT"] = environment
    
    # Run main.py
    cmd = [sys.executable, "main.py"]
    
    print(f"🚀 Starting bot in {environment} environment...")
    print(f"📁 Loading .env.{environment} (if exists)")
    
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(130)


if __name__ == "__main__":
    main()

