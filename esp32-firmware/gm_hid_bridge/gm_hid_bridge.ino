/**
 * GM HID Bridge — ESP32-S3 Firmware (Production)
 * 
 * AtomS3U plugged into Gym Monster USB-A port:
 *   - USB HID Keyboard → sends LEFT arrow to Gym Monster
 *   - BLE GATT Server  → receives TOGGLE commands from PC/Phone
 * 
 * BLE Protocol (4 bytes per command):
 *   [0] = 0x01 (Key Press command)
 *   [1] = HID keycode
 *   [2] = Repeat count (1–50)
 *   [3] = Delay between presses in 10ms units
 * 
 * Quick command: Write single byte 0x01 → default toggle (LEFT arrow x1)
 * 
 * Build: USBMode=default (TinyUSB), CDCOnBoot=default
 * 
 * Hardware: M5Stack AtomS3U (ESP32-S3, USB-A male)
 * FechTech 2026
 */

#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "USB.h"
#include "USBHIDKeyboard.h"

// ============================================================
// BLE UUIDs
// ============================================================
#define SERVICE_UUID        "4652454d-4f54-452d-4b42-442d53455256"
#define KEY_CHAR_UUID       "4652454d-4f54-452d-4b42-442d4b455953"
#define STATUS_CHAR_UUID    "4652454d-4f54-452d-4b42-442d53544154"

// ============================================================
// Configuration
// ============================================================
#define DEVICE_NAME         "GM HID Bridge"
#define KEY_HOLD_MS         80     // How long to hold key down
#define DEFAULT_DELAY_UNITS 25     // 25 * 10ms = 250ms between keys
#define DEFAULT_TOGGLE_KEY  0x50   // LEFT Arrow — Gym Monster weight on/off

// Status codes
#define STATUS_IDLE         0x00
#define STATUS_CONNECTED    0x01
#define STATUS_SENDING      0x02

// ============================================================
// Globals
// ============================================================
USBHIDKeyboard Keyboard;
BLEServer* pServer = nullptr;
BLECharacteristic* pKeyChar = nullptr;
BLECharacteristic* pStatusChar = nullptr;

bool bleConnected = false;
bool wasBleConnected = false;
uint32_t totalToggles = 0;

// Forward declarations
void sendStatus(uint8_t status);
void sendHidKey(uint8_t keycode);
void executeToggle(uint8_t keycode, uint8_t count, uint16_t delayMs);

// ============================================================
// BLE Server Callbacks
// ============================================================
class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer* server) override {
    bleConnected = true;
    Serial.println("[BLE] Client connected");
    sendStatus(STATUS_CONNECTED);
  }

  void onDisconnect(BLEServer* server) override {
    bleConnected = false;
    Serial.println("[BLE] Client disconnected");
    sendStatus(STATUS_IDLE);
    BLEDevice::startAdvertising();
    Serial.println("[BLE] Re-advertising...");
  }
};

// ============================================================
// Key Characteristic Write Callback
// ============================================================
class KeyCharCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* pChar) override {
    String value = pChar->getValue();
    
    if (value.length() == 0) return;

    // Quick toggle: single byte 0x01
    if (value.length() == 1 && value[0] == 0x01) {
      Serial.println("[BLE] Quick toggle!");
      executeToggle(DEFAULT_TOGGLE_KEY, 1, 0);
      return;
    }

    // Full command: [type, keycode, param1, param2]
    if (value.length() >= 2) {
      uint8_t cmdType = value[0];
      uint8_t keycode = value[1];

      switch (cmdType) {
        case 0x01: {
          // Standard press: [0x01, keycode, count, delay_10ms]
          uint8_t count = (value.length() >= 3) ? value[2] : 1;
          uint8_t delayUnits = (value.length() >= 4) ? value[3] : DEFAULT_DELAY_UNITS;
          if (count == 0 || count > 50) count = 1;
          uint16_t delayMs = (uint16_t)delayUnits * 10;
          executeToggle(keycode, count, delayMs);
          break;
        }
        case 0x02: {
          // Long press: [0x02, keycode, hold_100ms]
          // Hold key down for (hold_100ms * 100) milliseconds
          uint8_t holdUnits = (value.length() >= 3) ? value[2] : 10;  // default 1 second
          uint16_t holdMs = (uint16_t)holdUnits * 100;
          if (holdMs > 15000) holdMs = 15000;  // max 15 seconds
          Serial.printf("[LONG PRESS] Key=0x%02X hold=%dms\n", keycode, holdMs);
          sendStatus(STATUS_SENDING);
          totalToggles++;
          
          uint8_t report[8] = {0};
          report[2] = keycode;
          Keyboard.sendReport((KeyReport*)report);  // Key Down
          delay(holdMs);                              // Hold!
          memset(report, 0, sizeof(report));
          Keyboard.sendReport((KeyReport*)report);   // Key Up
          delay(20);
          
          sendStatus(bleConnected ? STATUS_CONNECTED : STATUS_IDLE);
          Serial.printf("[LONG PRESS] Done #%lu\n", totalToggles);
          break;
        }
        case 0x03: {
          // Double tap: [0x03, keycode, gap_10ms]
          uint8_t gapUnits = (value.length() >= 3) ? value[2] : 10;  // default 100ms gap
          uint16_t gapMs = (uint16_t)gapUnits * 10;
          Serial.printf("[DOUBLE TAP] Key=0x%02X gap=%dms\n", keycode, gapMs);
          sendStatus(STATUS_SENDING);
          totalToggles++;
          
          sendHidKey(keycode);
          delay(gapMs);
          sendHidKey(keycode);
          
          sendStatus(bleConnected ? STATUS_CONNECTED : STATUS_IDLE);
          Serial.printf("[DOUBLE TAP] Done #%lu\n", totalToggles);
          break;
        }
        default:
          Serial.printf("[BLE] Unknown cmd: 0x%02X\n", cmdType);
          break;
      }
    }
  }
};

