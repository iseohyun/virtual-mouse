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
| **Zadig** | 2.9 | GPL-3.0 | https://github.com/pbatard/libwdi | Optional manual WinUSB driver installer (`scripts/setup.ps1` downloads it, not bundled) |

## WinUSB driver installer (bundled in `VirtualMouse-Agent.exe`)

| Component | Version | License | Source | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **libwdi** (`wdi-simple` example + library) | 1.5.1 (commit `9b23b82a2dd1cbffc16d46c212f92c6bf8c0c602`) | LGPL-3.0-or-later | https://github.com/pbatard/libwdi | `wdi-simple.exe`, built from source by `scripts/build_wdi.ps1`; run with UAC only when the user asks to install the DFU WinUSB driver |
| **Microsoft Windows Driver Frameworks 1.11 co-installers** (`WdfCoInstaller01011.dll` 1.11.9200.16384, `winusbcoinstaller2.dll` 6.1.7600.16385, x64) | WDK 8 redistributables | Microsoft Software License Terms (Distributable Code) | https://go.microsoft.com/fwlink/p/?LinkID=253170 | Embedded unmodified in `wdi-simple.exe` and copied into the generated WinUSB driver package |
| **MinGW-w64 runtime** | 14.0.0 | ZPL-2.1 and other permissive licenses (see notice file) | https://github.com/mingw-w64/mingw-w64 | Statically linked into `wdi-simple.exe` |
| **libgcc** (GCC runtime) | 16.2.0 | GPL-3.0 with GCC Runtime Library Exception | https://gcc.gnu.org/ | Statically linked into `wdi-simple.exe` |

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
| **WinLibs MinGW-w64 GCC** | GCC 16.2.0, MinGW-w64 14.0.0 UCRT r3 | GPL-3.0 (compiler), runtime as listed above | https://github.com/brechtsanders/winlibs_mingw | Compiler for `wdi-simple.exe` (`scripts/build_wdi.ps1`, pinned by SHA-256) |

## Note on `dfu-programmer` (GPL-2.0)
`VirtualMouse-Agent.exe` invokes `dfu-programmer.exe` as an unmodified external subprocess binary.
Full source code and license text for `dfu-programmer` v1.1.0 are available at:
https://github.com/dfu-programmer/dfu-programmer/releases/tag/v1.1.0

## Note on `wdi-simple` / libwdi (LGPL-3.0-or-later)
`VirtualMouse-Agent.exe` runs `wdi-simple.exe` as a separate program (it is not linked into the agent).
`wdi-simple.exe` is built without source changes from libwdi v1.5.1 by `scripts/build_wdi.ps1`
(MinGW-w64, x86_64 only, WinUSB only). The build is reproducible: the same pinned inputs give the same file,
whose SHA-256 is pinned in the script.

- Corresponding source: the exact upstream source archive (`libwdi-9b23b82a2dd1cbffc16d46c212f92c6bf8c0c602.tar.gz`)
  is attached to every GitHub Release that contains the agent, and the build script is in this repository.
- License texts and build details are bundled next to `wdi-simple.exe` inside the agent
  (`COPYING`, `COPYING-LGPL`, `WDF-License.rtf`, `COPYING.MinGW-w64-runtime.txt`, `BUILD-INFO.txt`).
- To use a modified libwdi, change and rerun `scripts/build_wdi.ps1`, then rebuild the agent with `scripts/build_agent.ps1`.

## Note on the Microsoft WinUSB co-installers
`WdfCoInstaller01011.dll` and `winusbcoinstaller2.dll` (x64) come from Microsoft's Windows Driver Kit 8
redistributable package (`wdfcoinstaller.msi`), where they are listed in `redist.txt` as Distributable Code.
They are redistributed unmodified, with their Microsoft signatures, under the Microsoft Software License Terms
for Windows Driver Frameworks 1.11 (`WDF-License.rtf`, bundled next to `wdi-simple.exe`).
Use of these files is subject to those terms. They are only needed by Windows 7/8; on Windows 10/11 WinUSB and
KMDF are part of Windows, but the driver package that libwdi generates still references them.

## Note on `pystray` (LGPL-3.0)
`pystray` is used unmodified as a separate Python package inside the PyInstaller bundle.
Its source code is available at https://github.com/moses-palmer/pystray (tag `v0.19.5`).
Users may replace it by rebuilding the agent from this repository with `scripts/build_agent.ps1`.
