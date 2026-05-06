"""
============================================================
  ChatNet — Task 3 : Upgraded Chat Client
  File : chat_client_v2.py
============================================================

WHAT IS NEW IN TASK 3 (compared to Task 2 chat_client.py)
-----------------------------------------------------------
  ✔ /users command  → asks server for the online user list
  ✔ /msg command    → sends a private message to one user
  ✔ /sendfile       → triggers UDP file transfer via file_sender.py
  ✔ PRIVATE prefix  → displays private messages cleanly
  ✔ SERVER_MSG      → displays server info replies (e.g. user list)
  ✔ SERVER_ERR      → displays server error replies
  ✔ 409 Conflict    → detects and shows duplicate-username rejection
  ✔ WELCOME         → shows personalised welcome on join

  ALL Task 2 features (BROADCAST, /ping, /throughput) still work.

THREADING IN THE CLIENT
------------------------
  There are two threads:
    1. Main Thread   — reads user keyboard input and sends commands.
    2. Recv Thread   — listens for incoming server messages continuously.

  Without the recv thread the user could not receive a message while
  they are typing (the two operations would block each other).
"""

import socket
import threading
import time
import subprocess
import sys
import os


# ─────────────────────────────────────────────────────────
#  Receive Thread — runs in background, prints all inbound
# ─────────────────────────────────────────────────────────
def receive_messages(client_socket):
    """
    Continuously reads messages from the server and prints them.
    This runs in a SEPARATE thread so the user can type at the same
    time without any interruption.

    Message prefixes defined in the protocol:
      BROADCAST  → public chat message (from another user)
      PING_ECHO  → server echo for /ping RTT calculation
      THROUGHPUT_ACK → server ack for /throughput test
      PRIVATE    → private message (sent to/from /msg)
      SERVER_MSG → informational reply from server (e.g. /users list)
      SERVER_ERR → error reply from server
      SERVER     → general server announcement (join/leave notices)
      WELCOME    → personalised greeting after JOIN
    """
    try:
        reader = client_socket.makefile('r', encoding='utf-8')
        while True:
            line = reader.readline()
            if not line:
                print("\n[DISCONNECTED] Server closed the connection.")
                break

            line = line.strip()

            # ── Public broadcast chat message ──────────────────────────
            if line.startswith("BROADCAST "):
                print(f"\r{line[10:]}")          # Strip "BROADCAST " prefix
                print("> ", end="", flush=True)

            # ── Ping echo (Task 2) ─────────────────────────────────────
            elif line.startswith("PING_ECHO "):
                _, ts = line.split(' ', 1)
                rtt = (time.time() - float(ts)) * 1000
                print(f"\r[PING] RTT = {rtt:.2f} ms")
                print("> ", end="", flush=True)

            # ── Throughput ACK (Task 2) ────────────────────────────────
            elif line.startswith("THROUGHPUT_ACK "):
                parts = line.split(' ')
                if len(parts) >= 3:
                    size      = int(parts[1])
                    ts        = float(parts[2])
                    elapsed   = time.time() - ts
                    if elapsed > 0:
                        kbps = (size * 8 / elapsed) / 1000
                        print(f"\r[THROUGHPUT] {kbps:.2f} kbps  (elapsed: {elapsed:.4f}s)")
                    else:
                        print("\r[THROUGHPUT] Too fast to measure!")
                print("> ", end="", flush=True)

            # ── Private message (Task 3) ───────────────────────────────
            elif line.startswith("PRIVATE "):
                print(f"\r💬 {line[8:]}")        # Strip "PRIVATE " prefix
                print("> ", end="", flush=True)

            # ── Server info reply (e.g. /users result) (Task 3) ───────
            elif line.startswith("SERVER_MSG "):
                print(f"\r[SERVER]\n{line[11:]}")   # Strip "SERVER_MSG "
                print("> ", end="", flush=True)

            # ── Server error reply (Task 3) ────────────────────────────
            elif line.startswith("SERVER_ERR "):
                print(f"\r[!] {line[11:]}")
                print("> ", end="", flush=True)

            # ── General server announcement (join/leave) ───────────────
            elif line.startswith("SERVER:"):
                print(f"\r*** {line} ***")
                print("> ", end="", flush=True)

            # ── Welcome message on first connect ──────────────────────
            elif line.startswith("WELCOME "):
                print(f"\r[SERVER] {line[8:]}")
                print("> ", end="", flush=True)

            # ── 409 Conflict — username taken ──────────────────────────
            elif line.startswith("409"):
                print(f"\r[ERROR] {line}")
                # The server closed the connection; stop the recv loop
                break

            # ── 200 OK — initial welcome banner ───────────────────────
            elif line.startswith("200"):
                print(f"\r[SERVER] {line}")

            # ── Anything else — print raw ──────────────────────────────
            else:
                if line:
                    print(f"\r[RAW] {line}")
                    print("> ", end="", flush=True)

    except Exception as e:
        print(f"\n[ERROR] Receive error: {e}")
    finally:
        client_socket.close()


