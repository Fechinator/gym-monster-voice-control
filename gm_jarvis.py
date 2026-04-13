"""
GM Voice Control — Gym Monster Wake Word Detector with Web UI

Say "Hey Jarvis" to toggle Gym Monster weight on/off.
Sends TOGGLE command to AtomS3U via BLE (Bluetooth Low Energy).
Beautiful web dashboard with real-time visualization.

Usage: python gm_jarvis.py
       Opens browser to http://localhost:8888

FechTech 2026
"""

import os
import sys
import json
import time
import struct
import asyncio
import threading
import webbrowser
import numpy as np
from http.server import HTTPServer, SimpleHTTPRequestHandler

import sounddevice as sd
import websockets.server
import openwakeword
from openwakeword.model import Model as OWWModel

try:
    from bleak import BleakClient, BleakScanner
    HAS_BLE = True
except ImportError:
    HAS_BLE = False
    print("  [WARN] bleak not installed -- BLE disabled")
    print("         Install with: pip install bleak")

# === Config ===
WAKE_WORD = "hey_jarvis_v0.1"
COOLDOWN_SECONDS = 3.0
THRESHOLD = 0.5
SAMPLE_RATE = 16000
CHUNK_SIZE = 1280

HTTP_PORT = 8888
WS_PORT = 8765

# BLE config for AtomS3U
BLE_DEVICE_NAME = "GM HID Bridge"
BLE_SERVICE_UUID = "4652454d-4f54-452d-4b42-442d53455256"
BLE_KEY_CHAR_UUID = "4652454d-4f54-452d-4b42-442d4b455953"
BLE_STATUS_CHAR_UUID = "4652454d-4f54-452d-4b42-442d53544154"

# === Shared State ===
ws_clients = set()
trigger_count = 0
last_trigger_time = 0
event_loop = None
ble_client = None
ble_connected = False
ble_loop = None  # Separate event loop for BLE


async def ble_scan_and_connect():
    """Scan for and connect to the AtomS3U BLE device."""
    global ble_client, ble_connected

    print("  [BLE] Scanning for 'GM HID Bridge'...")
    
    device = None
    for attempt in range(3):
        devices = await BleakScanner.discover(timeout=5.0)
        for d in devices:
            if d.name and BLE_DEVICE_NAME in d.name:
                device = d
                break
        if device:
            break
        print(f"  [BLE] Scan attempt {attempt + 1}/3 - not found, retrying...")

    if not device:
        print("  [BLE] AtomS3U not found!")
        print("  [BLE] Make sure it's powered on and advertising.")
        return False

    print(f"  [BLE] Found: {device.name} ({device.address})")

    try:
        ble_client = BleakClient(device.address, timeout=10.0)
        await ble_client.connect()
        ble_connected = True
        print(f"  [BLE] Connected to AtomS3U!")
        
        # Subscribe to status notifications
        async def status_callback(sender, data):
            status_map = {0: "IDLE", 1: "CONNECTED", 2: "SENDING"}
            status = data[0] if data else 0
            status_name = status_map.get(status, f"UNKNOWN({status})")
            schedule_broadcast({"type": "esp_status", "status": status_name})
        
        await ble_client.start_notify(BLE_STATUS_CHAR_UUID, status_callback)
        return True

    except Exception as e:
        print(f"  [BLE] Connection failed: {e}")
        ble_client = None
        ble_connected = False
        return False


async def ble_send_toggle():
    """Send quick toggle command via BLE."""
    global ble_client, ble_connected

    if not ble_client or not ble_connected:
        print("  [BLE] Not connected -- skipping toggle")
        return False

    try:
        # Quick toggle: single byte 0x01
        await ble_client.write_gatt_char(BLE_KEY_CHAR_UUID, bytes([0x01]), response=False)
        return True
    except Exception as e:
        print(f"  [BLE] Send failed: {e}")
        ble_connected = False
        # Try reconnecting in background
        threading.Thread(target=ble_reconnect_thread, daemon=True).start()
        return False