// ============================================================
// Execute Toggle — send real USB HID keypress
// ============================================================
void executeToggle(uint8_t keycode, uint8_t count, uint16_t delayMs) {
  sendStatus(STATUS_SENDING);
  totalToggles++;

  Serial.printf("[TOGGLE] #%lu Key=0x%02X x%d\n", totalToggles, keycode, count);

  for (uint8_t i = 0; i < count; i++) {
    sendHidKey(keycode);
    if (i < count - 1 && delayMs > 0) {
      delay(delayMs);
    }
  }

  sendStatus(bleConnected ? STATUS_CONNECTED : STATUS_IDLE);
  Serial.printf("[TOGGLE] Done #%lu\n", totalToggles);
}

// ============================================================
// USB HID Key Send — actual keypress to Gym Monster
// ============================================================
void sendHidKey(uint8_t keycode) {
  uint8_t report[8] = {0};
  
  // Key Down
  report[2] = keycode;
  Keyboard.sendReport((KeyReport*)report);
  delay(KEY_HOLD_MS);
  
  // Key Up
  memset(report, 0, sizeof(report));
  Keyboard.sendReport((KeyReport*)report);
  delay(20);  // Small gap after release
}

// ============================================================
// BLE Status Notify
// ============================================================
void sendStatus(uint8_t status) {
  if (pStatusChar != nullptr) {
    pStatusChar->setValue(&status, 1);
    if (bleConnected) {
      pStatusChar->notify();
    }
  }
}

// ============================================================
// Setup
// ============================================================
void setup() {
  Serial.begin(115200);  // Goes to UART0 (debug only, not USB)
  delay(1000);
  
  Serial.println("\n=== GM HID Bridge ===");
  Serial.println("FechTech 2026 — Production Mode");
  Serial.println("Key: LEFT Arrow (0x50)");

  // ---- USB HID Keyboard ----
  USB.begin();
  Keyboard.begin();
  Serial.println("[USB] HID Keyboard ready");

  // ---- BLE Server ----
  BLEDevice::init(DEVICE_NAME);
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new ServerCallbacks());

  BLEService* pService = pServer->createService(SERVICE_UUID);

  pKeyChar = pService->createCharacteristic(
    KEY_CHAR_UUID,
    BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR
  );
  pKeyChar->setCallbacks(new KeyCharCallbacks());

  pStatusChar = pService->createCharacteristic(
    STATUS_CHAR_UUID,
    BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
  );
  pStatusChar->addDescriptor(new BLE2902());
  uint8_t initialStatus = STATUS_IDLE;
  pStatusChar->setValue(&initialStatus, 1);

  pService->start();

  BLEAdvertising* pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  BLEDevice::startAdvertising();

  Serial.println("[BLE] Advertising as '" DEVICE_NAME "'");
  Serial.println("[READY] Waiting for BLE connection...");
}

// ============================================================
// Loop
// ============================================================
void loop() {
  if (bleConnected != wasBleConnected) {
    wasBleConnected = bleConnected;
    Serial.printf("[LOOP] BLE %s\n", bleConnected ? "ACTIVE" : "IDLE");
  }

  // Heartbeat every 30s
  static uint32_t lastHB = 0;
  if (millis() - lastHB > 30000) {
    lastHB = millis();
    Serial.printf("[HB] BLE=%s Toggles=%lu Up=%lus\n",
      bleConnected ? "ON" : "OFF", totalToggles, millis()/1000);
  }

  delay(10);
}