# ─────────────────────────────────────────────────────────
#  File Transfer Trigger
# ─────────────────────────────────────────────────────────
def trigger_file_send(filename, recipient, server_ip):
    """
    Spawns file_sender.py in a background subprocess.

    Why subprocess instead of in-process?
    ● file_sender.py is a standalone script (Task 3 requirement).
    ● Running it in a subprocess keeps the chat client responsive
      while the file transfer is happening in the background.
    ● The receiver must already be running file_receiver.py.

    The sender connects to the recipient's machine directly on UDP port 13000.
    In a real system the server would relay the target IP; for simplicity we
    send to the same server IP (works when server and recipient share a machine
    in a lab environment).
    """
    sender_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "file_sender.py"
    )
    if not os.path.exists(sender_script):
        print("[ERROR] file_sender.py not found in the same directory.")
        return

    print(f"[FILE] Starting UDP transfer of '{filename}' to '{recipient}'...")
    # Launch the sender as a detached subprocess so the chat keeps working
    subprocess.Popen(
        [sys.executable, sender_script, filename, server_ip],
        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
    )


# ─────────────────────────────────────────────────────────
#  Main Client
# ─────────────────────────────────────────────────────────
def start_client():
    """
    Connects to the ChatNet server, registers a username, then enters
    the interactive command loop.

    Commands supported:
      /ping                    — measure round-trip time (Task 2)
      /throughput <bytes>      — measure bandwidth (Task 2)
      /users                   — list online users (Task 3)
      /msg <user> <text>       — private message (Task 3)
      /sendfile <file> <user>  — UDP file transfer (Task 3)
      /quit                    — disconnect gracefully (Task 3)
    """
    print("=" * 45)
    print("  ChatNet Client — Task 3")
    print("=" * 45)

    # ── Connection details ─────────────────────────────────────────────
    server_ip  = input("Server IP   : ").strip()
    port_input = input("Server Port (default 12000): ").strip()
    port       = int(port_input) if port_input else 12000
    username   = input("Username    : ").strip()

    if not username:
        print("[ERROR] Username cannot be empty.")
        return

    # ── Connect via TCP ────────────────────────────────────────────────
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client_socket.connect((server_ip, port))
    except Exception as e:
        print(f"[ERROR] Could not connect to {server_ip}:{port} → {e}")
        return

    # ── Start background receive thread ────────────────────────────────
    recv_thread = threading.Thread(
        target=receive_messages,
        args=(client_socket,),
        daemon=True   # Auto-exits when main thread exits
    )
    recv_thread.start()

    # ── Wait briefly so the 200 OK banner prints before our JOIN ───────
    time.sleep(0.1)

    # ── Send JOIN ──────────────────────────────────────────────────────
    client_socket.sendall(f"JOIN {username}\n".encode('utf-8'))

    # Give the server a moment to respond (409 or WELCOME)
    time.sleep(0.2)

    # ── Print help ─────────────────────────────────────────────────────
    print("\n--- You are now in the chatroom ---")
    print("Commands:")
    print("  /ping                       - Measure RTT latency")
    print("  /throughput <bytes>         - Measure bandwidth (e.g. /throughput 102400)")
    print("  /users                      - List online users")
    print("  /msg <username> <message>   - Send a private message")
    print("  /sendfile <file> <username> - Send a file via UDP")
    print("  /quit                       - Disconnect and exit")
    print("  <anything else>             - Send as public chat message")
    print("-----------------------------------\n")

    # ── Main input loop ────────────────────────────────────────────────
    try:
        while True:
            user_input = input("> ").strip()
            if not user_input:
                continue

            # ── /quit — graceful disconnect ────────────────────────────
            if user_input.lower() in ('/quit', '/exit', '/disconnect'):
                client_socket.sendall("DISCONNECT\n".encode('utf-8'))
                break

            # ── /ping — RTT test (Task 2) ──────────────────────────────
            elif user_input.lower() == '/ping':
                msg = f"PING {time.time()}\n"
                client_socket.sendall(msg.encode('utf-8'))

            # ── /throughput — bandwidth test (Task 2) ─────────────────
            elif user_input.lower().startswith('/throughput'):
                parts = user_input.split()
                if len(parts) == 2 and parts[1].isdigit():
                    size    = int(parts[1])
                    payload = 'A' * size
                    msg     = f"THROUGHPUT {size} {time.time()} {payload}\n"
                    print(f"[SYSTEM] Sending {size} bytes for throughput test…")
                    client_socket.sendall(msg.encode('utf-8'))
                else:
                    print("Usage: /throughput <size_in_bytes>")

            # ── /users — list online users (Task 3) ───────────────────
            elif user_input.lower() == '/users':
                client_socket.sendall("CMD_USERS\n".encode('utf-8'))

            # ── /msg — private message (Task 3) ───────────────────────
            elif user_input.lower().startswith('/msg '):
                rest = user_input[5:].strip()       # Everything after "/msg "
                parts = rest.split(' ', 1)
                if len(parts) < 2:
                    print("Usage: /msg <username> <message>")
                else:
                    recipient, text = parts[0], parts[1]
                    msg = f"CMD_MSG {recipient} {text}\n"
                    client_socket.sendall(msg.encode('utf-8'))

            # ── /sendfile — UDP file transfer (Task 3) ────────────────
            elif user_input.lower().startswith('/sendfile '):
                parts = user_input.split()
                if len(parts) < 3:
                    print("Usage: /sendfile <filename> <recipient_username>")
                else:
                    filename  = parts[1]
                    recipient = parts[2]
                    trigger_file_send(filename, recipient, server_ip)

            # ── Normal chat message ────────────────────────────────────
            else:
                msg = f"CHAT {user_input}\n"
                client_socket.sendall(msg.encode('utf-8'))

    except KeyboardInterrupt:
        print("\n[SYSTEM] Interrupted by user.")
    except Exception as e:
        print(f"\n[ERROR] {e}")
    finally:
        try:
            client_socket.close()
        except Exception:
            pass
        print("Disconnected from ChatNet.")


if __name__ == "__main__":
    start_client()
