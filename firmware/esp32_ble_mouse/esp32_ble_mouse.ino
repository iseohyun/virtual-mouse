/*
 * VirtualMouse - ESP32 BLE HID Mouse Firmware v1.0.0
 *
 * Target: ESP32-D0WD-V3 (Standard ESP32 DevKit, 4MB Flash, esp32:esp32 4.x built-in BLE.h)
 * BLE Device Name: "VirtualMouse BLE"
 *
 * Serial protocol (115200 baud, '\n' terminated):
 *   PING        -> PONG
 *   VER         -> VMOUSE_ESP32 1.0.0
 *   BLE         -> CONNECTED | ADVERTISING
 *   M <dx> <dy> -> Relative move (int16, auto-chunked into -127..127)
 *   C <L|R|M>   -> Click (Left / Right / Middle)
 *   P <L|R|M>   -> Press button
 *   R <L|R|M>   -> Release button
 *   W <delta>   -> Scroll wheel (-127..127)
 *   X           -> Emergency release all buttons
 *   DEMO        -> Move cursor in a small square once
 * Onboard BOOT button (GPIO 0): Press once when paired to run square DEMO.
 */

#include <Arduino.h>
#include <BLE.h>

#define FW_VERSION "1.0.0"
#define BLE_DEVICE_NAME "VirtualMouse BLE"
#define BOOT_BTN_PIN 0

// Standard 5-button + X/Y + Wheel HID Mouse Report Descriptor (Report ID 1)
static const uint8_t MOUSE_REPORT_MAP[] = {
  0x05, 0x01,       // USAGE_PAGE (Generic Desktop)
  0x09, 0x02,       // USAGE (Mouse)
  0xA1, 0x01,       // COLLECTION (Application)
  0x85, 0x01,       //   REPORT_ID (1)
  0x09, 0x01,       //   USAGE (Pointer)
  0xA1, 0x00,       //   COLLECTION (Physical)
  0x05, 0x09,       //     USAGE_PAGE (Button)
  0x19, 0x01,       //     USAGE_MINIMUM (Button 1)
  0x29, 0x05,       //     USAGE_MAXIMUM (Button 5)
  0x15, 0x00,       //     LOGICAL_MINIMUM (0)
  0x25, 0x01,       //     LOGICAL_MAXIMUM (1)
  0x95, 0x05,       //     REPORT_COUNT (5)
  0x75, 0x01,       //     REPORT_SIZE (1)
  0x81, 0x02,       //     INPUT (Data,Var,Abs)
  0x95, 0x01,       //     REPORT_COUNT (1)
  0x75, 0x03,       //     REPORT_SIZE (3)
  0x81, 0x03,       //     INPUT (Cnst,Var,Abs) - padding
  0x05, 0x01,       //     USAGE_PAGE (Generic Desktop)
  0x09, 0x30,       //     USAGE (X)
  0x09, 0x31,       //     USAGE (Y)
  0x09, 0x38,       //     USAGE (Wheel)
  0x15, 0x81,       //     LOGICAL_MINIMUM (-127)
  0x25, 0x7F,       //     LOGICAL_MAXIMUM (127)
  0x75, 0x08,       //     REPORT_SIZE (8)
  0x95, 0x03,       //     REPORT_COUNT (3)
  0x81, 0x06,       //     INPUT (Data,Var,Rel)
  0xC0,             //   END_COLLECTION
  0xC0              // END_COLLECTION
};

static BLEHIDDevice* hid = nullptr;
static BLECharacteristic inputMouse;
static volatile bool bleConnected = false;
static uint8_t currentButtons = 0;

static char cmdBuf[64];
static uint8_t cmdIdx = 0;
static uint32_t lastBtnMs = 0;

static void sendMouseReport(uint8_t buttons, int8_t dx, int8_t dy, int8_t wheel) {
  if (!bleConnected || !inputMouse) return;
  uint8_t report[4] = {
    buttons,
    static_cast<uint8_t>(dx),
    static_cast<uint8_t>(dy),
    static_cast<uint8_t>(wheel)
  };
  inputMouse.setValue(report, sizeof(report));
  inputMouse.notify();
}

static uint8_t parseButtonMask(char c) {
  switch (c) {
    case 'L': case 'l': return 0x01;
    case 'R': case 'r': return 0x02;
    case 'M': case 'm': return 0x04;
    default: return 0x00;
  }
}

static int16_t parseInt16(const char* p, const char** nextOut) {
  while (*p == ' ' || *p == '\t') p++;
  bool neg = false;
  if (*p == '-') { neg = true; p++; }
  else if (*p == '+') { p++; }
  int16_t val = 0;
  while (*p >= '0' && *p <= '9') {
    val = static_cast<int16_t>(val * 10 + (*p - '0'));
    p++;
  }
  if (nextOut) *nextOut = p;
  return neg ? static_cast<int16_t>(-val) : val;
}

static void moveRelative(int16_t dx, int16_t dy) {
  while (dx != 0 || dy != 0) {
    int8_t stepX = (dx > 127) ? 127 : (dx < -127 ? -127 : static_cast<int8_t>(dx));
    int8_t stepY = (dy > 127) ? 127 : (dy < -127 ? -127 : static_cast<int8_t>(dy));
    sendMouseReport(currentButtons, stepX, stepY, 0);
    dx -= stepX;
    dy -= stepY;
    if (dx != 0 || dy != 0) delay(6);
  }
}

