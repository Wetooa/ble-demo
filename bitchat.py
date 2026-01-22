#!/usr/bin/env python3
"""
BLE Chat - A simple terminal-based Bluetooth Low Energy chat application.
Two clients can discover and connect to each other for local messaging.
"""

import asyncio
import sys
import uuid
import signal
from typing import Optional, List
from bleak import BleakScanner, BleakClient, BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
import dbus
import dbus.exceptions
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

# GATT Service and Characteristic UUIDs
CHAT_SERVICE_UUID = "00001234-0000-1000-8000-00805f9b34fb"
TX_CHAR_UUID = "00001235-0000-1000-8000-00805f9b34fb"  # Write/Notify
RX_CHAR_UUID = "00001236-0000-1000-8000-00805f9b34fb"  # Read/Notify

# BlueZ D-Bus paths
BLUEZ_SERVICE = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHAR_IFACE = "org.bluez.GattCharacteristic1"


class ChatAdvertisement(dbus.service.Object):
    """D-Bus advertisement object for making device discoverable"""

    PATH_BASE = "/org/bluez/example/advertisement"

    def __init__(self, bus, index, name):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = "peripheral"
        self.service_uuids = [CHAT_SERVICE_UUID]
        self.local_name = name
        self.include_tx_power = True
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            LE_ADVERTISEMENT_IFACE: {
                "Type": self.ad_type,
                "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s"),
                "LocalName": dbus.String(self.local_name),
                "IncludeTxPower": dbus.Boolean(self.include_tx_power),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        print("[Advertisement] Released")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface == LE_ADVERTISEMENT_IFACE:
            return self.get_properties()[LE_ADVERTISEMENT_IFACE]
        else:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.UnknownInterface",
                "Interface {} is not supported".format(interface),
            )

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self.get_properties()[interface][prop]

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv", out_signature="")
    def Set(self, interface, prop, value):
        pass

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class ChatService(dbus.service.Object):
    """GATT Service for chat communication"""

    PATH_BASE = "/org/bluez/example/service"

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array(
                    self.get_characteristic_paths(), signature="o"
                ),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface == GATT_SERVICE_IFACE:
            return self.get_properties()[GATT_SERVICE_IFACE]
        else:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.UnknownInterface",
                "Interface {} is not supported".format(interface),
            )

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self.get_properties()[interface][prop]


