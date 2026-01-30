import asyncio
import websockets
import socket
import sys

# Configuration
ESP32_HOST = '192.168.11.99'
ESP32_PORT = 12022
WEBSOCKET_PORT = 8000
BUFFER_SIZE = 12000  # Expecting 12000 bytes for a 400x240 monochrome image (1 bit per pixel)

async def forward_to_esp32(websocket):
    """
    Handles a single WebSocket connection.
    Relays messages from the WebSocket to the ESP32 and back.
    """
    print(f"Client connected: {websocket.remote_address}")
    
    tcp_socket = None
    try:
        # Create a TCP connection to the ESP32
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.settimeout(5.0) # 5 second timeout
        print(f"Connecting to ESP32 at {ESP32_HOST}:{ESP32_PORT}...")
        tcp_socket.connect((ESP32_HOST, ESP32_PORT))
        print("Connected to ESP32.")

        async for message in websocket:
            if message == "send_screen":
                # Forward request to ESP32
                try:
                    tcp_socket.sendall(message.encode('utf-8'))
                    
                    # Receive response (exact number of bytes expected)
                    data = b''
                    while len(data) < BUFFER_SIZE:
                        chunk = tcp_socket.recv(BUFFER_SIZE - len(data))
                        if not chunk:
                            break
                        data += chunk
                    
                    if len(data) == BUFFER_SIZE:
                        # Send binary data back to WebSocket client
                        await websocket.send(data)
                    else:
                        print(f"Incomplete data received from ESP32: {len(data)} bytes")
                        await websocket.send(b'ERROR: Incomplete data')
                        
                except socket.error as e:
                    print(f"Socket error: {e}")
                    await websocket.send(f"ERROR: {e}".encode('utf-8'))
                    break
            
            elif message.startswith("put_clipboard:"):
                 # Format: put_clipboard:<content>
                 content = message.split(':', 1)[1]
                 content_bytes = content.encode('utf-8')
                 size = len(content_bytes)
                 
                 print(f"Sending clipboard data ({size} bytes)")
                 try:
                     tcp_socket.sendall(b"put_clipboard")
                     # Send size (little endian uint32)
                     tcp_socket.sendall(size.to_bytes(4, 'little'))
                     # Send data
                     tcp_socket.sendall(content_bytes)
                 except socket.error as e:
                    print(f"Socket error clp: {e}")

            elif message == "get_clipboard":
                 try:
                     tcp_socket.sendall(b"get_clipboard")
                     
                     # Receive size
                     size_bytes = tcp_socket.recv(4)
                     if len(size_bytes) == 4:
                         size = int.from_bytes(size_bytes, 'little')
                         print(size_bytes)
                         print(f"Receiving clipboard data ({size} bytes)")
                         
                         clip_data = b''
                         while len(clip_data) < size:
                             chunk = tcp_socket.recv(size - len(clip_data))
                             if not chunk: break
                             clip_data += chunk
                             
                         if len(clip_data) == size:
                             # Send back to browser text
                             text = clip_data.decode('utf-8', errors='ignore')
                             await websocket.send(f"clipboard_data:{text}")
                         else:
                             print("Error receiving clipboard data")
                 except socket.error as e:
                    print(f"Socket error get_clp: {e}")

            else:
                 print(f"Unknown message received: {message}")

    except Exception as e:
        print(f"Connection error: {e}")
        try:
             await websocket.send(f"ERROR: {e}".encode('utf-8'))
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
