# BitChat - BLE Chat Application

A simple terminal-based Bluetooth Low Energy (BLE) chat application that allows two devices to discover and connect to each other for local messaging without WiFi or internet connectivity.

## Features

- **Peer-to-peer communication**: No server required - two clients connect directly
- **Dual mode operation**: Each instance can both advertise (peripheral) and connect (central)
- **Terminal interface**: Simple command-line interface for chatting
- **Local only**: All communication happens over Bluetooth LE, no network required

## Requirements

- Python 3.8 or higher
- Bluetooth adapter with BLE (Bluetooth Low Energy) support
- Linux with BlueZ installed (for peripheral mode)
- Appropriate Bluetooth permissions

## Installation

1. Install system dependencies (Linux):

```bash
# On Arch Linux
sudo pacman -S bluez python-dbus python-gobject

# On Ubuntu/Debian
sudo apt-get install bluez python3-dbus python3-gi

# On Fedora
sudo dnf install bluez python3-dbus python3-gobject
```

2. Install Python dependencies:

```bash
pip install -r requirements.txt
```

Or install manually:

```bash
pip install bleak dbus-python PyGObject
```

## Usage

1. Run the script on both devices:

```bash
python3 bitchat.py
```

Or with a username:

```bash
python3 bitchat.py YourUsername
```

2. On the first device, scan for peers:

```
> /scan
```

3. Connect to the discovered peer:

```
> /connect <device_address>
```

4. Start chatting! Just type your message and press Enter:

```
> Hello, this is a test message!
[You]: Hello, this is a test message!
[Peer]: Hi there! How are you?
```

## Commands

- `/scan` - Scan for nearby BLE chat peers (takes ~5 seconds)
- `/connect <address>` - Connect to a peer by their Bluetooth address
- `/status` - Show current connection status
- `/disconnect` - Disconnect from current peer
- `/help` - Show available commands
- `/quit` - Exit the application

## How It Works

1. **Peripheral Mode**: Each instance advertises itself as a BLE service with the name "BitChat-<username>", making it discoverable by other devices.

2. **Central Mode**: Each instance can scan for nearby devices and connect to peers advertising the chat service.

3. **Message Exchange**: Once connected, messages are exchanged via GATT characteristics:
   - TX Characteristic: Used to send messages (write)
   - RX Characteristic: Used to receive messages (notify)

## Troubleshooting

### "No BLE adapter found"
- Ensure Bluetooth is enabled on your system
- Check that BlueZ is installed and running: `systemctl status bluetooth`
- Verify adapter is available: `bluetoothctl show`

### "Failed to set up peripheral mode"
- Ensure you have appropriate permissions (may need to run with `sudo` or configure udev rules)
- Check that BlueZ D-Bus service is running
- Peripheral mode may not work on all systems - you can still connect to other devices even if advertising fails

### "Connection failed"
- Ensure both devices are within Bluetooth range
- Make sure the other device is running the chat application
- Try scanning again to verify the peer is discoverable

### Permission errors
- On Linux, you may need to run with `sudo` or add your user to the `bluetooth` group:
  ```bash
  sudo usermod -aG bluetooth $USER
  ```
  (Log out and back in for changes to take effect)

## Technical Details

- **Service UUID**: `00001234-0000-1000-8000-00805f9b34fb`
- **TX Characteristic**: `00001235-0000-1000-8000-00805f9b34fb` (write/notify)
- **RX Characteristic**: `00001236-0000-1000-8000-00805f9b34fb` (read/notify)

The application uses:
- `bleak` for BLE central operations (scanning, connecting, GATT operations)
- BlueZ D-Bus API for peripheral mode (advertising)
- `asyncio` for concurrent operations

## Limitations

- One-to-one chat only (connects to one peer at a time)
- Messages are sent as plain text (no encryption)
- Requires both devices to be within Bluetooth range (~10 meters typical)
- Peripheral mode requires Linux with BlueZ

## License

This is a simple demonstration application. Use at your own discretion.