class ChatCharacteristic(dbus.service.Object):
    """GATT Characteristic for message transmission/reception"""

    PATH_BASE = "/org/bluez/example/char"

    def __init__(self, bus, index, uuid, flags, service, message_handler):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.message_handler = message_handler
        self.value = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHAR_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
                "Value": dbus.Array(self.value, signature="y"),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface == GATT_CHAR_IFACE:
            return self.get_properties()[GATT_CHAR_IFACE]
        else:
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.UnknownInterface",
                "Interface {} is not supported".format(interface),
            )

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self.get_properties()[interface][prop]

    @dbus.service.method(GATT_CHAR_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        return self.value

    @dbus.service.method(GATT_CHAR_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        if self.message_handler:
            try:
                message = bytes(value).decode("utf-8")
                self.message_handler(message)
            except Exception as e:
                print(f"[Error decoding message: {e}]")
        self.value = value

    @dbus.service.method(GATT_CHAR_IFACE)
    def StartNotify(self):
        pass

    @dbus.service.method(GATT_CHAR_IFACE)
    def StopNotify(self):
        pass

    @dbus.service.signal(dbus.PROPERTIES_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass


class BLEChatPeer:
    """Main BLE Chat peer that can act as both peripheral and central"""

    def __init__(self, username: str):
        self.username = username
        self.client: Optional[BleakClient] = None
        self.connected_address: Optional[str] = None
        self.running = True
        self.tx_char: Optional[BleakGATTCharacteristic] = None
        self.rx_char: Optional[BleakGATTCharacteristic] = None
        self.message_queue = asyncio.Queue()
        self.bus = None
        self.adapter = None
        self.ad_manager = None
        self.gatt_manager = None
        self.advertisement = None
        self.service = None
        self.tx_characteristic = None
        self.rx_characteristic = None

    def setup_peripheral(self):
        """Set up peripheral mode (advertising) using BlueZ D-Bus"""
        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            self.bus = dbus.SystemBus()

            # Find the first available adapter
            adapter_path = None
            om = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE, "/"), "org.freedesktop.DBus.ObjectManager")
            objects = om.GetManagedObjects()
            for path, interfaces in objects.items():
                if LE_ADVERTISING_MANAGER_IFACE in interfaces:
                    adapter_path = path
                    break

            if not adapter_path:
                print("[Warning] No BLE adapter found. Peripheral mode disabled.")
                return False

            self.adapter = self.bus.get_object(BLUEZ_SERVICE, adapter_path)
            self.ad_manager = dbus.Interface(self.adapter, LE_ADVERTISING_MANAGER_IFACE)
            self.gatt_manager = dbus.Interface(self.adapter, GATT_MANAGER_IFACE)

            # Create and register advertisement
            self.advertisement = ChatAdvertisement(self.bus, 0, f"BitChat-{self.username}")
            self.ad_manager.RegisterAdvertisement(
                self.advertisement.get_path(),
                {},
                reply_handler=self._register_ad_cb,
                error_handler=self._register_ad_error_cb,
            )

            # Create and register GATT service
            self.service = ChatService(self.bus, 0, CHAT_SERVICE_UUID, True)
            self.tx_characteristic = ChatCharacteristic(
                self.bus, 0, TX_CHAR_UUID, ["write", "notify"], self.service, self._handle_received_message
            )
            self.rx_characteristic = ChatCharacteristic(
                self.bus, 1, RX_CHAR_UUID, ["read", "notify"], self.service, None
            )
            self.service.add_characteristic(self.tx_characteristic)
            self.service.add_characteristic(self.rx_characteristic)

            self.gatt_manager.RegisterApplication(
                self.service.get_path(),
                {},
                reply_handler=self._register_app_cb,
                error_handler=self._register_app_error_cb,
            )

            print(f"[Peripheral] Advertising as 'BitChat-{self.username}'")
            return True

        except Exception as e:
            print(f"[Warning] Failed to set up peripheral mode: {e}")
            print("[Info] You can still connect to other devices, but others won't be able to discover you.")
            return False

    def _register_ad_cb(self):
        print("[Peripheral] Advertisement registered")

    def _register_ad_error_cb(self, error):
        print(f"[Peripheral] Failed to register advertisement: {error}")

    def _register_app_cb(self):
        print("[Peripheral] GATT application registered")

    def _register_app_error_cb(self, error):
        print(f"[Peripheral] Failed to register GATT application: {error}")

    def _handle_received_message(self, message: str):
        """Handle incoming message from peripheral mode"""
        asyncio.create_task(self.message_queue.put(("received", message)))

    async def scan_for_peers(self, timeout: float = 5.0) -> List[BLEDevice]:
        """Scan for nearby BLE devices advertising the chat service"""
        print(f"\n[*] Scanning for BLE chat peers (timeout: {timeout}s)...")
        devices = await BleakScanner.discover(timeout=timeout)
        
        # Filter devices that might be chat peers (name starts with "BitChat" or show our service UUID)
        chat_peers = []
        for device in devices:
            if device.name and ("BitChat" in device.name or device.name.startswith("BitChat")):
                chat_peers.append(device)
        
        if not chat_peers:
            print("[*] No chat peers found. Showing all BLE devices:")
            return devices
        else:
            print(f"[*] Found {len(chat_peers)} chat peer(s):")
            return chat_peers

    async def connect_to_peer(self, address: str) -> bool:
        """Connect to a peer device"""
        if self.client and self.client.is_connected:
            print("[!] Already connected. Disconnect first.")
            return False

        try:
            print(f"[*] Connecting to {address}...")
            self.client = BleakClient(address)
            await self.client.connect()
            self.connected_address = address

            # Discover services and characteristics
            services = await self.client.get_services()
            chat_service = None
            for service in services:
                if service.uuid.lower() == CHAT_SERVICE_UUID.lower():
                    chat_service = service
                    break

            if not chat_service:
                print("[!] Chat service not found on peer device")
                await self.disconnect()
                return False

            # Find characteristics
            for char in chat_service.characteristics:
                if char.uuid.lower() == TX_CHAR_UUID.lower():
                    self.tx_char = char
                elif char.uuid.lower() == RX_CHAR_UUID.lower():
                    self.rx_char = char

            if not self.tx_char or not self.rx_char:
                print("[!] Required characteristics not found")
                await self.disconnect()
                return False

            # Subscribe to notifications on RX characteristic
            await self.client.start_notify(self.rx_char.uuid, self._notification_handler)

            print(f"[+] Connected to {address}")
            print(f"[+] Peer name: {self.client.address}")
            return True

        except Exception as e:
            print(f"[-] Connection failed: {e}")
            self.client = None
            self.connected_address = None
            return False

    def _notification_handler(self, sender: BleakGATTCharacteristic, data: bytearray):
        """Handle notifications from connected peer"""
        try:
            message = data.decode("utf-8")
            asyncio.create_task(self.message_queue.put(("received", message)))
        except Exception as e:
            print(f"[Error decoding notification: {e}]")

    async def send_message(self, message: str) -> bool:
        """Send a message to the connected peer"""
        if not self.client or not self.client.is_connected:
            print("[-] Not connected to any peer")
            return False

        if not self.tx_char:
            print("[-] TX characteristic not available")
            return False

        try:
            formatted_message = f"{self.username}: {message}"
            await self.client.write_gatt_char(self.tx_char.uuid, formatted_message.encode("utf-8"))
            print(f"[You]: {message}")
            return True
        except Exception as e:
            print(f"[-] Failed to send message: {e}")
            return False

    async def disconnect(self):
        """Disconnect from current peer"""
        if self.client and self.client.is_connected:
            try:
                if self.rx_char:
                    await self.client.stop_notify(self.rx_char.uuid)
                await self.client.disconnect()
                print("[*] Disconnected")
            except Exception as e:
                print(f"[!] Error during disconnect: {e}")
            finally:
                self.client = None
                self.connected_address = None
                self.tx_char = None
                self.rx_char = None

    async def process_messages(self):
        """Process received messages from queue"""
        while self.running:
            try:
                msg_type, message = await asyncio.wait_for(self.message_queue.get(), timeout=0.5)
                if msg_type == "received":
                    print(f"\n[Peer]: {message}")
                    print("> ", end="", flush=True)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[Error processing message: {e}]")

    async def interactive_mode(self):
        """Main interactive chat loop"""
        print(f"\n[*] BitChat - BLE Chat Application")
        print(f"[*] Username: {self.username}")
        print(f"[*] Type /help for commands\n")

        # Start peripheral mode in background thread
        peripheral_thread = None
        if self.bus:
            import threading
            peripheral_thread = threading.Thread(target=self._run_peripheral_loop, daemon=True)
            peripheral_thread.start()

        # Start message processing
        message_task = asyncio.create_task(self.process_messages())

        # Main command loop
        while self.running:
            try:
                user_input = await asyncio.to_thread(input, "> ")
                user_input = user_input.strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    await self._handle_command(user_input)
                else:
                    await self.send_message(user_input)

            except (KeyboardInterrupt, EOFError):
                print("\n[*] Exiting...")
                self.running = False
                break
            except Exception as e:
                print(f"[Error: {e}]")

        # Cleanup
        await self.disconnect()
        message_task.cancel()
        # Peripheral thread will exit when daemon=True

    def _run_peripheral_loop(self):
        """Run the GLib main loop for D-Bus peripheral mode"""
        try:
            loop = GLib.MainLoop()
            loop.run()
        except Exception as e:
            print(f"[Peripheral loop error: {e}]")

    async def _handle_command(self, command: str):
        """Handle user commands"""
        parts = command.split()
        cmd = parts[0].lower()

        if cmd == "/help":
            print("\nCommands:")
            print("  /scan              - Scan for nearby BLE chat peers")
            print("  /connect <addr>    - Connect to a peer by address")
            print("  /status            - Show connection status")
            print("  /disconnect        - Disconnect from current peer")
            print("  /quit              - Exit the application")
            print("  /help              - Show this help message")
            print("\nJust type a message to send it to the connected peer.\n")

        elif cmd == "/scan":
            devices = await self.scan_for_peers()
            if devices:
                print("\n[*] Available devices:")
                for i, device in enumerate(devices, 1):
                    name = device.name or "Unknown"
                    print(f"  {i}. {name} ({device.address})")
                print()

        elif cmd == "/connect":
            if len(parts) < 2:
                print("[-] Usage: /connect <address>")
                return
            address = parts[1]
            await self.connect_to_peer(address)

        elif cmd == "/status":
            if self.client and self.client.is_connected:
                print(f"[+] Connected to {self.connected_address}")
            else:
                print("[-] Not connected")

        elif cmd == "/disconnect":
            await self.disconnect()

        elif cmd == "/quit":
            self.running = False

        else:
            print(f"[-] Unknown command: {cmd}. Type /help for available commands.")


async def main():
    """Main entry point"""
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("Enter your username: ").strip() or "User"

    peer = BLEChatPeer(username)

    # Set up signal handlers for graceful shutdown
    def signal_handler(sig, frame):
        peer.running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Set up peripheral mode (run in thread to avoid blocking)
    import threading
    def setup_peripheral_thread():
        try:
            peer.setup_peripheral()
        except Exception as e:
            print(f"[Warning] Peripheral setup failed: {e}")
    
    peripheral_setup_thread = threading.Thread(target=setup_peripheral_thread, daemon=True)
    peripheral_setup_thread.start()
    # Give it a moment to initialize
    await asyncio.sleep(0.5)

    # Run interactive mode
    await peer.interactive_mode()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[*] Exiting...")
        sys.exit(0)
