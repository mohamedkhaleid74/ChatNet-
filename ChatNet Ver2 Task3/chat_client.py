import socket
import threading
import time
import sys

def receive_messages(client_socket):
    """
    Continuously listens for messages from the server.
    Runs in a separate thread so the user can type while receiving.
    """
    try:
        # Use makefile() to easily read line-by-line responses from the server
        reader = client_socket.makefile('r', encoding='utf-8')
        while True:
            line = reader.readline()
            if not line:
                print("\n[DISCONNECTED] Server closed the connection.")
                break
                
            line = line.strip()
            
            # 1. Received a broadcasted chat message
            if line.startswith("BROADCAST "):
                message = line[10:]
                # Erase the current input prompt, print the message, and restore the prompt
                print(f"\r{message}")
                print("> ", end="", flush=True)
                
            # 2. Received an echo for our /ping command
            elif line.startswith("PING_ECHO "):
                _, ts = line.split(' ', 1)
                # Calculate Round Trip Time (RTT) in milliseconds
                rtt = (time.time() - float(ts)) * 1000 
                print(f"\r[DIAGNOSTICS] RTT = {rtt:.2f} ms")
                print("> ", end="", flush=True)
                
            # 3. Received an ACK for our /throughput command
            elif line.startswith("THROUGHPUT_ACK "):
                parts = line.split(' ')
                if len(parts) >= 3:
                    size = int(parts[1])
                    ts = float(parts[2])
                    time_taken = time.time() - ts
                    
                    if time_taken > 0:
                        # Throughput in kbps (kilobits per second)
                        # Formula: (size_in_bytes * 8 bits) / time_taken_in_sec / 1000
                        kbps = (size * 8 / time_taken) / 1000
                        print(f"\r[DIAGNOSTICS] Throughput = {kbps:.2f} kbps (Time: {time_taken:.4f}s)")
                    else:
                        print(f"\r[DIAGNOSTICS] Throughput = Infinite (Time too small to measure)")
                print("> ", end="", flush=True)
                
    except Exception as e:
        print(f"\n[ERROR] Connection error: {e}")
    finally:
        # If the reading loop exits, close the socket
        client_socket.close()

def start_client():
    """
    Main function to start the chat client.
    """
    print("=== Welcome to ChatNet Client ===")
    
    # 1. Ask user for connection details
    server_ip = input("Enter Server IP: ").strip()
    port_input = input("Enter Server Port (default 12000): ").strip()
    port = int(port_input) if port_input else 12000
    username = input("Enter Username: ").strip()
    
    if not username:
        print("Username cannot be empty. Exiting.")
        return

    # 2. Connect to the TCP server
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client_socket.connect((server_ip, port))
    except Exception as e:
        print(f"Failed to connect to server at {server_ip}:{port}. Error: {e}")
        return

    # 3. Read and display the welcome message from the server
    try:
        welcome_bytes = client_socket.recv(1024)
        welcome_msg = welcome_bytes.decode('utf-8').strip()
        print(f"\n[SERVER] {welcome_msg}")
    except Exception as e:
        print(f"[ERROR] Failed to read welcome message: {e}")
        client_socket.close()
        return
    
    # 4. Send JOIN message to register the username
    join_msg = f"JOIN {username}\n"
    client_socket.sendall(join_msg.encode('utf-8'))
    
    # 5. Start the background thread to receive messages continuously
    recv_thread = threading.Thread(target=receive_messages, args=(client_socket,))
    recv_thread.daemon = True # Thread exits when main program exits
    recv_thread.start()
    
    print("\n--- You are now in the chatroom ---")
    print("Commands:")
    print("  /ping               - Test connection latency (RTT)")
    print("  /throughput <size>  - Test network throughput (e.g., /throughput 102400)")
    print("  /quit               - Disconnect and exit")
    print("-----------------------------------\n")

    # 6. Main loop for capturing user input and sending messages
    try:
        while True:
            # Simple terminal prompt
            user_input = input("> ").strip()
            
            if not user_input:
                continue
                
            # Handle user commands
            if user_input.lower() in ('/quit', '/exit', '/disconnect'):
                client_socket.sendall("DISCONNECT\n".encode('utf-8'))
                break
                
            elif user_input.lower() == '/ping':
                # Send timestamp to calculate RTT later
                msg = f"PING {time.time()}\n"
                client_socket.sendall(msg.encode('utf-8'))
                
            elif user_input.lower().startswith('/throughput'):
                parts = user_input.split(' ')
                if len(parts) == 2 and parts[1].isdigit():
                    size = int(parts[1])
                    if size <= 0:
                        print("Size must be greater than 0.")
                        continue
                    
                    # Generate a test payload of the given byte size (repeating 'A')
                    payload = 'A' * size
                    # Send size, current timestamp, and payload
                    msg = f"THROUGHPUT {size} {time.time()} {payload}\n"
                    
                    print(f"[SYSTEM] Sending {size} bytes for throughput test...")
                    client_socket.sendall(msg.encode('utf-8'))
                else:
                    print("Usage: /throughput <size_in_bytes>")
                    
            else:
                # Normal chat message
                msg = f"CHAT {user_input}\n"
                client_socket.sendall(msg.encode('utf-8'))
                
    except KeyboardInterrupt:
        print("\n[SYSTEM] Interrupted by user.")
    except Exception as e:
        print(f"\n[ERROR] Sending error: {e}")
    finally:
        # Cleanup when the loop exits
        try:
            client_socket.close()
        except:
            pass
        print("Disconnected from ChatNet.")

if __name__ == "__main__":
    start_client()
