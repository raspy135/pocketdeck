# Getting Started with Pocket Cast

Pocket Cast is a web-based screencast viewer for your ESP32 Pocket Computer. It allows you to view the device's screen on your computer via a smooth, high-performance web interface.

## Prerequisites

1.  **Python 3.7+**: Make sure Python is installed on your system.
2.  **Web Browser**: A modern browser like Chrome, Firefox, or Edge.
3.  **ESP32 Device**: Your custom ESP32 pocket computer running the screencast server (listening on port 12022).

## Installation

1.  Install the required Python library for the proxy server:
    ```bash
    pip install websockets
    ```

## Running the Application

### 1. Start the Proxy Server
The web browser cannot connect directly to the ESP32's raw TCP socket. We use a lightweight Python proxy to bridge the connection.

Run the proxy script:
```bash
python py/proxy.py
```
*By default, this attempts to connect to an ESP32 at `192.168.11.99`. If your device has a different IP, specify it as an argument:*
```bash
python py/proxy.py 192.168.1.50
```

### 2. Open the Web Interface
Open the `web/index.html` file in your web browser. You can typically double-click the file, or run a simple HTTP server:
```bash
# Optional: Serve via HTTP
cd web
python -m http.server 8080
# Then open http://localhost:8080 in your browser
```

### 3. Connect
Click the **Connect** button in the web interface. You should see your ESP32's screen mirrored in real-time!

## Troubleshooting

-   **Connection Failed**: Ensure your computer and the ESP32 are on the same Wi-Fi network.
-   **Static/Snow**: If you don't have the device handy, you can run the mock device simulator to test the interface:
    ```bash
    python py/mock_device.py
    ```
