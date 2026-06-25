"""
============================================================
  ChatNet — Task 3 : Upgraded Multithreaded TCP Chat Server
  File : chat_server_threaded.py
============================================================

WHAT IS NEW IN TASK 3 (compared to Task 2)
-------------------------------------------
  ✔ Shared clients dict  : username -> socket  (was socket -> username)
  ✔ threading.Lock()     : protects every access to 'clients'
  ✔ Unique username check: rejects duplicate names with "409 Conflict"
  ✔ /users command       : lists all online users
  ✔ /msg command         : private messages between users
  ✔ /quit command        : graceful disconnect
  ✔ Logging              : writes timestamped events to server.log
  ✔ Thread stats         : active client + thread count printed on connect/quit
  ✔ ALL Task 2 features  : CHAT broadcast, /ping, /throughput still work

HOW MULTITHREADING WORKS HERE
------------------------------
  When a client connects, the server spawns ONE new thread just for that client.
  That thread blocks (waits) for data from its own client without blocking anyone
  else. The main thread keeps accepting new connections freely.

  ┌─────────────────────────────────────────────────────┐
  │  Main Thread                                        │
  │   └── accept() → new client → spawn Thread-1        │
  │                 → new client → spawn Thread-2       │
  │                 → new client → spawn Thread-3 ...   │
  │  Thread-1  →  handle client A (blocking recv loop)  │
  │  Thread-2  →  handle client B (blocking recv loop)  │
  │  Thread-3  →  handle client C (blocking recv loop)  │
  └─────────────────────────────────────────────────────┘

WHY WE NEED A LOCK (threading.Lock)
--------------------------------------
  Multiple threads may try to read/write the 'clients' dictionary at the
  same time. Without protection this causes a "race condition" — a bug
  where two threads corrupt each other's data.

  With a Lock, only ONE thread can enter the 'with clients_lock:' block
  at a time. All others wait their turn.

  Example race condition WITHOUT a lock:
    Thread-A reads  clients = {"alice": ...}
    Thread-B reads  clients = {"alice": ...}   ← same snapshot!
    Thread-A adds   "bob"    → clients = {"alice": ..., "bob": ...}
    Thread-B adds   "carol"  → clients = {"alice": ..., "carol": ...}
                                               ← "bob" is LOST!

  With a Lock that can't happen.
"""

import socket
import threading
import time
import os
import re
from datetime import datetime
import json
import smtp_notifier

# ─────────────────────────────────────────────
#  Server Configuration
# ─────────────────────────────────────────────
HOST = '0.0.0.0'   # Listen on all network interfaces
PORT = 12000        # Same port as Task 2 so existing clients connect normally

# ─────────────────────────────────────────────
#  Shared State  (Task 3 requirement)
#
#  clients dict maps:  username (str) → socket object
#  This reversed mapping (vs Task 2) makes username lookups O(1),
#  which is needed for /msg and /users commands.
# ─────────────────────────────────────────────
clients = {}                     # { username: client_socket }
clients_lock = threading.Lock()  # Protects every read/write of 'clients'

# ─────────────────────────────────────────────
#  Logging Setup
# ─────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.log")

def log(message):
    """
    Writes a timestamped message to server.log AND prints it to console.
    This function is thread-safe because file.write() with a short string
    is atomic on most OS's; we also keep it simple for students.
    """
    timestamp = datetime.now().strftime('%H:%M:%S')
    entry = f"[{timestamp}] {message}"
    print(entry)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(entry + '\n')
    except Exception as e:
        print(f"[LOG ERROR] Could not write to log file: {e}")


