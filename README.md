# Prism Desktop
**A Home Assistant PC App for Windows & Linux**

Prism Desktop brings Home Assistant to your PC with a modern, lightweight desktop experience.  
It features a sleek dashboard with smooth animations, build in notifications, intuitive drag-and-drop customization, and deep integration with Home Assistant entities.


<img width="833" height="660" alt="image" src="https://github.com/user-attachments/assets/bc7028cc-89db-4de3-9805-027914573a3c" />






## Features

- **System Tray Integration**: The app stays tucked away in your tray until you need it.
- **PC notifications**: Send notifications to your PC 
- **Resizeable dashboard**: adjust the size of your dashboard according to your needs.
- **Morphing Controls**: Click and hold widgets to expand them into granular controls like dimmers or thermostats.
- **Drag & Drop Customization**: Rearrange your dashboard grid simply by dragging icons around.
- **Real-time Sync**: Uses Home Assistant's WebSocket API for instant state updates.
- **Customizable Appearance**: Choose from different border effects (like Rainbow or Aurora) and customize button colors.
- **Keyboard Shortcuts**: Create custom shortcuts for your button tiles

## Supported Entity Types
- Automation
- Camera
- Climate
- Curtain / Cover
- Fan
- Light / Switch
- Lawn Mower
- Media Controller
- Scene
- Sun
- Script
- Sensor
- Vacuum
- Weather

## 3D printer tile
- Camera
- Nozzle Temperature
- Nozzle Target Temperature
- Bed Temperature
- Bed Target Temperature
- State

## Keyboard Shortcuts
- **Open / Close App**: Use the shortcut defined in Settings under 'App toggle'.
- **Custom Shortcuts**: Define custom shortcuts for any button via the Add/Edit menu.

## Adjustable grid
![gif-grid](https://github.com/user-attachments/assets/70d9b5f6-bef0-4f86-a6e3-59790e3f5460)

## Widget overlays
![gif-overlay](https://github.com/user-attachments/assets/244bb7a7-be80-499e-a343-ec8773bb1307)



## Installation

### Windows Installer
Download the latest `PrismDesktopSetup.exe` from the Releases page. This will install the app and optionally set it to start with Windows.

### Linux Installer
Download the latest `.AppImage` from the Releases page.

1. Make it executable:
   ```bash
   chmod +x PrismDesktop-x86_64.AppImage
   ```
2. Run it:
   ```bash
   ./PrismDesktop-x86_64.AppImage
   ```

> **Note:** Some distributions (e.g. Ubuntu 22.04+) require `libfuse2` for AppImages to run:
> ```bash
> sudo apt install libfuse2
> ```

**GNOME:**
- Install `AppIndicator and KStatusNotifierItem Support` through `Extension Manager` for system tray support.
- Wayland: GNOME has limited global shortcut support. As a workaround, you can bind the following command to a custom keyboard shortcut in your system settings to toggle the app:
  ```bash
  /path/to/PrismDesktop-x86_64.AppImage --toggle
  ```
  Binding shortcuts to individual entities is not supported.

**KDE:**
- System tray works out of the box.
- The app-toggle shortcut works via `org.freedesktop.portal.GlobalShortcuts`.
- Binding shortcuts to individual entities is not supported on KDE.

### Manual / Portable
You can also download the standalone `.exe` if you prefer not to install anything. Just run it, and it will create a configuration file in the same directory.

## Running from Source

If you want to modify the code or run it manually:

1. Clone this repository.
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python main.py
   ```

## Configuration

Upon first launch, you will be asked for your Home Assistant URL and a Long-Lived Access Token. You can generate this token in your Home Assistant profile settings.

<img width="617" height="941" alt="image" src="https://github.com/user-attachments/assets/36309cb4-a316-4469-87a0-5d1ee68f22d2" />







## Building

### Windows
To build the executable yourself, run the included build script:

```bash
python build_exe.py
```

This will run PyInstaller and generate a single-file executable in the `dist` folder.

To build the installer, open `setup.iss` with [Inno Setup](https://jrsoftware.org/isdl.php) and compile it.

### Linux (AppImage)
1. Download `appimagetool-x86_64.AppImage` from the [appimagetool releases](https://github.com/AppImage/appimagetool/releases) and place it in the project folder.
2. Run the build script:

```bash
python3 build_linux.py
```

This will build the binary, create an AppDir, and package it into an AppImage.

## License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
