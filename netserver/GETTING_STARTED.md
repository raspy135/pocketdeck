# Netserver

Pocket deck provides netserver app, which can be used for screencast, clipboard sharing and file sharing.

There are two type of clients available. One is web app with Python, and another one is iOS app.

## Prerequisites for web

1.  **Python 3.7+**: Make sure Python is installed on your system.
2.  **Web Browser**: A modern browser like Chrome, Firefox, or Edge.

## Starting Netserver

You need to start Netserver on Pocket Deck. To start Netserver, execute `netserver` in command line. You need to connect WiFi before you start Netserver.

```
wifi
(Some messages)
netserver [password]
```
password is saved to /config/netserver_password.  If no password is passed, then the stored password is used.

Note the IP address from the result of `wifi` command.

## Web client

### Installation

```bash
pip install websockets
```
### 1. Start the Proxy Server
The web app needs proxy python script running.
Run the proxy script:

```bash
python py/proxy.py
```

### 2. Open the Web Interface
Open the `web/index.html` file in your web browser. 

### 3. Connect

Input IP address of Pocket deck and password, then click the **Connect device** button in the web interface.

## iOS app

iOS app has the same features as web client. Download 'pocket deck' app from app store.

