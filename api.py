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
        self.callbacks = []
        self.connected = False
        self._request_id = 0
        self._client_id = 1
        self._pending_requests = {}

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
        try:
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
                    return True
                await asyncio.sleep(0.5)

            return False
        except Exception as e:
            _LOGGER.error(f"Connection failed: {e}")
            return False

    def _on_open(self, ws):
        """Handle WebSocket open."""
        self.connected = True
        _LOGGER.info("WebSocket connected")

    def _on_message(self, ws, message):
        """Handle incoming messages."""
        try:
            data = json.loads(message)
            _LOGGER.debug(f"Received: {data}")

            # Handle response to our requests
            request_id = data.get("request_id")
            if request_id and request_id in self._pending_requests:
                self._pending_requests[request_id] = data

            # Handle device list response
            if data.get("action") == "get_device_list" and data.get("data"):
                self._handle_device_list(data["data"])

        except Exception as e:
            _LOGGER.error(f"Message handling error: {e}")

    def _on_error(self, ws, error):
        """Handle WebSocket errors."""
        _LOGGER.error(f"WebSocket error: {error}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close."""
        self.connected = False
        _LOGGER.info("WebSocket disconnected")

    async def _send_request(self, action: str, node_id: str = None, args: dict = None) -> dict:
        """Send request and wait for response."""
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

        self._pending_requests[request_id] = None
        self.ws.send(json.dumps(request))

        # Wait for response
        for _ in range(50):  # 5 second timeout
            if self._pending_requests[request_id] is not None:
                response = self._pending_requests.pop(request_id)
                if response.get("code") == 0:
                    return response
                else:
                    _LOGGER.error(f"Request failed: {response}")
                    return None
            await asyncio.sleep(0.1)

        self._pending_requests.pop(request_id, None)
        return None

    async def _discover_devices(self):
        """Discover all devices."""
        response = await self._send_request("get_device_list")
        if response and response.get("data"):
            self._handle_device_list(response["data"])

    def _handle_device_list(self, device_list):
        """Process device list."""
        for device in device_list:
            device_id = device.get("node_id")
            if device_id and not device_id.startswith("9d75"):  # Skip "All" group
                self.devices[device_id] = device
                _LOGGER.info(f"Found device: {device.get('name')} ({device_id})")

    def register_callback(self, callback: Callable):
        """Register update callback."""
        self.callbacks.append(callback)

    async def get_device_state(self, device_id: str) -> dict:
        """Get complete device state."""
        state = {}

        # Get power state
        sleep_response = await self._send_request("get_sleep", device_id)
        if sleep_response and sleep_response.get("data") is not None:
            state["is_on"] = not sleep_response["data"]

        # Get brightness
        intensity_response = await self._send_request("get_intensity", device_id)
        if intensity_response and intensity_response.get("data") is not None:
            state["brightness"] = int((intensity_response["data"] / 1000) * 100)

        # Get color temperature
        cct_response = await self._send_request("get_cct", device_id)
        if cct_response and cct_response.get("data"):
            state["cct"] = cct_response["data"].get("cct", 5500)
            state["gm"] = cct_response["data"].get("gm", 0)

        return state

    async def set_power(self, device_id: str, on: bool):
        """Set device power state."""
        await self._send_request("set_sleep", device_id, {"sleep": not on})

    async def set_brightness(self, device_id: str, brightness: int):
        """Set device brightness (0-100)."""
        intensity = int((brightness / 100) * 1000)
        await self._send_request("set_intensity", device_id, {"intensity": intensity})

    async def set_cct(self, device_id: str, temperature: int, gm: int = 0):
        """Set color temperature (2000-10000K) and green/magenta."""
        await self._send_request("set_cct", device_id, {"cct": temperature, "gm": gm})

    async def set_hsi(self, device_id: str, hue: int, saturation: int, intensity: int = None):
        """Set HSI color."""
        args = {"hue": hue, "sat": saturation}
        if intensity is not None:
            args["intensity"] = intensity
        await self._send_request("set_hsi", device_id, args)

    def disconnect(self):
        """Disconnect WebSocket."""
        if self.ws:
            self.ws.close()
