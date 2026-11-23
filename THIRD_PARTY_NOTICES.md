# Third-Party Open Source Notices

This project (`VirtualMouse`) uses or bundles the following third-party open-source components.
Each component remains governed by its respective license.

| Component | Version | License | Source | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **HoodLoader2** | 2.0.5 | MIT | https://github.com/NicoHood/HoodLoader2 | Arduino Uno `ATmega16U2` board core |
| **HID-Project** | 2.8.4 | MIT | https://github.com/NicoHood/HID | MultiReport USB HID Mouse & Keyboard firmware library |
| **ArduinoCore-avr** | 1.8.8 | LGPL-2.1 | https://github.com/arduino/ArduinoCore-avr | AVR core and stock Uno R3 16U2 recovery `.hex` |
| **pyserial** | 3.5 | BSD-3-Clause | https://github.com/pyserial/pyserial | PC ↔ Arduino COM serial communication |
| **dfu-programmer** | 1.1.0 | GPL-2.0 | https://github.com/dfu-programmer/dfu-programmer | External CLI tool invoked via subprocess for ATmega16U2 DFU flashing (bundled in `VirtualMouse-Agent.exe`) |
| **libusb** | 1.0.x | LGPL-2.1 | https://github.com/libusb/libusb | USB backend DLL (`libusb-1.0.dll`) used by `dfu-programmer` |
| **Zadig / libwdi** | 2.9 | LGPL-3.0 / GPL-3.0 | https://github.com/pbatard/libwdi | Optional Windows WinUSB driver installation helper (`scripts/setup.ps1`) |
| **PyInstaller** | 6.x | GPL-2.0 with Bootloader Exception | https://github.com/pyinstaller/pyinstaller | Packaging tool for `VirtualMouse-Agent.exe` |

## Note on `dfu-programmer` (GPL-2.0)
`VirtualMouse-Agent.exe` invokes `dfu-programmer.exe` as an unmodified external subprocess binary.
Full source code and license text for `dfu-programmer` v1.1.0 are available at:
https://github.com/dfu-programmer/dfu-programmer/releases/tag/v1.1.0
