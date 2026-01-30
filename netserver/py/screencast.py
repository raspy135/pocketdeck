import socket
import pygame
import time
import sys

SCREEN_WIDTH = 400
SCREEN_HEIGHT = 240
# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
GRAY = (200, 200, 200)
DARK_GRAY = (100, 100, 100)
BUTTON_COLOR = (70, 130, 180)
BUTTON_HOVER = (100, 160, 210)

running = True
rects = []
pygame.init()

class pd_socket:
    def __init__(self, server_host='192.168.1.1', server_port=12022):
        """Connects to a TCP server, sends a message, and prints the response."""
        # Validate port
        if not (0 < server_port < 65536):
            raise ValueError("Port number must be between 1 and 65535.")

        # Create a TCP/IP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            print(f"Connecting to {server_host}:{server_port}...")
            self.sock.connect((server_host, server_port))



        except ConnectionRefusedError:
            print("Error: Could not connect to the server. Is it running?")
        except socket.gaierror:
            print("Error: Invalid server address.")
        except Exception as e:
            print(f"Unexpected error: {e}")

    def request(self, message):
        # Send data
        #print(f"Sending: {message}")
        self.sock.sendall(message.encode('utf-8'))

        response = bytes()
        # Receive response
        while True:
            last_response = self.sock.recv(50*240)  # Buffer size 1024 bytes
            response = response + last_response
            if len(last_response)==0 or len(response) == 12000:
                break
            #print(f"Received: {len(response)}")
        #game.update_canvas(response)
        return response


class pygame_canvas:
    def __init__(self, pd_conn):
        self.pd_conn = pd_conn
        # Initialize PyGame

        self.screen = pygame.display.set_mode((SCREEN_WIDTH*2, SCREEN_HEIGHT*2))
        pygame.display.set_caption("Pocket deck screencast")
        # Create canvas surface (for the 400x240 drawing area)
        self.canvas = pygame.Surface((SCREEN_WIDTH,SCREEN_HEIGHT))
        self.canvas.fill(WHITE)

    def exit_app(self):
        """Exit the application"""
        pygame.quit()
        global running
        running = False
        sys.exit()
        
    def handle_events(self):
        """Handle all events"""
        mouse_pos = pygame.mouse.get_pos()
        
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.exit_app()

    def update_onebyte(self, x,y,byte,pixel_array):
        for i in range(8): #index, pixel in enumerate(pat):
            pixel = True if byte & (1 << (7-i)) else False
            color = BLACK
            if pixel:
                color = WHITE
            else:
                continue
            dx = (x + i)
            dy = y
            #pygame.draw.rect(self.canvas, color, 
            #               (dx , dy, 2, 2))
            pixel_array[dx, dy] = color
            #pixel_array[dx+1, dy] = color
            #pixel_array[dx, dy+1] = color
            #pixel_array[dx+1, dy+1] = color
            #canvas.itemconfig(rects[r_index],fill=color) 
            #r_index += 1
            #canvas.create_rectangle(dx,dy,dx+2,dy+2, fill=color, outline='')

    def update_canvas(self, data):
#        print("hello")
        pixel_array = pygame.PixelArray(self.canvas)
        for i in range(len(data)):
            y = i // (SCREEN_WIDTH//8)
            x = (i % (SCREEN_WIDTH//8)) * 8
            self.update_onebyte(x,y, data[i],pixel_array)
        del pixel_array
    
    def draw_ui(self):
        """Draw the user interface"""
        # Clear screen
        self.screen.fill(BLACK)
        # Draw canvas surface
        scaled_canvas = pygame.transform.scale(self.canvas,(SCREEN_WIDTH*2,SCREEN_HEIGHT*2))
        self.screen.blit(scaled_canvas, (0,0))
 

    def run(self):
        """Main game loop"""
        while True:
            self.handle_events()
            self.draw_ui()
            
            # Update display
            pygame.display.flip()
            
            # Cap frame rate
            #self.clock.tick(self.fps)
            #time.sleep(0.1)
            self.canvas.fill(BLACK)
            self.update_canvas(self.pd_conn.request("send_screen"))




if __name__ == "__main__":
    host = '192.168.11.101'
    if len(sys.argv) == 2:
        host = sys.argv[1]    
    pd_conn = pd_socket(server_host=host)
    game = pygame_canvas(pd_conn)    
    # Start the GUI event loop
    #running = False
    game.run()
    
