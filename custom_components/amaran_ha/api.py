"""API client for Amaran WebSocket communication."""
import asyncio
import json
import base64
import logging
import time
from typing import Any, Callable, Dict, Optional
import websocket
from threading import Thread
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes

_LOGGER = logging.getLogger(__name__)

class AmaranAPI:
    """Handle WebSocket communication with Amaran."""

    def __init__(self, host: str, port: int, api_key: str):
        """Initialize the API client."""
        self.host = host
        self.port = port
        self.api_key = api_key
        self.ws = None
        self.devices = {}
        self.device_states = {}  # Track actual device states
        self.callbacks = []
        self.connected = False
        self._request_id = 0
        self._client_id = 1
        self._pending_requests = {}
        self._heartbeat_task = None
        self._reconnect_lock = asyncio.Lock()
        self._last_set_time = 0  # Track last SET command time
        self._set_lock = asyncio.Lock()  # Serialize SET commands

    def _get_next_request_id(self) -> int:
        """Get next request ID."""
        self._request_id += 1
        return self._request_id

    def _generate_token(self) -> str:
        """Generate auth token using AES-256-GCM."""
        iv = get_random_bytes(12)
        key = base64.b64decode(self.api_key)
        cipher = AES.new(key, AES.MODE_GCM, iv)

        now = str(int(time.time()))
        ciphertext, auth_tag = cipher.encrypt_and_digest(now.encode('utf-8'))

        # Concatenate IV + auth_tag + ciphertext
        token = iv + auth_tag + ciphertext
        return base64.b64encode(token).decode('utf-8')

    async def connect(self) -> bool:
        """Connect to WebSocket."""
        async with self._reconnect_lock:
            if self.connected and self.ws:
                return True

            try:
                if self.ws:
                    try:
                        self.ws.close()
                    except:
                        pass
                    self.ws = None

                url = f"ws://{self.host}:{self.port}"
                self.ws = websocket.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close
                )

                # Run WebSocket in separate thread
                self.ws_thread = Thread(target=self.ws.run_forever)
                self.ws_thread.daemon = True
                self.ws_thread.start()

                # Wait for connection
                for _ in range(10):
                    if self.connected:
                        await self._discover_devices()
                        if not self._heartbeat_task or self._heartbeat_task.done():
                            self._heartbeat_task = asyncio.create_task(self._heartbeat())
                        return True
                    await asyncio.sleep(0.5)

                return False
            except Exception as e:
                _LOGGER.error(f"Connection failed: {e}")
                return False

    async def ensure_connected(self) -> bool:
        """Ensure WebSocket is connected, reconnect if necessary."""
        if self.connected and self.ws:
            return True

        _LOGGER.info("WebSocket disconnected, attempting to reconnect...")
        return await self.connect()

    async def _heartbeat(self):
        """Send periodic heartbeat to keep connection alive."""
        while self.connected:
            try:
                await asyncio.sleep(30)
                if self.connected and self.ws:
                    response = await self._send_request("get_device_list", skip_reconnect=True)
                    if response is None:
                        _LOGGER.warning("Heartbeat failed, connection may be lost")
                        self.connected = False
                        break
            except Exception as e:
                _LOGGER.error(f"Heartbeat error: {e}")
                self.connected = False
                break

    def _on_open(self, ws):
        """Handle WebSocket open."""
        self.connected = True
        _LOGGER.info("WebSocket connected")

    def _on_message(self, ws, message):
        """Handle incoming messages."""
        try:
            data = json.loads(message)
            _LOGGER.debug(f"Received: {data}")

            request_id = data.get("request_id")
            if request_id and request_id in self._pending_requests:
                self._pending_requests[request_id] = data

            # Update cached state based on successful commands
            if data.get("code") == 0 and data.get("node_id"):
                self._update_cached_state(data)

            if data.get("action") == "get_device_list" and data.get("data"):
                self._handle_device_list(data["data"])

            for callback in self.callbacks:
                try:
                    callback(data)
                except Exception as e:
                    _LOGGER.error(f"Callback error: {e}")

        except Exception as e:
            _LOGGER.error(f"Message handling error: {e}")

    def _update_cached_state(self, data):
        """Update cached device state from response."""
        device_id = data.get("node_id")
        if not device_id or device_id not in self.device_states:
            return

        action = data.get("action")
        response_data = data.get("data")

        # Update state based on successful responses
        if action == "get_sleep" and response_data is not None:
            self.device_states[device_id]["is_on"] = not response_data
        elif action == "get_intensity" and response_data is not None:
            self.device_states[device_id]["brightness"] = int((response_data / 1000) * 100)
        elif action == "get_cct" and response_data:
            self.device_states[device_id]["cct"] = response_data.get("cct", 5500)
            self.device_states[device_id]["gm"] = response_data.get("gm", 100)
        elif action == "get_hsi" and response_data:
            self.device_states[device_id]["hue"] = response_data.get("hue", 0)
            self.device_states[device_id]["sat"] = response_data.get("sat", 0)

    def _on_error(self, ws, error):
        """Handle WebSocket errors."""
        _LOGGER.error(f"WebSocket error: {error}")
        self.connected = False

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close."""
        self.connected = False
        _LOGGER.info(f"WebSocket disconnected: {close_status_code} - {close_msg}")

    async def _send_request(self, action: str, node_id: str = None, args: dict = None, skip_reconnect: bool = False) -> dict:
        """Send request and wait for response."""
        # Serialize SET commands with 200ms delay to prevent hardware overload
        if action.startswith("set_"):
            async with self._set_lock:
                now = time.time()
                wait_time = max(0, 0.2 - (now - self._last_set_time))
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self._last_set_time = time.time()

        if not skip_reconnect:
            if not await self.ensure_connected():
                _LOGGER.error("Cannot send request - not connected")
                return None
        elif not self.connected or not self.ws:
            return None

        request_id = self._get_next_request_id()

        request = {
            "version": 2,
            "type": "request",
            "client_id": self._client_id,
            "request_id": request_id,
            "action": action,
            "token": self._generate_token()
        }

        if node_id:
            request["node_id"] = node_id
        if args:
            request["args"] = args

        try:
            self._pending_requests[request_id] = None
            self.ws.send(json.dumps(request))

            for _ in range(50):  # 5 second timeout
                if self._pending_requests[request_id] is not None:
                    response = self._pending_requests.pop(request_id)
                    if response.get("code") == 0:
                        # Update cached state for set commands
                        if node_id and action.startswith("set_"):
                            self._update_state_from_command(node_id, action, args)
                        return response
                    else:
                        _LOGGER.error(f"Request failed: {response}")
                        return None
                await asyncio.sleep(0.1)

            self._pending_requests.pop(request_id, None)
            _LOGGER.warning(f"Request timeout for action: {action}")
            return None

        except websocket.WebSocketConnectionClosedException:
            _LOGGER.error("WebSocket connection closed during request")
            self.connected = False
            return None
        except Exception as e:
            _LOGGER.error(f"Error sending request: {e}")
            return None

    def _update_state_from_command(self, device_id: str, action: str, args: dict):
        """Update cached state when sending commands."""
        if device_id not in self.device_states:
            self.device_states[device_id] = {}

        state = self.device_states[device_id]

        if action == "set_sleep" and args:
            state["is_on"] = not args.get("sleep", True)
        elif action == "set_intensity" and args:
            state["brightness"] = int((args.get("intensity", 0) / 1000) * 100)
        elif action == "set_cct" and args:
            state["cct"] = args.get("cct", 5500)
            state["gm"] = args.get("gm", 100)
        elif action == "set_hsi" and args:
            state["hue"] = args.get("hue", 0)
            state["sat"] = args.get("sat", 0)
            if "intensity" in args:
                state["brightness"] = int((args["intensity"] / 1000) * 100)

    async def _discover_devices(self):
        """Discover all devices."""
        response = await self._send_request("get_device_list", skip_reconnect=True)
        if response and response.get("data"):
            self._handle_device_list(response["data"])

    def _handle_device_list(self, device_list):
        """Process device list."""
        for device in device_list:
            device_id = device.get("node_id")
            if device_id and not device_id.startswith("9d75"):  # Skip "All" group
                self.devices[device_id] = device
                if device_id not in self.device_states:
                    self.device_states[device_id] = {}
                _LOGGER.info(f"Found device: {device.get('name')} ({device_id})")

    def register_callback(self, callback: Callable):
        """Register update callback."""
        self.callbacks.append(callback)

    def get_cached_state(self, device_id: str) -> dict:
        """Get cached device state."""
        return self.device_states.get(device_id, {})

    async def get_device_state(self, device_id: str) -> dict:
        """Get complete device state."""
        state = {}

        sleep_response = await self._send_request("get_sleep", device_id)
        if sleep_response and sleep_response.get("data") is not None:
            state["is_on"] = not sleep_response["data"]

        intensity_response = await self._send_request("get_intensity", device_id)
        if intensity_response and intensity_response.get("data") is not None:
            state["brightness"] = int((intensity_response["data"] / 1000) * 100)

        cct_response = await self._send_request("get_cct", device_id)
        if cct_response and cct_response.get("data"):
            state["cct"] = cct_response["data"].get("cct", 5500)
            state["gm"] = cct_response["data"].get("gm", 100)

        hsi_response = await self._send_request("get_hsi", device_id)
        if hsi_response and hsi_response.get("data"):
            state["hue"] = hsi_response["data"].get("hue", 0)
            state["sat"] = hsi_response["data"].get("sat", 0)

        # Update cache with fresh state
        self.device_states[device_id] = state

        return state

    async def set_power(self, device_id: str, on: bool):
        """Set device power state."""
        return await self._send_request("set_sleep", device_id, {"sleep": not on})

    async def set_brightness(self, device_id: str, brightness: int):
        """Set device brightness (0-100)."""
        intensity = int((brightness / 100) * 1000)
        return await self._send_request("set_intensity", device_id, {"intensity": intensity})

    async def set_cct(self, device_id: str, temperature: int, gm: int = 100):
        """Set color temperature (2000-10000K) and green/magenta."""
        return await self._send_request("set_cct", device_id, {"cct": temperature, "gm": gm})

    async def set_hsi(self, device_id: str, hue: int, saturation: int, intensity: int = None):
        """Set HSI color."""
        args = {"hue": hue, "sat": saturation}
        if intensity is not None:
            args["intensity"] = intensity
        return await self._send_request("set_hsi", device_id, args)

    def disconnect(self):
        """Disconnect WebSocket."""
        self.connected = False

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()

        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                _LOGGER.error(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None