# ─────────────────────────────────────────────
#  Helper : send a message to ONE socket safely
# ─────────────────────────────────────────────
def send_to(sock, message):
    """
    Sends a text message to a single socket.
    Appends a newline so the receiver's readline() returns cleanly.
    Returns False if the send failed (broken pipe, etc.).
    """
    try:
        sock.sendall((message + '\n').encode('utf-8'))
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────
#  Broadcast  (Task 2 feature — kept + improved)
# ─────────────────────────────────────────────
def broadcast(message, exclude_username=None):
    """
    Sends 'message' to ALL connected clients.

    exclude_username: if provided, that user does NOT receive the broadcast.
                      Used so a sender doesn't get an echo of their own message.

    Lock is held for the entire loop to guarantee a consistent snapshot
    of the clients dict while we iterate. Without the lock, a client
    could disconnect mid-loop and cause a RuntimeError (dict changed size).
    """
    with clients_lock:
        for uname, info in list(clients.items()):
            if uname == exclude_username:
                continue
            try:
                info["socket"].sendall((message + '\n').encode('utf-8'))
            except Exception:
                pass   # Broken clients are cleaned up by their own thread


# ─────────────────────────────────────────────
#  Remove Client  (Task 2 feature — upgraded)
# ─────────────────────────────────────────────
def remove_client(username):
    """
    Removes a user from the clients dict and closes their socket.
    Must be called with clients_lock NOT already held (it acquires it).
    After removal, announces the departure to remaining users and logs it.
    """
    with clients_lock:
        client_info = clients.pop(username, None)   # Remove safely; None if missing
    if client_info:
        try:
            client_info["socket"].close()
        except Exception:
            pass
    
    # Save the updated users list to JSON for the standalone SMTP tester
    save_users_state()
    
    log(f"{username} disconnected")
    # Tell everyone else this user left
    broadcast(f"SERVER: {username} has left the chat.")
    print_stats()


# ─────────────────────────────────────────────
#  Print live stats (Task 3 requirement)
# ─────────────────────────────────────────────
def print_stats():
    """Displays current active clients and active threads on the server console."""
    active_clients = len(clients)
    active_threads = threading.active_count()  # Includes main thread
    print(f"  ↳ Stats: {active_clients} client(s) online | "
          f"{active_threads} thread(s) active (incl. main)")


# ─────────────────────────────────────────────
#  Export Shared User State (Task 4)
# ─────────────────────────────────────────────
def save_users_state():
    """
    Saves the currently connected users (without sockets) to a JSON file.
    This allows the standalone smtp_notifier.py to read live user data
    without needing complex inter-process communication.
    """
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "connected_users.json")
    exported_data = {}
    
    with clients_lock:
        for uname, info in clients.items():
            exported_data[uname] = {
                "email": info["email"],
                "ip": info["ip"]
            }
            
    try:
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(exported_data, f, indent=4)
    except Exception as e:
        log(f"[ERROR] Could not save users state: {e}")


# ─────────────────────────────────────────────
#  Shared SMTP Event Queue (Task 4)
# ─────────────────────────────────────────────
def log_smtp_event(event_type, target, email, message):
    """
    Appends a lightweight SMTP event to the shared event file.
    Used by the standalone SMTP monitor mode.
    """
    event_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smtp_events.log")
    event = {
        "type": event_type,
        "target": target,
        "email": email,
        "message": message,
        "timestamp": datetime.now().strftime('%H:%M:%S')
    }
    try:
        with open(event_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + '\n')
    except Exception as e:
        log(f"[ERROR] Could not write to smtp_events.log: {e}")