static void runSquareDemo() {
  if (!bleConnected) {
    Serial.println(F("ERR_NOT_CONNECTED"));
    return;
  }
  const int16_t dirs[4][2] = { {80, 0}, {0, 80}, {-80, 0}, {0, -80} };
  for (int d = 0; d < 4; d++) {
    for (int s = 0; s < 10; s++) {
      moveRelative(dirs[d][0] / 10, dirs[d][1] / 10);
      delay(15);
    }
    delay(80);
  }
}

static void handleCommand(const char* line) {
  while (*line == ' ' || *line == '\t') line++;
  if (*line == '\0') return;

  if (strncmp(line, "PING", 4) == 0) {
    Serial.println(F("PONG"));
    return;
  }
  if (strncmp(line, "VER", 3) == 0) {
    Serial.println(F("VMOUSE_ESP32 " FW_VERSION));
    return;
  }
  if (strncmp(line, "BLE", 3) == 0) {
    Serial.println(bleConnected ? F("CONNECTED") : F("ADVERTISING"));
    return;
  }
  if (strncmp(line, "DEMO", 4) == 0) {
    runSquareDemo();
    Serial.println(F("OK"));
    return;
  }

  char cmd = line[0];
  switch (cmd) {
    case 'M': {
      const char* p = line + 1;
      int16_t dx = parseInt16(p, &p);
      int16_t dy = parseInt16(p, &p);
      moveRelative(dx, dy);
      Serial.println(F("OK"));
      break;
    }
    case 'C': {
      const char* p = line + 1;
      while (*p == ' ' || *p == '\t') p++;
      uint8_t mask = parseButtonMask(*p);
      if (mask) {
        sendMouseReport(currentButtons | mask, 0, 0, 0);
        delay(55);
        sendMouseReport(currentButtons & ~mask, 0, 0, 0);
        Serial.println(F("OK"));
      } else {
        Serial.println(F("ERR"));
      }
      break;
    }
    case 'P': {
      const char* p = line + 1;
      while (*p == ' ' || *p == '\t') p++;
      uint8_t mask = parseButtonMask(*p);
      if (mask) {
        currentButtons |= mask;
        sendMouseReport(currentButtons, 0, 0, 0);
        Serial.println(F("OK"));
      } else {
        Serial.println(F("ERR"));
      }
      break;
    }
    case 'R': {
      const char* p = line + 1;
      while (*p == ' ' || *p == '\t') p++;
      uint8_t mask = parseButtonMask(*p);
      if (mask) {
        currentButtons &= ~mask;
        sendMouseReport(currentButtons, 0, 0, 0);
        Serial.println(F("OK"));
      } else {
        Serial.println(F("ERR"));
      }
      break;
    }
    case 'W': {
      const char* p = line + 1;
      int16_t delta = parseInt16(p, &p);
      if (delta > 127) delta = 127;
      if (delta < -127) delta = -127;
      sendMouseReport(currentButtons, 0, 0, static_cast<int8_t>(delta));
      Serial.println(F("OK"));
      break;
    }
    case 'X': {
      currentButtons = 0;
      sendMouseReport(0, 0, 0, 0);
      Serial.println(F("OK"));
      break;
    }
    default:
      Serial.println(F("ERR"));
      break;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BOOT_BTN_PIN, INPUT_PULLUP);

  BLE.begin(BLE_DEVICE_NAME);

  BLESecurity sec = BLE.getSecurity();
  sec.setAuthenticationMode(true, false, true);

  BLEServer server = BLE.createServer();
  server.advertiseOnDisconnect(true);
  server.onConnect([](BLEServer& s, const BLEConnInfo& conn) {
    bleConnected = true;
    Serial.println(F("[BLE] CONNECTED"));
  });
  server.onDisconnect([](BLEServer& s, const BLEConnInfo& conn, uint8_t reason) {
    bleConnected = false;
    currentButtons = 0;
    Serial.println(F("[BLE] DISCONNECTED - advertising restarted"));
  });

  hid = new BLEHIDDevice(server);
  inputMouse = hid->inputReport(1);
  hid->manufacturer("VirtualMouse");
  hid->pnp(0x02, 0x05AC, 0x820A, 0x0210);
  hid->hidInfo(0x00, 0x02);
  hid->reportMap(MOUSE_REPORT_MAP, sizeof(MOUSE_REPORT_MAP));
  hid->setBatteryLevel(100);

  server.start();

  BLEAdvertising adv = BLE.getAdvertising();
  adv.setAppearance(0x03C2);  // HID Mouse
  adv.setName(BLE_DEVICE_NAME);
  adv.setScanResponse(true);
  adv.start();

  Serial.println(F("[READY] VirtualMouse BLE advertising..."));
}

void loop() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\r') continue;
    if (c == '\n') {
      cmdBuf[cmdIdx] = '\0';
      handleCommand(cmdBuf);
      cmdIdx = 0;
    } else if (cmdIdx < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdIdx++] = c;
    }
  }

  // Onboard BOOT button (GPIO 0): trigger a quick square demo move when connected
  if (digitalRead(BOOT_BTN_PIN) == LOW && (millis() - lastBtnMs > 1200)) {
    lastBtnMs = millis();
    if (bleConnected) {
      Serial.println(F("[BTN] Running square demo..."));
      runSquareDemo();
    } else {
      Serial.println(F("[BTN] Not paired yet (ADVERTISING)"));
    }
  }
}
