"""
============================================================
  ChatNet — Task 4 : SMTP Email Notification Module
  File : smtp_notifier.py
============================================================

HOW THE SMTP PROTOCOL WORKS
----------------------------
SMTP (Simple Mail Transfer Protocol) is the standard protocol used
for sending emails across the internet. It operates on a simple
request-response model over a TCP connection (typically port 25, 587, or 465).

The client sends text-based commands (like HELO, MAIL FROM), and the 
server replies with a 3-digit status code and a message (e.g., "250 OK").

THE SMTP HANDSHAKE (Delivery Flow)
-----------------------------------
1. Connect   → Client connects to the SMTP server via TCP.
               Server replies: `220 Service Ready`
2. HELO      → Client introduces itself.
               Server replies: `250 OK`
3. MAIL FROM → Client specifies the sender's email address.
               Server replies: `250 OK`
4. RCPT TO   → Client specifies the recipient's email address.
               Server replies: `250 OK`
5. DATA      → Client asks to send the email body.
               Server replies: `354 Start mail input`
6. Body      → Client sends the email headers, a blank line, and the message.
               The message ends with a single dot (`.`) on a new line.
               Server replies: `250 Message accepted`
7. QUIT      → Client disconnects.
               Server replies: `221 Goodbye`

SECURITY NOTES & REAL-WORLD CONSIDERATIONS
-------------------------------------------
1. Why Plaintext is Insecure:
   By default, SMTP sends everything (including emails and passwords) in 
   plain text. Anyone snooping on the network can easily read your data.

2. What is STARTTLS?
   STARTTLS is an SMTP command that takes an insecure plaintext connection 
   and upgrades it to a secure, encrypted connection (TLS/SSL). 

3. How Encryption Protects Credentials:
   Once STARTTLS is initiated, all subsequent commands (especially the `AUTH` 
   command used for logging in) are scrambled, keeping passwords safe.

4. Gmail & App Passwords:
   If you try to use Gmail's SMTP server (smtp.gmail.com), you MUST use 
   STARTTLS and authenticate. Furthermore, Google no longer allows normal 
   account passwords for basic SMTP logins. You must generate a special, 
   16-character "App Password" from your Google Account security settings 
   to authenticate your script.

*Note: For this educational assignment, we use a raw, unencrypted TCP 
socket to demonstrate the core SMTP protocol mechanics. This is meant to 
be tested against a local development SMTP server (like MailHog or 
Python's built-in debugging server) rather than a production server.*
"""

import socket
import re
import os
import json

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# The SMTP server we are connecting to.
# (Using localhost on port 2525 for safe local testing)
SMTP_SERVER = "127.0.0.1"
SMTP_PORT = 2525
SENDER_EMAIL = "notifications@chatnet.local"

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.log")

def log_event(message):
    """
    Writes a timestamped message to server.log AND prints it to console.
    """
    from datetime import datetime
    timestamp = datetime.now().strftime('%H:%M:%S')
    entry = f"[{timestamp}] {message}"
    print(entry)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(entry + '\n')
    except Exception as e:
        print(f"[LOG ERROR] Could not write to log file: {e}")


