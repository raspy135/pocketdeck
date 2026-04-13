import asyncio
import websockets
import socket
import sys

# Configuration
ESP32_HOST = '192.168.11.99'
ESP32_PORT = 12022
WEBSOCKET_PORT = 8000
BUFFER_SIZE = 12000  # Expecting 12000 bytes for a 400x240 monochrome image (1 bit per pixel)

import hashlib

async def forward_to_esp32(websocket):
    """
    Handles a single WebSocket connection.
    Relays messages from the WebSocket to the ESP32 and back.
    """
    print(f"Client connected: {websocket.remote_address}")
    
    tcp_socket = None
    try:
        async def read_resp_header():
            if not tcp_socket: return None
            header = tcp_socket.recv(4)
            if len(header) < 4:
                return None
            return header[0]

        async for message in websocket:
            if isinstance(message, str):
                if message.startswith("target_ip:"):
                    new_host = message.split(':', 1)[1]
                    try:
                        if tcp_socket: tcp_socket.close()
                        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        tcp_socket.settimeout(5.0)
                        print(f"Connecting to ESP32 at {new_host}:{ESP32_PORT}...")
                        tcp_socket.connect((new_host, ESP32_PORT))
                        print("Connected to ESP32.")
                        await websocket.send("connect_success")
                    except Exception as e:
                        print(f"Connection failed: {e}")
                        tcp_socket = None
                        await websocket.send(f"connect_failed:{e}")
                    continue

                if not tcp_socket:
                    await websocket.send("ERROR: Not connected to target device.")
                    continue

                if message.startswith("auth:"):
                    password = message.split(':', 1)[1]
                    md5_hex = hashlib.md5(password.encode('utf-8')).hexdigest()
                    try:
                        tcp_socket.sendall(f"auth {md5_hex}".encode('utf-8'))
                        code = await read_resp_header()
                        if code == 0:
                            await websocket.send("auth_success")
                            print("Authorization successful.")
                        else:
                            await websocket.send(f"auth_failed:code_{code}")
                            print(f"Authorization failed: code {code}")
                    except socket.error as e:
                        await websocket.send(f"ERROR: {e}")

                elif message == "send_screen":
                    try:
                        tcp_socket.sendall(message.encode('utf-8'))
                        code = await read_resp_header()
                        if code != 0:
                            await websocket.send(f"ERROR: Code {code}")
                            continue
                            
                        data = b''
                        while len(data) < BUFFER_SIZE:
                            chunk = tcp_socket.recv(BUFFER_SIZE - len(data))
                            if not chunk: break
                            data += chunk
                        
                        if len(data) == BUFFER_SIZE:
                            await websocket.send(data)
                        else:
                            await websocket.send(b'ERROR: Incomplete data')
                    except socket.error as e:
                        print(f"Socket error: {e}")
                        break
                
                elif message.startswith("put_clipboard:"):
                    content = message.split(':', 1)[1]
                    content_bytes = content.encode('utf-8')
                    size = len(content_bytes)
                    try:
                        tcp_socket.sendall(b"put_clipboard")
                        tcp_socket.sendall(size.to_bytes(4, 'little'))
                        tcp_socket.sendall(content_bytes)
                        code = await read_resp_header()
                        if code != 0:
                            await websocket.send(f"ERROR: Clipboard put failed ({code})")
                    except socket.error as e:
                        print(f"Socket error clp: {e}")

                elif message == "get_clipboard":
                    try:
                        tcp_socket.sendall(b"get_clipboard")
                        code = await read_resp_header()
                        if code != 0:
                            await websocket.send(f"ERROR: Clipboard get failed ({code})")
                            continue
                            
                        size_bytes = tcp_socket.recv(4)
                        if len(size_bytes) == 4:
                            size = int.from_bytes(size_bytes, 'little')
                            clip_data = b''
                            while len(clip_data) < size:
                                chunk = tcp_socket.recv(size - len(clip_data))
                                if not chunk: break
                                clip_data += chunk
                            
                            if len(clip_data) == size:
                                text = clip_data.decode('utf-8', errors='ignore')
                                await websocket.send(f"clipboard_data:{text}")
                    except socket.error as e:
                        print(f"Socket error get_clp: {e}")

                elif message == "get_file_list":
                    try:
                        tcp_socket.sendall(b"get_file_list")
                        code = await read_resp_header()
                        if code != 0:
                            await websocket.send(f"file_list_error:{code}")
                            continue
                        size_bytes = tcp_socket.recv(4)
                        size = int.from_bytes(size_bytes, 'little')
                        data = b''
                        while len(data) < size:
                            chunk = tcp_socket.recv(size - len(data))
                            if not chunk: break
                            data += chunk
                        await websocket.send(f"file_list:{data.decode('utf-8')}")
                    except socket.error as e:
                        await websocket.send(f"ERROR: {e}")

                elif message.startswith("get_file:"):
                    filename = message.split(':', 1)[1]
                    try:
                        tcp_socket.sendall(f"get_file {filename}".encode('utf-8'))
                        code = await read_resp_header()
                        if code != 0:
                            await websocket.send(f"file_get_error:{code}")
                            print(f"File get error: {code}")
                            continue
                        size_bytes = tcp_socket.recv(4)
                        size = int.from_bytes(size_bytes, 'little')
                        # Send size prefix to WS first so client knows how much to expect
                        await websocket.send(f"file_start:{filename}:{size}")
                        print(f"Receiving file {filename} ({size} bytes)")
                        total_sent = 0
                        while total_sent < size:
                            chunk = tcp_socket.recv(min(4096, size - total_sent))
                            if not chunk: break
                            await websocket.send(chunk)
                            total_sent += len(chunk)
                    except socket.error as e:
                        await websocket.send(f"ERROR: {e}")
                else:
                    print(f"Unknown string message received: {message}")

            elif isinstance(message, bytes):
                if not tcp_socket:
                    await websocket.send("ERROR: Not connected to target device.")
                    continue

                if message.startswith(b"put_file:"):
                    # Binary message expected for upload: "put_file:[filename]\0[binary_data]"
                    parts = message.split(b":", 1)
                    content = parts[1]
                    f_null_idx = content.find(b"\0")
                    if f_null_idx != -1:
                        filename = content[:f_null_idx].decode('utf-8')
                        file_data = content[f_null_idx+1:]
                        size = len(file_data)
                        try:
                            tcp_socket.sendall(b"put_file ")
                            tcp_socket.sendall(filename.encode('utf-8') + b"\0")
                            tcp_socket.sendall(size.to_bytes(4, 'little'))
                            tcp_socket.sendall(file_data)
                            code = await read_resp_header()
                            if code == 0:
                                await websocket.send("file_put_success")
                            else:
                                await websocket.send(f"file_put_error:{code}")
                        except socket.error as e:
                            await websocket.send(f"ERROR: {e}")
                else:
                    print(f"Unknown binary message received: {len(message)} bytes")

    except Exception as e:
        print(f"Connection error: {e}")
        try:
             await websocket.send(f"ERROR: {e}")
        except:
             pass
    finally:
        if tcp_socket:
            tcp_socket.close()
        print(f"Client disconnected: {websocket.remote_address}")

async def main():
    # Allow overriding host via command line
    global ESP32_HOST
    if len(sys.argv) == 2:
        ESP32_HOST = sys.argv[1]
        
    print(f"Starting WebSocket Proxy on port {WEBSOCKET_PORT}")
    print(f"Target ESP32: {ESP32_HOST}:{ESP32_PORT}")
    
    async with websockets.serve(forward_to_esp32, "localhost", WEBSOCKET_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping proxy.")
