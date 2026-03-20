#!/usr/bin/env bash

# Adaptive Stealth Network - One-Line Installer
# Usage: bash <(curl -sL https://raw.githubusercontent.com/Decaliostro/adaptive-stealth-network/master/install.sh)

set -e

REPO_URL="https://github.com/Decaliostro/adaptive-stealth-network.git"
INSTALL_DIR="/opt/asn"

echo "========================================================"
echo "    Adaptive Stealth Network (ASN) - Installer          "
echo "========================================================"
echo

# 1. Check Root
if [ "$(id -u)" != "0" ]; then
    echo "[!] Error: This script must be run as root. Try 'sudo bash ...'"
    exit 1
fi

# 2. Install Dependencies
echo "[*] Installing required packages..."
if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y -q >/dev/null
    apt-get install -y -q git curl wget >/dev/null
elif command -v yum >/dev/null 2>&1; then
    yum install -y -q git curl wget >/dev/null
else
    echo "[!] Unsupported package manager. Please install git and curl manually."
    exit 1
fi

# 3. Install Docker if not present
if ! command -v docker >/dev/null 2>&1; then
    echo "[*] Installing Docker..."
    curl -fsSL https://get.docker.com | sh >/dev/null 2>&1
    systemctl enable --now docker
else
    echo "[*] Docker is already installed."
fi

# 4. Clone or Update Repository
if [ -d "$INSTALL_DIR" ]; then
    echo "[*] ASN is already installed at $INSTALL_DIR. Updating..."
    cd $INSTALL_DIR
    git pull
else
    echo "[*] Cloning repository to $INSTALL_DIR..."
    git clone $REPO_URL $INSTALL_DIR
    cd $INSTALL_DIR
fi

# 5. Start Container
echo "[*] Starting ASN containers..."
docker compose up -d --build

echo
echo "========================================================"
echo "    Installation Complete!                              "
echo "========================================================"
SERVER_IP=$(curl -s ifconfig.me || echo "your_server_ip")
echo "  Management Panel: http://$SERVER_IP:8000"
echo "  To view logs: cd $INSTALL_DIR && docker compose logs -f"
echo "========================================================"