# ─────────────────────────────────────────────────────────────────────────────
#  HELPER: SEND COMMAND & RECEIVE RESPONSE
# ─────────────────────────────────────────────────────────────────────────────
def send_smtp_command(sock, command, expected_code=None):
    """
    Sends an SMTP command and reads the server's response.
    
    Parameters:
        sock (socket)       : The active TCP socket connected to the server.
        command (str)       : The command to send (e.g., "HELO mypc").
        expected_code (str) : The expected 3-digit success code (e.g., "250").
        
    Raises:
        Exception: If the server replies with an unexpected error code.
    """
    if command:
        print(f"  [Client]  {command.strip()}")
        # SMTP commands must end with \r\n (Carriage Return + Line Feed)
        sock.sendall((command + "\r\n").encode('utf-8'))
    
    # Receive the server's reply
    response = sock.recv(1024).decode('utf-8')
    print(f"  [Server]  {response.strip()}")
    
    if expected_code and not response.startswith(expected_code):
        raise Exception(f"SMTP Error: Expected {expected_code}, got:\n{response}")
        
    return response


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN SMTP NOTIFICATION FUNCTION
# ─────────────────────────────────────────────────────────────────────────────
def send_notification_email(recipient_email, username, original_message):
    """
    Manually connects to an SMTP server and executes the SMTP handshake
    to send an email notification using raw TCP sockets.
    """
    print(f"\n[SYSTEM] Connecting to SMTP server {SMTP_SERVER}:{SMTP_PORT}...")
    
    # 1. Create a raw TCP socket (SOCK_STREAM)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)  # Don't hang forever if the server is down
        sock.connect((SMTP_SERVER, SMTP_PORT))
    except Exception as e:
        print(f"[ERROR] Could not connect to SMTP server: {e}")
        return

    try:
        # Step 1: Read the initial greeting banner from the server (220)
        response = sock.recv(1024).decode('utf-8')
        print(f"  [Server]  {response.strip()}")
        if not response.startswith("220"):
            raise Exception("Server is not ready (did not receive 220).")

        # Step 2: HELO (Introduce ourselves)
        send_smtp_command(sock, "HELO chatnet.local", "250")

        # Step 3: MAIL FROM (Sender address)
        send_smtp_command(sock, f"MAIL FROM:<{SENDER_EMAIL}>", "250")

        # Step 4: RCPT TO (Recipient address)
        send_smtp_command(sock, f"RCPT TO:<{recipient_email}>", "250")

        # Step 5: DATA (Tell the server we are about to send the email body)
        send_smtp_command(sock, "DATA", "354")

        # Step 6: Construct and send the email headers and body
        # Headers are separated from the body by an empty line (\r\n)
        email_data = (
            f"From: ChatNet System <{SENDER_EMAIL}>\r\n"
            f"To: {recipient_email}\r\n"
            f"Subject: ChatNet Mention/Private Message Alert\r\n"
            "\r\n"  # Empty line separating headers and body
            f"Hello {username},\r\n\r\n"
            f"You received a new notification in ChatNet:\r\n"
            f"\"{original_message}\"\r\n"
            "\r\n"
            "." # A single dot on its own line tells the server the email is finished
        )
        
        send_smtp_command(sock, email_data, "250")
        
        # Log successful delivery directly using our new log_event method
        log_event(f"[SMTP] Email notification sent to {recipient_email}")

        # Step 7: QUIT (Close the connection gracefully)
        send_smtp_command(sock, "QUIT", "221")

    except Exception as e:
        print(f"[ERROR] Failed during SMTP transaction: {e}")
        log_event(f"[SMTP ERROR] Failed to send email to {recipient_email}: {e}")
    finally:
        sock.close()


# ─────────────────────────────────────────────────────────────────────────────
#  LIVE MONITOR MODE (Task 4 Upgrade)
# ─────────────────────────────────────────────────────────────────────────────
def live_monitor_mode():
    import time
    
    print("\n[SMTP MONITOR]")
    print("Watching for live events...\n")
    
    event_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smtp_events.log")
    
    # Ensure file exists so we can read it without crashing
    if not os.path.exists(event_file):
        with open(event_file, 'w', encoding='utf-8') as f:
            pass
            
    try:
        with open(event_file, 'r', encoding='utf-8') as f:
            # Seek to the end of the file to ignore past events
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.5)
                    continue
                    
                line = line.strip()
                if not line:
                    continue
                    
                try:
                    event = json.loads(line)
                    event_type = event.get("type", "unknown")
                    target = event.get("target", "unknown")
                    target_email = event.get("email", "unknown@example.com")
                    message = event.get("message", "")
                    
                    print("\n" + "=" * 50)
                    print(f"[SMTP EVENT DETECTED]")
                    print(f"Type: {event_type}")
                    print(f"Target user: {target}")
                    print(f"Sending notification to {target_email}...")
                    print("=" * 50)
                    
                    # Automatically trigger SMTP socket flow
                    send_notification_email(target_email, target, message)
                    print("\nWaiting for next event...\n")
                    
                except json.JSONDecodeError:
                    print(f"[WARNING] Corrupted event detected: {line}")
    except KeyboardInterrupt:
        print("\n[SMTP MONITOR] Stopped by user.")
    except Exception as e:
        print(f"[ERROR] Monitor failed: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  MANUAL TEST MODE (Original Standalone)
# ─────────────────────────────────────────────────────────────────────────────
def manual_test_mode():
    print("\n=" * 50)
    print("  [SMTP TEST MODE]")
    print("=" * 50)
    
    # Load connected users from the JSON file created by the chat server
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "connected_users.json")
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            users = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        users = {}

    if not users:
        print("[!] No users are currently connected.")
        print("    Please start 'chat_server_threaded.py' and connect at least one client.")
    else:
        print("Connected users loaded successfully:")
        for idx, (uname, info) in enumerate(users.items(), 1):
            print(f"  {idx}. {uname}")
            
        print("-" * 50)
        target = input("\nSelect target username: ").strip()
        
        if target not in users:
            print("[ERROR] User not found.")
        else:
            target_email = users[target]["email"]
            msg = input("Enter test message: ").strip()
            
            print(f"\nSending notification to {target_email}...")
            send_notification_email(target_email, target, msg)
            
    print("=" * 50)

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  [SMTP STANDALONE UTILITY]")
    print("=" * 50)
    print("1. Manual test mode")
    print("2. Live monitor mode")
    
    try:
        mode = input("Select mode: ").strip()
        
        if mode == "1":
            manual_test_mode()
        elif mode == "2":
            live_monitor_mode()
        else:
            print("Invalid selection. Exiting.")
    except KeyboardInterrupt:
        print("\nExiting.")
