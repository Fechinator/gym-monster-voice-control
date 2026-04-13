#!/bin/bash
# GM Voice Control — Raspberry Pi Setup Script
# Run: curl -sSL https://raw.githubusercontent.com/Fechinator/gym-monster-voice-control/main/setup.sh | bash

set -e

USER_NAME=$(whoami)
HOME_DIR=$(eval echo ~$USER_NAME)

echo "========================================"
echo "  GM Voice Control — Setup"
echo "  Gym Monster Voice Toggle"
echo "========================================"
echo

# System packages
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv python3-dev \
  libasound2-dev libportaudio2 portaudio19-dev \
  bluetooth bluez libbluetooth-dev alsa-utils git

# Python venv
echo "[2/6] Setting up Python environment..."
python3 -m venv $HOME_DIR/gm-voice
source $HOME_DIR/gm-voice/bin/activate
pip install --upgrade pip -q
pip install openwakeword sounddevice websockets numpy bleak -q

# Download wake word models (OWW 0.6+ doesn't ship them)
echo "[3/6] Downloading wake word models..."
python3 -c 'import openwakeword; openwakeword.utils.download_models()' 2>/dev/null || true

# Clone repo
echo "[4/6] Downloading project..."
if [ -d $HOME_DIR/gm-voice-control ]; then
  cd $HOME_DIR/gm-voice-control && git pull
else
  git clone https://github.com/Fechinator/gym-monster-voice-control.git $HOME_DIR/gm-voice-control
fi

# Bluetooth + USB audio
echo "[5/6] Configuring Bluetooth + Audio..."
grep -q "^AutoEnable=true" /etc/bluetooth/main.conf 2>/dev/null || \
  echo 'AutoEnable=true' | sudo tee -a /etc/bluetooth/main.conf > /dev/null
sudo systemctl enable bluetooth
# Ensure USB audio driver loads at boot
grep -q "snd-usb-audio" /etc/modules 2>/dev/null || \
  echo 'snd-usb-audio' | sudo tee -a /etc/modules > /dev/null
sudo modprobe snd-usb-audio 2>/dev/null || true

# Systemd service
echo "[6/6] Installing service..."
cat > /tmp/gm-voice.service << EOF
[Unit]
Description=GM Voice Control - Gym Monster
After=network-online.target bluetooth.target
Wants=network-online.target bluetooth.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$HOME_DIR/gm-voice-control
ExecStartPre=/bin/sleep 10
ExecStart=$HOME_DIR/gm-voice/bin/python gm_jarvis.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sudo cp /tmp/gm-voice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gm-voice
sudo systemctl start gm-voice

echo
echo "========================================"
echo "  Setup complete!"
echo "  Service: $(sudo systemctl is-active gm-voice)"
echo "  Logs:    sudo journalctl -u gm-voice -f"
echo "========================================"
echo
echo "  Plug in your USB microphone and say"
echo "  \"HEY JARVIS\" to toggle!"
echo