def ble_reconnect_thread():
    """Reconnect BLE in background."""
    global ble_connected
    time.sleep(2)
    print("  [BLE] Attempting reconnect...")
    if ble_loop:
        future = asyncio.run_coroutine_threadsafe(ble_scan_and_connect(), ble_loop)
        try:
            future.result(timeout=20)
        except Exception as e:
            print(f"  [BLE] Reconnect failed: {e}")


def send_toggle():
    """Thread-safe toggle send via BLE."""
    if ble_loop:
        future = asyncio.run_coroutine_threadsafe(ble_send_toggle(), ble_loop)
        try:
            return future.result(timeout=5)
        except Exception:
            return False
    return False


def run_ble_loop():
    """Run BLE event loop in its own thread. Retries forever until connected."""
    global ble_loop
    ble_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ble_loop)
    
    # Keep trying to connect (Bluetooth may not be ready at boot)
    async def connect_with_retry():
        while True:
            try:
                success = await ble_scan_and_connect()
                if success:
                    return
            except Exception as e:
                print(f"  [BLE] Error: {e}", flush=True)
            print("  [BLE] Retrying in 10s...", flush=True)
            await asyncio.sleep(10)
    
    ble_loop.run_until_complete(connect_with_retry())
    
    # Keep the loop running for future commands
    ble_loop.run_forever()


async def ws_broadcast(message):
    """Send to all WS clients."""
    if not ws_clients:
        return
    data = json.dumps(message)
    for client in list(ws_clients):
        try:
            await client.send(data)
        except Exception:
            ws_clients.discard(client)


async def ws_handler(websocket):
    ws_clients.add(websocket)
    print(f"  [WS] Client connected ({len(ws_clients)})")
    # Send current BLE status
    await websocket.send(json.dumps({
        "type": "serial_status",
        "connected": ble_connected,
    }))
    try:
        async for _ in websocket:
            pass
    except Exception:
        pass
    finally:
        ws_clients.discard(websocket)
        print(f"  [WS] Client disconnected ({len(ws_clients)})")


def run_http_server():
    web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

    class QuietHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=web_dir, **kwargs)
        def log_message(self, format, *args):
            pass

    httpd = HTTPServer(("0.0.0.0", HTTP_PORT), QuietHandler)
    httpd.serve_forever()


def schedule_broadcast(msg):
    """Thread-safe way to schedule a broadcast on the event loop."""
    if event_loop and event_loop.is_running():
        asyncio.run_coroutine_threadsafe(ws_broadcast(msg), event_loop)


