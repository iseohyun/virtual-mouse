/*
 * VirtualMouse - Arduino Uno R3 (ATmega16U2) USB HID Mouse + Keyboard Firmware v1.1.0
 *
 * Protocol (115200 baud, newline '\n' terminated):
 *   PING         -> PONG
 *   VER          -> VMOUSE 1.1.0
 *   M <dx> <dy>  -> Relative mouse move (int16, auto-chunked into -127..127)
 *   C <L|R|M>    -> Mouse click (Left / Right / Middle)
 *   P <L|R|M>    -> Mouse press
 *   R <L|R|M>    -> Mouse release
 *   W <delta>    -> Mouse wheel scroll (-127..127)
 *   KP <code>    -> Keyboard press (uint8 Arduino/ASCII keycode)
 *   KR <code>    -> Keyboard release (uint8 Arduino/ASCII keycode)
 *   KT <code>    -> Keyboard tap/write single keycode
 *   KW <text>    -> Keyboard write raw ASCII text
 *   KA           -> Keyboard release all keys
 *   X            -> Emergency release all mouse buttons & keyboard keys
 *   BOOT         -> Jump to ATmega16U2 DFU bootloader (0x3000 byte / 0x1800 word)
 */

#include <HID-Project.h>
#include <avr/interrupt.h>
#include <avr/wdt.h>

#define FW_VERSION "1.1.0"

static char cmdBuf[48];
static uint8_t cmdIdx = 0;

static uint8_t parseButton(char c) {
  switch (c) {
    case 'L': case 'l': return MOUSE_LEFT;
    case 'R': case 'r': return MOUSE_RIGHT;
    case 'M': case 'm': return MOUSE_MIDDLE;
    default: return 0;
  }
}

static int16_t parseInt16(const char* p, const char** nextOut) {
  while (*p == ' ' || *p == '\t') p++;
  bool neg = false;
  if (*p == '-') {
    neg = true;
    p++;
  } else if (*p == '+') {
    p++;
  }
  int16_t val = 0;
  while (*p >= '0' && *p <= '9') {
    val = (int16_t)(val * 10 + (*p - '0'));
    p++;
  }
  if (nextOut) *nextOut = p;
  return neg ? (int16_t)(-val) : val;
}

static void moveRelative(int16_t dx, int16_t dy) {
  while (dx != 0 || dy != 0) {
    int8_t stepX = (dx > 127) ? 127 : (dx < -127 ? -127 : (int8_t)dx);
    int8_t stepY = (dy > 127) ? 127 : (dy < -127 ? -127 : (int8_t)dy);
    Mouse.move(stepX, stepY, 0);
    dx -= stepX;
    dy -= stepY;
  }
}

static void jumpToDfuBootloader() {
  Mouse.releaseAll();
  Keyboard.releaseAll();
  Serial.println(F("BOOTING"));
  Serial.flush();
  delay(80);

  cli();
  // Detach USB and disable interrupts/timers before jumping to Atmel DFU bootloader
  UDCON = 1;
  USBCON = (1 << FRZCLK);
  UCSR1B = 0;
  TCCR0B = 0;
  TCCR1B = 0;
  TIMSK0 = 0;
  TIMSK1 = 0;
  wdt_disable();

  // Brief busy wait so host sees USB disconnect cleanly
  for (volatile uint32_t i = 0; i < 80000UL; i++) {
    __asm__ __volatile__("nop");
  }

  // ATmega16U2 DFU bootloader sits at byte address 0x3000 (word address 0x1800)
  ((void (*)(void))0x1800)();
}

static void handleCommand(const char* line) {
  while (*line == ' ' || *line == '\t') line++;
  if (*line == '\0') return;

  char cmd = line[0];

  if (cmd == 'P' && line[1] == 'I' && line[2] == 'N' && line[3] == 'G') {
    Serial.println(F("PONG"));
    return;
  }
  if (cmd == 'V' && line[1] == 'E' && line[2] == 'R') {
    Serial.println(F("VMOUSE " FW_VERSION));
    return;
  }
  if (cmd == 'B' && line[1] == 'O' && line[2] == 'O' && line[3] == 'T') {
    jumpToDfuBootloader();
    return;
  }

  if (cmd == 'K') {
    char sub = line[1];
    const char* p = line + 2;
    if (sub == 'P') {
      uint8_t code = (uint8_t)parseInt16(p, &p);
      Keyboard.press(KeyboardKeycode(code));
      Serial.println(F("OK"));
    } else if (sub == 'R') {
      uint8_t code = (uint8_t)parseInt16(p, &p);
      Keyboard.release(KeyboardKeycode(code));
      Serial.println(F("OK"));
    } else if (sub == 'T') {
      uint8_t code = (uint8_t)parseInt16(p, &p);
      Keyboard.write(KeyboardKeycode(code));
      Serial.println(F("OK"));
    } else if (sub == 'W') {
      if (*p == ' ') p++;
      Keyboard.print(p);
      Serial.println(F("OK"));
    } else if (sub == 'A') {
      Keyboard.releaseAll();
      Serial.println(F("OK"));
    } else {
      Serial.println(F("ERR"));
    }
    return;
  }

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
      uint8_t btn = parseButton(*p);
      if (btn) {
        Mouse.click(btn);
        Serial.println(F("OK"));
      } else {
        Serial.println(F("ERR"));
      }
      break;
    }
    case 'P': {
      const char* p = line + 1;
      while (*p == ' ' || *p == '\t') p++;
      uint8_t btn = parseButton(*p);
      if (btn) {
        Mouse.press(btn);
        Serial.println(F("OK"));
      } else {
        Serial.println(F("ERR"));
      }
      break;
    }
    case 'R': {
      const char* p = line + 1;
      while (*p == ' ' || *p == '\t') p++;
      uint8_t btn = parseButton(*p);
      if (btn) {
        Mouse.release(btn);
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
      Mouse.move(0, 0, (int8_t)delta);
      Serial.println(F("OK"));
      break;
    }
    case 'X': {
      Mouse.releaseAll();
      Keyboard.releaseAll();
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
  Mouse.begin();
  Keyboard.begin();
}

void loop() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      cmdBuf[cmdIdx] = '\0';
      handleCommand(cmdBuf);
      cmdIdx = 0;
    } else if (cmdIdx < sizeof(cmdBuf) - 1) {
      cmdBuf[cmdIdx++] = c;
    }
  }
}
