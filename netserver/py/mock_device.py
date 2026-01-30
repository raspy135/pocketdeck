import socket
import time
import random

HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
PORT = 12022        # Port to listen on (non-privileged ports are > 1023)
SCREEN_WIDTH = 400
SCREEN_HEIGHT = 240
BUFFER_SIZE = (SCREEN_WIDTH * SCREEN_HEIGHT) // 8 # 12000 bytes

MOCK_CLIPBOARD = b"Initial Mock Clipboard Content"

def create_test_pattern(offset=0):
    """Creates a simple test pattern (vertical bars)"""
    data = bytearray(BUFFER_SIZE)
    for i in range(BUFFER_SIZE):
        # Create a moving pattern
        if (i + offset) % 32 < 16:
            data[i] = 0xFF # All pixels on (8 pixels)
        else:
            data[i] = 0x00 # All pixels off
    return data

def main():
    global MOCK_CLIPBOARD
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen()
        print(f"Mock Device listening on {HOST}:{PORT}")
        
        offset = 0
        while True:
            conn, addr = s.accept()
            with conn:
                print(f"Connected by {addr}")
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    
                    message = data.decode('utf-8', errors='ignore')
                    if "send_screen" in message:
                        #print("Sending screen data...")
                        conn.sendall(create_test_pattern(offset))
                        offset += 1
                    elif "put_clipboard" in message:
                        # Receive size (4 bytes)
                        size_bytes = conn.recv(4)
                        if len(size_bytes) == 4:
                            size = int.from_bytes(size_bytes, 'little')
                            clipboard_data = b''
                            while len(clipboard_data) < size:
                                chunk = conn.recv(size - len(clipboard_data))
                                if not chunk: break
                                clipboard_data += chunk
                            print(f"Mock: Clipboard set to {clipboard_data}")
                            MOCK_CLIPBOARD = clipboard_data
                            
                    elif "get_clipboard" in message:
                        size = len(MOCK_CLIPBOARD)
                        conn.sendall(size.to_bytes(4, 'little'))
                        if size > 0:
                            conn.sendall(MOCK_CLIPBOARD)
                        print(f"Mock: Sent clipboard {MOCK_CLIPBOARD}")

                    else:
                        print(f"Unknown command: {message}")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopping mock device.")