def run_audio_detector():
    """Audio detection in its own thread."""
    global trigger_count, last_trigger_time

    # Load model
    print("  Loading wake word model...", flush=True)
    try:
        # OWW 0.4+ (Trixie): wakeword_model_paths works
        model_paths = [p for p in openwakeword.get_pretrained_model_paths() if "hey_jarvis" in p]
        if model_paths:
            # Prefer ONNX over tflite for ARM compatibility
            onnx = [p for p in model_paths if p.endswith(".onnx")]
            chosen = onnx if onnx else model_paths
            try:
                oww = OWWModel(wakeword_models=chosen, inference_framework="onnx")
            except TypeError:
                oww = OWWModel(wakeword_model_paths=chosen)
        else:
            oww = OWWModel(wakeword_models=[WAKE_WORD])
    except Exception:
        oww = OWWModel(wakeword_models=[WAKE_WORD])
    print("  Model ready!", flush=True)

    # Wait for microphone
    while True:
        try:
            default_dev = sd.default.device[0]
            if default_dev < 0:
                raise RuntimeError("No input device")
            device_info = sd.query_devices(default_dev)
            print(f"  Mic: {device_info['name']}", flush=True)
            break
        except Exception:
            print("  [MIC] No microphone found, retrying in 5s...", flush=True)
            time.sleep(5)
            sd._terminate()
            sd._initialize()

    print(f"  Wake word: \"{WAKE_WORD}\"", flush=True)
    print(f"  Threshold: {THRESHOLD}", flush=True)
    print("-" * 55, flush=True)
    print(f'  Say "HEY JARVIS" to toggle!\n', flush=True)

    # Broadcast BLE status to dashboard
    schedule_broadcast({
        "type": "serial_status",
        "connected": ble_connected,
    })

    # Find USB mic device explicitly and try 16kHz
    mic_idx = None
    for i, d in enumerate(sd.query_devices()):
        if d['max_input_channels'] > 0 and 'USB' in d['name']:
            mic_idx = i
            break

    mic_rate = SAMPLE_RATE
    resample = False
    open_kwargs = dict(samplerate=SAMPLE_RATE, channels=1, blocksize=CHUNK_SIZE, dtype='int16')
    if mic_idx is not None:
        open_kwargs['device'] = mic_idx
    try:
        test = sd.InputStream(**open_kwargs)
        test.close()
    except sd.PortAudioError:
        mic_rate = int(device_info.get('default_samplerate', 48000))
        resample = True
        open_kwargs['samplerate'] = mic_rate
        open_kwargs['blocksize'] = int(CHUNK_SIZE * mic_rate / SAMPLE_RATE)
        print(f"  [MIC] 16kHz not supported, using {mic_rate}Hz + resample", flush=True)

    chunk = open_kwargs['blocksize']

    with sd.InputStream(**open_kwargs) as stream:
        while True:
            audio, _ = stream.read(chunk)
            audio_flat = audio.flatten().astype(np.int16)

            # Resample to 16kHz if needed (proper linear interpolation)
            if resample:
                target_len = int(len(audio_flat) * SAMPLE_RATE / mic_rate)
                x_old = np.linspace(0, 1, len(audio_flat))
                x_new = np.linspace(0, 1, target_len)
                audio_flat = np.interp(x_new, x_old, audio_flat).astype(np.int16)

            prediction = oww.predict(audio_flat)

            for name, score in prediction.items():
                if score > 0.01:
                    schedule_broadcast({
                        "type": "confidence",
                        "score": round(float(score), 4),
                    })

                if score > THRESHOLD:
                    now = time.time()
                    if now - last_trigger_time > COOLDOWN_SECONDS:
                        last_trigger_time = now
                        trigger_count += 1
                        ts = time.strftime('%H:%M:%S')

                        print(f"  >>> WEIGHT TOGGLE #{trigger_count}! "
                              f"(conf: {score:.2f}) [{ts}] <<<", flush=True)

                        # Send to AtomS3U via BLE
                        sent = send_toggle()

                        if sent:
                            print(f"  [BLE] Toggle sent!", flush=True)
                        else:
                            print(f"  [BLE] Toggle FAILED!", flush=True)

                        schedule_broadcast({
                            "type": "trigger",
                            "count": trigger_count,
                            "confidence": round(float(score), 4),
                            "time": ts,
                            "serial_sent": sent,
                        })

                        oww.reset()


async def main():
    global event_loop
    event_loop = asyncio.get_event_loop()

    os.system('cls' if os.name == 'nt' else 'clear')

    print("=" * 55)
    print("  GM VOICE CONTROL  --  GYM MONSTER")
    print("  Powered by OpenWakeWord + AtomS3U BLE")
    print("=" * 55)
    print()

    # Start BLE connection in its own thread
    if HAS_BLE:
        ble_thread = threading.Thread(target=run_ble_loop, daemon=True)
        ble_thread.start()
        # Give BLE time to connect before starting audio
        time.sleep(8)
    else:
        print("  [BLE] Disabled -- install bleak")
    print()

    # HTTP server thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()
    print(f"  [HTTP] Dashboard on http://localhost:{HTTP_PORT}")

    # WebSocket server
    ws_server = await websockets.server.serve(ws_handler, "0.0.0.0", WS_PORT)
    print(f"  [WS]   WebSocket on port {WS_PORT}")
    print()

    # Audio detector thread
    audio_thread = threading.Thread(target=run_audio_detector, daemon=True)
    audio_thread.start()

    # Open browser
    webbrowser.open(f"http://localhost:{HTTP_PORT}")

    # Keep running
    await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n  Stopped. {trigger_count} triggers total.")
        if ble_client:
            print("  [BLE] Disconnecting...")
