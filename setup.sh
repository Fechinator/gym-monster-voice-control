#!/bin/bash
# GM Voice Control — Raspberry Pi Setup Script
# Run: curl -sSL https://raw.githubusercontent.com/Fechinator/gym-monster-voice-control/main/setup.sh | bash

set -e

echo "========================================"
echo "  GM Voice Control — Setup"
echo "  Gym Monster 2S Voice Toggle"
echo "========================================"
echo

# System packages
echo "[1/5] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv python3-dev \
  libasound2-dev libportaudio2 portaudio19-dev \
  bluetooth bluez libbluetooth-dev alsa-utils

# Python venv
echo "[2/5] Setting up Python environment..."
python3 -m venv ~/gm-voice
source ~/gm-voice/bin/activate
pip install --upgrade pip -q
pip install openwakeword sounddevice websockets numpy bleak -q

# Clone repo
echo "[3/5] Downloading project..."
if [ -d ~/gm-voice-control ]; then
  cd ~/gm-voice-control && git pull
else
  git clone https://github.com/Fechinator/gym-monster-voice-control.git ~/gm-voice-control
fi

# Bluetooth
echo "[4/5] Configuring Bluetooth..."
grep -q "^AutoEnable=true" /etc/bluetooth/main.conf 2>/dev/null || \
  echo 'AutoEnable=true' | sudo tee -a /etc/bluetooth/main.conf > /dev/null
sudo systemctl enable bluetooth

# Systemd service
echo "[5/5] Installing service..."
USER=$(whoami)
sed "s/%i/$USER/g" ~/gm-voice-control/systemd/gm-voice.service | \
  sudo tee /etc/systemd/system/gm-voice.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable gm-voice
sudo systemctl start gm-voice

echo
echo "========================================"
echo "  Setup complete!"
echo "  Service status: $(sudo systemctl is-active gm-voice)"
echo "  Logs: sudo journalctl -u gm-voice -f"
echo "  Dashboard: http://$(hostname -I | awk '{print $1}'):8888"
echo "========================================"
echo
echo "  Plug in your USB microphone and say"
echo "  \"HEY JARVIS\" to toggle!"
echo