# ─────────────────────────────────────────────
#  Client Handler  — runs in its OWN thread
# ─────────────────────────────────────────────
def handle_client(client_socket, addr):
    """
    Entry point for each client's dedicated thread.

    FLOW:
      1. Send welcome banner
      2. Read JOIN <username>
      3. Check for duplicate username  → reject with 409 if taken
      4. Register user in 'clients' dict
      5. Main message loop (CHAT / PING / THROUGHPUT / /users / /msg / /quit)
      6. On exit → remove user, notify others
    """
    log(f"New TCP connection from {addr}")

    username = None   # Will be set after successful JOIN

    try:
        # ── Step 1: Welcome ──────────────────────────────────────────────
        send_to(client_socket, "200 OK ; Connected to ChatNet Server (Task 3)")

        # Use makefile() for convenient line-by-line reading
        reader = client_socket.makefile('r', encoding='utf-8')

        # ── Step 2: Receive JOIN ─────────────────────────────────────────
        first_line = reader.readline()
        if not first_line or not first_line.strip().upper().startswith('JOIN '):
            log(f"[ERROR] Invalid handshake from {addr}. Closing.")
            client_socket.close()
            return

        # Handshake expects: JOIN <username> <email>
        parts = first_line.strip().split(' ', 2)
        if len(parts) < 3:
            send_to(client_socket, "400 Bad Request ; Username and email required")
            client_socket.close()
            return

        username = parts[1].strip()
        email = parts[2].strip()

        if not username or not email:
            send_to(client_socket, "400 Bad Request ; Username and email cannot be empty")
            client_socket.close()
            return

        # ── Step 3: Unique username check (Task 3) ───────────────────────
        #
        # We acquire the lock to safely CHECK and then INSERT atomically.
        # If we checked outside the lock, two users could both pass the
        # check before either inserts — a classic TOCTOU race condition.
        with clients_lock:
            if username in clients:
                # Username taken → send 409 and drop the connection
                send_to(client_socket, "409 Conflict ; Username already exists")
                log(f"[REJECTED] Duplicate username '{username}' from {addr}")
                client_socket.close()
                return
            # Safe to add — we're still inside the lock
            clients[username] = {
                "socket": client_socket,
                "email": email,
                "ip": addr[0]
            }

        # Save the updated users list to JSON for the standalone SMTP tester
        save_users_state()

        log(f"{username} connected from {addr}")
        send_to(client_socket, f"WELCOME {username} ; You joined the chatroom!")

        # Tell everyone else this user joined
        broadcast(f"SERVER: {username} has joined the chat!", exclude_username=username)
        print_stats()

        # ── Step 4: Main message loop ────────────────────────────────────
        while True:
            line = reader.readline()
            if not line:
                # Empty readline = client disconnected (TCP FIN received)
                break

            line = line.strip()
            if not line:
                continue

            # ── /quit — Graceful Disconnect (Task 3) ──────────────────
            if line.upper() in ('DISCONNECT', '/QUIT'):
                send_to(client_socket, "SERVER: Goodbye!")
                break

            # ── CHAT — Public Broadcast (Task 2, kept) ────────────────
            elif line.startswith('CHAT '):
                message = line[5:]
                timestamp = datetime.now().strftime('%H:%M:%S')
                formatted = f"BROADCAST [{timestamp}] {username}: {message}"
                broadcast(formatted)
                log(f"CHAT from {username}: {message}")

                # ── Detect Mentions and Send Emails (Task 4) ───────────
                mentions = set(re.findall(r'@(\w+)', message))
                if mentions:
                    with clients_lock:
                        for target in mentions:
                            target_info = clients.get(target)
                            if target_info:
                                target_email = target_info["email"]
                                notification_msg = f"Mentioned by {username} in public chat: {message}"
                                # Log event for Live Monitor mode
                                log_smtp_event("mention", target, target_email, notification_msg)
                                # Send via Integrated mode
                                threading.Thread(
                                    target=smtp_notifier.send_notification_email,
                                    args=(target_email, target, notification_msg),
                                    daemon=True
                                ).start()

            # ── /users — Active Users List (Task 3) ───────────────────
            elif line.upper() == 'CMD_USERS':
                with clients_lock:
                    user_list = list(clients.keys())
                response = "Online Users:\n" + "\n".join(f"  - {u}" for u in user_list)
                send_to(client_socket, f"SERVER_MSG {response}")

            # ── /msg — Private Message (Task 3) ───────────────────────
            elif line.startswith('CMD_MSG '):
                # Protocol: CMD_MSG <recipient> <message text>
                rest = line[8:]                        # Strip "CMD_MSG "
                parts = rest.split(' ', 1)
                if len(parts) < 2:
                    send_to(client_socket, "SERVER_ERR Usage: /msg <username> <message>")
                    continue

                recipient, private_msg = parts[0], parts[1]

                with clients_lock:
                    recipient_info = clients.get(recipient)

                if recipient_info is None:
                    send_to(client_socket, f"SERVER_ERR User '{recipient}' not found or offline.")
                else:
                    recipient_sock = recipient_info["socket"]
                    recipient_email = recipient_info["email"]
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    # Send to recipient
                    send_to(recipient_sock,
                            f"PRIVATE [{timestamp}] {username} → you: {private_msg}")
                    # Confirm to sender
                    send_to(client_socket,
                            f"PRIVATE [{timestamp}] you → {recipient}: {private_msg}")
                    log(f"PRIVATE {username} → {recipient}: {private_msg}")

                    # ── Send Email for Private Message (Task 4) ──────────
                    notification_msg = f"Private message from {username}: {private_msg}"
                    # Log event for Live Monitor mode
                    log_smtp_event("private_message", recipient, recipient_email, notification_msg)
                    # Send via Integrated mode
                    threading.Thread(
                        target=smtp_notifier.send_notification_email,
                        args=(recipient_email, recipient, notification_msg),
                        daemon=True
                    ).start()

            # ── CMD_SENDFILE — UDP File Transfer (IP Resolution) ──────────
            elif line.startswith('CMD_SENDFILE '):
                rest = line[13:].strip()
                parts = rest.split(' ', 1)
                if len(parts) < 2:
                    send_to(client_socket, "SERVER_ERR Usage: /sendfile <filename> <username>")
                    continue
                filename, recipient = parts[0], parts[1]
                
                with clients_lock:
                    recipient_info = clients.get(recipient)
                    
                if not recipient_info:
                    send_to(client_socket, f"SERVER_ERR User '{recipient}' not found or offline.")
                else:
                    recipient_ip = recipient_info["ip"]
                    # Send IP back to sender so they can start UDP transfer directly
                    send_to(client_socket, f"FILE_IP {filename} {recipient_ip}")
                    log(f"FILE TRANSFER requested by {username} to {recipient} (IP resolved to {recipient_ip})")

            # ── PING — RTT Diagnostic (Task 2, kept) ──────────────────
            elif line.startswith('PING '):
                _, ts = line.split(' ', 1)
                send_to(client_socket, f"PING_ECHO {ts}")

            # ── THROUGHPUT — Bandwidth Test (Task 2, kept) ────────────
            elif line.startswith('THROUGHPUT '):
                parts = line.split(' ', 3)
                if len(parts) >= 3:
                    size = parts[1]
                    ts   = parts[2]
                    # Echo back only the metadata, NOT the payload (saves bandwidth)
                    send_to(client_socket, f"THROUGHPUT_ACK {size} {ts}")

            else:
                # Unknown command — ignore silently (keeps protocol extensible)
                pass

    except Exception as e:
        log(f"[ERROR] Exception handling {addr}: {e}")
    finally:
        # ── Cleanup — always runs even if an exception occurred ────────
        if username:
            remove_client(username)
        else:
            # Username was never set (handshake failed) — just close socket
            try:
                client_socket.close()
            except Exception:
                pass


