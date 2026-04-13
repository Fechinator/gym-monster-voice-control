# Gym Monster Voice Control 🏋️🎙️

> **"Hey Jarvis" → Gym Monster toggles weight. Hands-free. No app needed.**

Voice-activated weight toggle for the [Speediance Gym Monster 2S](https://speediance.com/) using a Raspberry Pi and an ESP32-S3 (M5Stack AtomS3U). Say the wake word and your equipment responds — completely hands-free during your workout.

<p align="center">
  <img src="docs/architecture.png" alt="Architecture" width="700">
</p>

## How It Works

```
🎙️ USB Microphone          → Raspberry Pi (Wake Word Detection)
🧠 OpenWakeWord "Hey Jarvis" → BLE command to ESP32
⚡ M5Stack AtomS3U          → USB HID LEFT Arrow keypress
🏋️ Gym Monster 2S          → Weight toggles on/off!
```

The system uses **Bluetooth Low Energy (BLE)** to communicate wirelessly between the Raspberry Pi and the AtomS3U, which is plugged directly into the Gym Monster's USB-A port acting as a USB keyboard.

## Hardware Required

| Component | Purpose | ~Cost |
|-----------|---------|-------|
| [M5Stack AtomS3U](https://shop.m5stack.com/products/atoms3u) | USB HID keyboard bridge (ESP32-S3, USB-A male) | ~$8 |
| Raspberry Pi 4 (or 3B+, Zero 2 W) | Wake word detection + BLE client | ~$35 |
| USB Microphone | Audio input (any USB mic or USB headset) | ~$10 |
| USB-C power supply | Power for the Raspberry Pi | ~$10 |

**Total: ~$63** for completely hands-free gym equipment control.

## Quick Start

### 1. Flash the AtomS3U

Install [Arduino CLI](https://arduino.github.io/arduino-cli/) and the ESP32 board package:

```bash
arduino-cli core install esp32:esp32
```

Compile and flash the firmware (AtomS3U connected to PC via USB):

```bash
arduino-cli compile --fqbn "esp32:esp32:esp32s3:USBMode=default,CDCOnBoot=default" firmware/gm_hid_bridge

arduino-cli upload --fqbn "esp32:esp32:esp32s3:USBMode=default,CDCOnBoot=default" --port <PORT> firmware/gm_hid_bridge
```

> ⚠️ After flashing, **unplug and replug** the AtomS3U to exit download mode.

Then plug it into the **Gym Monster's USB-A port**.

### 2. Set Up the Raspberry Pi

Flash **Raspberry Pi OS Lite (64-bit)** onto an SD card. Boot the Pi and run:

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv python3-dev \
  libasound2-dev libportaudio2 portaudio19-dev \
  bluetooth bluez libbluetooth-dev alsa-utils

# Create virtual environment
python3 -m venv ~/gm-voice
source ~/gm-voice/bin/activate

# Install Python packages
pip install openwakeword sounddevice websockets numpy bleak

# Clone this repo
git clone https://github.com/Fechinator/gym-monster-voice-control.git ~/gm-voice-control
```

### 3. Enable Bluetooth Auto-Power

```bash
# Ensure Bluetooth powers on at boot
echo 'AutoEnable=true' | sudo tee -a /etc/bluetooth/main.conf
sudo systemctl enable bluetooth
```

### 4. Install as Service (Auto-Start)

```bash
sudo cp ~/gm-voice-control/systemd/gm-voice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gm-voice
sudo systemctl start gm-voice
```

The service will:
- ✅ Start automatically on boot
- ✅ Retry BLE connection until the AtomS3U is found
- ✅ Wait for a USB microphone to be plugged in
- ✅ Restart automatically on crashes

### 5. Test It!

Plug in your USB microphone, make sure the AtomS3U is in the Gym Monster, and say **"Hey Jarvis"**!

Check logs:
```bash
sudo journalctl -u gm-voice -f
```

## Web Dashboard

A real-time monitoring dashboard is available at `http://<pi-ip>:8888` showing:
- Live wake word confidence visualization
- Toggle event log with timestamps
- BLE connection status

## Configuration

Edit `gm_jarvis.py` to customize:

| Setting | Default | Description |
|---------|---------|-------------|
| `WAKE_WORD` | `hey_jarvis_v0.1` | OpenWakeWord model name |
| `THRESHOLD` | `0.5` | Wake word confidence threshold (0.0–1.0) |
| `COOLDOWN_SECONDS` | `3.0` | Minimum seconds between triggers |
| `HTTP_PORT` | `8888` | Web dashboard port |

### Changing the Key

The default key sent to the Gym Monster is **LEFT Arrow** (`0x50`). To change it, edit `firmware/gm_hid_bridge/gm_hid_bridge.ino`:

```cpp
#define DEFAULT_TOGGLE_KEY  0x50  // Change to desired HID keycode
```

Common HID keycodes: `0x50` LEFT, `0x4F` RIGHT, `0x52` UP, `0x51` DOWN, `0x28` ENTER, `0x2C` SPACE

## Project Structure

```
gym-monster-voice-control/
├── firmware/
│   └── gm_hid_bridge/
│       └── gm_hid_bridge.ino    # ESP32-S3 firmware (BLE + USB HID)
├── web/
│   └── index.html               # Real-time monitoring dashboard
├── systemd/
│   └── gm-voice.service         # Auto-start service file
├── gm_jarvis.py                 # Main controller (wake word + BLE)
├── setup.sh                     # One-line Pi setup script
└── README.md
```

## How It Was Built

This project was born out of frustration with the Gym Monster 2S lacking a simple hands-free weight toggle. The journey:

1. **Attempted Bluetooth HID** from a phone — the Gym Monster doesn't support BT keyboards
2. **Built a USB HID bridge** using the M5Stack AtomS3U (ESP32-S3 with USB-A connector)
3. **Added voice control** with OpenWakeWord running on a Raspberry Pi
4. **Connected everything via BLE** — Pi detects wake word, sends BLE command to AtomS3U, which sends USB keypress to Gym Monster

The AtomS3U is perfect for this because it has a native USB-A male connector — it plugs directly into the Gym Monster without any adapters.

## Troubleshooting

### AtomS3U not detected after flashing
The ESP32-S3 enters download mode after flashing. **Unplug and replug** the device.

### BLE connection fails
- Make sure Bluetooth is powered on: `sudo bluetoothctl power on`
- Check if the AtomS3U is advertising: `sudo bluetoothctl scan on` — look for "GM HID Bridge"
- The service retries every 10 seconds automatically

### No microphone detected
- Check with `arecord -l` — your USB mic should appear
- The service waits and retries every 5 seconds until a mic is found

### Wake word not triggering
- Lower the threshold in `gm_jarvis.py` (try `0.3`)
- Speak clearly and directly into the microphone
- Check logs: `sudo journalctl -u gm-voice -f`

## License

MIT License — see [LICENSE](LICENSE)

---

**Built with ❤️ by [FechTech](https://github.com/Fechinator)** — because sometimes you just need your gym to listen.
