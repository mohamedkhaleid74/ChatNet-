import socket
import threading
from datetime import datetime

# ==========================================
# Server Configuration
# ==========================================
HOST = '0.0.0.0'  # Bind to all network interfaces
PORT = 12000      # Default port as requested

# Dictionary to keep track of connected clients
# Maps client_socket -> username
clients = {}
clients_lock = threading.Lock()

def broadcast(message):
    """
    Sends a message to all connected clients.
    Uses a lock to prevent dictionary modification during iteration.
    """
    with clients_lock:
        for client_socket in list(clients.keys()):
            try:
                # All messages are appended with a newline for easy client reading
                client_socket.sendall((message + '\n').encode('utf-8'))
            except Exception as e:
                print(f"[ERROR] Failed to send message to a client: {e}")
                remove_client(client_socket)

def remove_client(client_socket):
    """
    Removes a client from the active connections and closes their socket.
    """
    with clients_lock:
        if client_socket in clients:
            username = clients[client_socket]
            del clients[client_socket]
            try:
                client_socket.close()
            except:
                pass
            print(f"[DISCONNECT] {username} has left the chat.")
            # Optional: Broadcast to others that the user left
            # broadcast(f"BROADCAST [{datetime.now().strftime('%H:%M:%S')}] SERVER: {username} has left.")

def handle_client(client_socket, addr):
    """
    Handles communication with a single connected client.
    Runs in a separate thread for each client.
    """
    print(f"[NEW CONNECTION] {addr} connected.")
    
    try:
        # 1. Send welcome message when client connects
        welcome_msg = "200 OK ; Connected to ChatNet Server\n"
        client_socket.sendall(welcome_msg.encode('utf-8'))
        
        # We use makefile() to read incoming data line-by-line easily
        reader = client_socket.makefile('r', encoding='utf-8')
        
        # 2. Receive the first message which should be the JOIN command with username
        first_line = reader.readline()
        if not first_line or not first_line.startswith('JOIN '):
            print(f"[ERROR] Invalid join from {addr}")
            client_socket.close()
            return
            
        username = first_line[5:].strip()
        
        # Add the new client to our dictionary
        with clients_lock:
            clients[client_socket] = username
        
        print(f"[JOIN] {username} joined from {addr}")
        
        # 3. Enter main loop to continuously process messages from this client
        while True:
            line = reader.readline()
            if not line:
                # If readline returns empty, the client disconnected
                break
                
            line = line.strip()
            
            # --- Protocol Handling ---
            
            # A standard chat message
            if line.startswith('CHAT '):
                message = line[5:]
                timestamp = datetime.now().strftime('%H:%M:%S')
                formatted_msg = f"BROADCAST [{timestamp}] {username}: {message}"
                broadcast(formatted_msg)
                
            # Ping command for RTT diagnostic
            elif line.startswith('PING '):
                # Format: PING <timestamp>
                _, ts = line.split(' ', 1)
                reply = f"PING_ECHO {ts}\n"
                client_socket.sendall(reply.encode('utf-8'))
                
            # Throughput diagnostic command
            elif line.startswith('THROUGHPUT '):
                # Format: THROUGHPUT <size> <timestamp> <payload>
                parts = line.split(' ', 3)
                if len(parts) >= 3:
                    size = parts[1]
                    ts = parts[2]
                    # We echo back an ACK with the size and timestamp.
                    # We DO NOT echo the payload back to save server bandwidth.
                    reply = f"THROUGHPUT_ACK {size} {ts}\n"
                    client_socket.sendall(reply.encode('utf-8'))
                    
            # Explicit disconnect command
            elif line == 'DISCONNECT':
                break
                
    except Exception as e:
        print(f"[ERROR] Exception in client thread {addr}: {e}")
    finally:
        # Ensure client is removed and socket is closed when the loop ends or crashes
        remove_client(client_socket)

def start_server():
    """
    Main function to start the TCP server and listen for connections.
    """
    # Create a TCP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # Allow port reuse immediately after server restart
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)
        
        # Automatically detect and print server IP using gethostbyname
        hostname = socket.gethostname()
        server_ip = socket.gethostbyname(hostname)
        
        print("="*40)
        print(" ChatNet Server Started")
        print(f" Hostname: {hostname}")
        print(f" Server IP: {server_ip}")
        print(f" Port: {PORT}")
        print(" Waiting for clients...")
        print("="*40)
        
        # Infinite loop to accept new clients
        while True:
            client_socket, addr = server_socket.accept()
            
            # Start a new thread for each client so multiple clients can chat simultaneously
            thread = threading.Thread(target=handle_client, args=(client_socket, addr))
            # Daemon threads will automatically exit when the main program stops
            thread.daemon = True 
            thread.start()
            
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Server is shutting down.")
    except Exception as e:
        print(f"[ERROR] Server error: {e}")
    finally:
        server_socket.close()

if __name__ == "__main__":
    start_server()