# ─────────────────────────────────────────────
#  Server Startup
# ─────────────────────────────────────────────
def start_server():
    """
    Creates the server socket, binds to HOST:PORT, and enters the
    accept loop. Each accepted connection gets its own daemon thread.
    """
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server_socket.bind((HOST, PORT))
        server_socket.listen(10)   # Queue up to 10 pending connections

        # Detect the machine's IP for display
        hostname  = socket.gethostname()
        server_ip = socket.gethostbyname(hostname)

        print("=" * 50)
        print("  ChatNet Server — Task 3 (Multithreaded)")
        print(f"  Hostname : {hostname}")
        print(f"  IP       : {server_ip}")
        print(f"  Port     : {PORT}")
        print(f"  Log file : {LOG_FILE}")
        print("=" * 50)
        log("Server started and listening for connections")

        while True:
            client_socket, addr = server_socket.accept()

            # Create a dedicated thread for this client.
            # daemon=True means the thread dies automatically when the
            # main program exits (no need for manual cleanup on Ctrl+C).
            t = threading.Thread(
                target=handle_client,
                args=(client_socket, addr),
                daemon=True
            )
            t.start()

    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Ctrl+C received. Server stopping.")
        log("Server shutdown by operator")
    except Exception as e:
        print(f"[FATAL] Server error: {e}")
        log(f"[FATAL] {e}")
    finally:
        server_socket.close()


if __name__ == "__main__":
    start_server()
