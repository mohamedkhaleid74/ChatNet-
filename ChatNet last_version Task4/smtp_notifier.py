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

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION & USER DATABASE
# ─────────────────────────────────────────────────────────────────────────────

# In a real app, this would be a database. For ChatNet, we use a dictionary.
USERS = {
    "ahmed": "ahmed@example.com",
    "mohamed": "mohamed@example.com",
    "alice": "alice@example.com",
    "bob": "bob@example.com"
}

# The SMTP server we are connecting to.
# (Using localhost on port 2525 for safe local testing)
SMTP_SERVER = "127.0.0.1"
SMTP_PORT = 2525
SENDER_EMAIL = "notifications@chatnet.local"


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
            f"Subject: ChatNet Mention Alert\r\n"
            "\r\n"  # Empty line separating headers and body
            f"Hello {username},\r\n\r\n"
            f"You were mentioned in ChatNet:\r\n"
            f"\"{original_message}\"\r\n"
            "\r\n"
            "." # A single dot on its own line tells the server the email is finished
        )
        
        send_smtp_command(sock, email_data, "250")
        print(f"[SYSTEM] Email sent successfully to {recipient_email}")

        # Step 7: QUIT (Close the connection gracefully)
        send_smtp_command(sock, "QUIT", "221")

    except Exception as e:
        print(f"[ERROR] Failed during SMTP transaction: {e}")
    finally:
        sock.close()


# ─────────────────────────────────────────────────────────────────────────────
#  MENTION DETECTOR & INTEGRATION HANDLER
# ─────────────────────────────────────────────────────────────────────────────
def process_chat_message(message_text):
    """
    Parses a chat message. If an @username mention is found, and that user
    exists in our dictionary, it triggers the SMTP notification.
    
    This simulates what the ChatNet server would do when receiving a message.
    """
    # Use regex to find all words starting with '@'
    # Example: "@ahmed hello bro" -> matches ["@ahmed"]
    mentions = re.findall(r'@(\w+)', message_text)
    
    if not mentions:
        return

    # Process each mentioned user
    for username in mentions:
        # Convert to lowercase to match our dictionary keys safely
        username_lower = username.lower()
        
        if username_lower in USERS:
            email_address = USERS[username_lower]
            print(f"\n[SYSTEM] Detected mention for '{username}'. Triggering email to {email_address}...")
            send_notification_email(email_address, username, message_text)
        else:
            print(f"\n[SYSTEM] Ignored mention for '{username}' (User not found in email database).")


# ─────────────────────────────────────────────────────────────────────────────
#  TESTING / DEMONSTRATION
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  ChatNet SMTP Notifier Demo")
    print("=" * 60)
    
    # We will demonstrate the mention detection.
    # To see the actual SMTP commands succeed, run a dummy SMTP server in 
    # another terminal first: 
    #   python -m smtpd -c DebuggingServer -n localhost:2525
    # (Note: smtpd is deprecated in Python 3.11+. You can use the 'aiosmtpd' 
    # package, or just watch the connection fail gracefully if no server is running).
    
    test_messages = [
        "Hey everyone!",
        "@ahmed hello bro",
        "@bob are you coming to the meeting?",
        "@unknown_user this won't trigger an email"
    ]
    
    for msg in test_messages:
        print(f"\nIncoming Message: {msg}")
        process_chat_message(msg)
