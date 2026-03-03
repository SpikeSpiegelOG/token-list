#!/usr/bin/env bash
# ============================================================
# SPIKE ARB BOT - Quick Install Script
# ============================================================
# This script sets up the latency arbitrage bot on a fresh system.
# It installs Python dependencies, creates necessary directories,
# and prepares the configuration files.
#
# Usage: bash scripts/install.sh
# ============================================================

set -e

echo "============================================"
echo "  SPIKE ARB BOT - Installation"
echo "============================================"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is required but not installed.${NC}"
    echo "Install Python 3.11+ and try again."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "Python version: ${GREEN}${PYTHON_VERSION}${NC}"

# Check if Python 3.11+
MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]); then
    echo -e "${RED}Python 3.11+ is required. Found ${PYTHON_VERSION}.${NC}"
    exit 1
fi

# Create virtual environment
echo ""
echo -e "${YELLOW}Creating virtual environment...${NC}"
python3 -m venv .venv
source .venv/bin/activate
echo -e "${GREEN}Virtual environment created and activated.${NC}"

# Install dependencies
echo ""
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install --upgrade pip
pip install -e ".[dev]"
echo -e "${GREEN}Dependencies installed.${NC}"

# Create data directories
echo ""
echo -e "${YELLOW}Creating data directories...${NC}"
mkdir -p data logs
touch data/.gitkeep
echo -e "${GREEN}Data directories created.${NC}"

# Setup configuration
echo ""
echo -e "${YELLOW}Setting up configuration...${NC}"
if [ ! -f config/.env ]; then
    cp config/.env.example config/.env
    echo -e "${GREEN}Created config/.env from template.${NC}"
    echo -e "${YELLOW}>>> IMPORTANT: Edit config/.env with your API keys <<<${NC}"
else
    echo "config/.env already exists, skipping."
fi

if [ ! -f config/settings.local.yaml ]; then
    echo "# Local settings overrides (not committed to git)" > config/settings.local.yaml
    echo -e "${GREEN}Created config/settings.local.yaml for local overrides.${NC}"
fi

# Verify installation
echo ""
echo -e "${YELLOW}Verifying installation...${NC}"
python3 -c "
from src.core.config import load_config
from src.core.models import Platform, SignalType
from src.core.event_bus import EventBus
print('All core modules imported successfully.')
config = load_config()
print(f'Config loaded: bot={config.bot.name}, mode={config.bot.mode}')
print('Installation verified!')
"

echo ""
echo "============================================"
echo -e "  ${GREEN}Installation Complete!${NC}"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Edit config/.env with your API keys"
echo "  2. Customize config/settings.yaml"
echo "  3. Activate venv: source .venv/bin/activate"
echo "  4. Run in paper mode: arb-bot run --mode paper"
echo "  5. Or run directly: python -m src.cli run --mode paper"
echo ""
echo "For help: arb-bot --help"
echo ""
