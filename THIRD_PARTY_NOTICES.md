# Third-Party Open Source Notices

This project (`VirtualMouse`) uses or bundles the following third-party open-source components.
Each component remains governed by its respective license.

## Firmware and flashing tools

| Component | Version | License | Source | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **HoodLoader2** | 2.0.5 | MIT | https://github.com/NicoHood/HoodLoader2 | Arduino Uno `ATmega16U2` board core |
| **HID-Project** | 2.8.4 | MIT | https://github.com/NicoHood/HID | MultiReport USB HID Mouse & Keyboard firmware library |
| **ArduinoCore-avr** | 1.8.8 | LGPL-2.1 | https://github.com/arduino/ArduinoCore-avr | AVR core and stock Uno R3 16U2 recovery `.hex` |
| **dfu-programmer** | 1.1.0 | GPL-2.0 | https://github.com/dfu-programmer/dfu-programmer | External CLI tool invoked via subprocess for ATmega16U2 DFU flashing (bundled in `VirtualMouse-Agent.exe`) |
| **libusb** | 1.0.x | LGPL-2.1 | https://github.com/libusb/libusb | USB backend DLL (`libusb-1.0.dll`) used by `dfu-programmer` (bundled in `VirtualMouse-Agent.exe`) |
| **Zadig / libwdi** | 2.9 | LGPL-3.0 / GPL-3.0 | https://github.com/pbatard/libwdi | Optional Windows WinUSB driver installation helper (`scripts/setup.ps1`, not bundled) |

## Bundled in `VirtualMouse-Agent.exe` (Python runtime and packages)

| Component | Version | License | Source | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **Python** | 3.12 | PSF-2.0 | https://www.python.org/ | Interpreter runtime embedded by PyInstaller |
| **pyserial** | 3.5 | BSD-3-Clause | https://github.com/pyserial/pyserial | PC ↔ Arduino COM serial communication |
| **pystray** | 0.19.5 | LGPL-3.0 | https://github.com/moses-palmer/pystray | System tray icon and menu |
| **Pillow** | 13.0.0 | MIT-CMU (HPND) | https://github.com/python-pillow/Pillow | Tray icon image drawing |
| **six** | 1.17.0 | MIT | https://github.com/benjaminp/six | Dependency of pystray |

Pillow's Windows wheels also ship third-party libraries (for example zlib, libjpeg-turbo, libpng, FreeType);
their licenses are listed in Pillow's `LICENSE` file: https://github.com/python-pillow/Pillow/blob/main/LICENSE

## Build tools (not redistributed)

| Component | Version | License | Source | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **PyInstaller** | 6.22.3 | GPL-2.0 with Bootloader Exception | https://github.com/pyinstaller/pyinstaller | Packaging tool for `VirtualMouse-Agent.exe` (the bootloader exception allows distributing the packaged exe) |
| **arduino-cli** | 1.6.0 | GPL-3.0 | https://github.com/arduino/arduino-cli | Firmware compiler front end |

## Note on `dfu-programmer` (GPL-2.0)
`VirtualMouse-Agent.exe` invokes `dfu-programmer.exe` as an unmodified external subprocess binary.
Full source code and license text for `dfu-programmer` v1.1.0 are available at:
https://github.com/dfu-programmer/dfu-programmer/releases/tag/v1.1.0

## Note on `pystray` (LGPL-3.0)
`pystray` is used unmodified as a separate Python package inside the PyInstaller bundle.
Its source code is available at https://github.com/moses-palmer/pystray (tag `v0.19.5`).
Users may replace it by rebuilding the agent from this repository with `scripts/build_agent.ps1`.
