"""
============================================================
  ChatNet — Dummy SMTP Debugging Server
  File : dummy_smtp_server.py
============================================================

Since Python 3.12 removed the built-in `smtpd` module, this 
script acts as a lightweight replacement for local testing.

It creates a raw TCP socket listening on port 2525 and 
simulates a real SMTP server by correctly responding to the 
standard SMTP handshake commands (HELO, MAIL FROM, RCPT TO, DATA, QUIT).

HOW TO USE IT:
--------------
1. Run this script in its own terminal:
   python dummy_smtp_server.py

2. In a separate terminal, run your smtp_notifier.py to 
   test the notification system.

3. You will see the live SMTP conversation printed here!
"""

import socket
import json
import os
import re
from datetime import datetime

# ─────────────────────────────────────────────────────────
#  SERVER CONFIGURATION & CONSTANTS
# ─────────────────────────────────────────────────────────
HOST = "127.0.0.1"
PORT = 2525

# Path to the JSON file where all received emails are stored persistently
EMAILS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emails.json")

# ─────────────────────────────────────────────────────────
#  PERSISTENCE HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────
def extract_email(header_val):
    """
    Extracts a clean email address from a header value.
    Supports formats like 'Name <email@domain.com>' and 'email@domain.com'.
    """
    if not header_val:
        return ""
    # Look for anything inside angle brackets '<' and '>'
    match = re.search(r'<(.*?)>', header_val)
    if match:
        return match.group(1).strip()
    return header_val.strip()

def load_emails():
    """
    Loads the list of stored emails from the emails.json file.
    If the file does not exist, it creates it and initializes it as an empty list [].
    If the file exists but contains corrupted JSON, it re-initializes it gracefully to avoid crashes.
    """
    if not os.path.exists(EMAILS_FILE):
        try:
            with open(EMAILS_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=4)
            return []
        except Exception as e:
            print(f"[SYSTEM ERROR] Could not create {EMAILS_FILE}: {e}")
            return []
            
    try:
        with open(EMAILS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[WARNING] {EMAILS_FILE} is corrupted or empty. Re-initializing it: {e}")
        try:
            with open(EMAILS_FILE, 'w', encoding='utf-8') as f:
                json.dump([], f, indent=4)
        except Exception:
            pass
        return []
    except Exception as e:
        print(f"[SYSTEM ERROR] Failed to read {EMAILS_FILE}: {e}")
        return []

def save_email(email_obj):
    """
    Appends a new email object to the persistent emails.json file.
    """
    emails = load_emails()
    emails.append(email_obj)
    try:
        with open(EMAILS_FILE, 'w', encoding='utf-8') as f:
            json.dump(emails, f, indent=4)
    except Exception as e:
        print(f"[SYSTEM ERROR] Failed to write to {EMAILS_FILE}: {e}")

def parse_and_save_email(data_lines):
    """
    Parses the raw DATA lines of an email to extract 'From', 'To', 'Subject', 
    and 'Body', then saves the resulting structure to emails.json with a timestamp.
    """
    headers = {}
    body_lines = []
    is_body = False
    
    # Loop through each line of the received email data
    for msg in data_lines:
        if not is_body:
            # The headers section ends with the first empty line
            if msg == "":
                is_body = True
                continue
            # Try to parse header lines (e.g. "Subject: ChatNet Mention Alert")
            if ":" in msg:
                key, val = msg.split(":", 1)
                headers[key.strip().lower()] = val.strip()
            else:
                # If there's no colon before the empty line, treat it as part of the body
                body_lines.append(msg)
                is_body = True
        else:
            body_lines.append(msg)
            
    # Extract headers with default fallbacks in case of malformed/missing headers
    from_raw = headers.get("from", "")
    to_raw = headers.get("to", "")
    subject = headers.get("subject", "No Subject")
    
    # Clean up the email addresses
    from_email = extract_email(from_raw)
    to_email = extract_email(to_raw)
    
    # Combine body lines into a single string
    body = "\n".join(body_lines).strip()
    
    # Generate a timestamp formatted as YYYY-MM-DD HH:MM:SS
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Create the structured email object
    email_obj = {
        "from": from_email,
        "to": to_email,
        "subject": subject,
        "body": body,
        "timestamp": timestamp
    }
    
    # Save the email persistently
    save_email(email_obj)

# ─────────────────────────────────────────────────────────
#  MAIN SERVER LOOP
# ─────────────────────────────────────────────────────────
def start_dummy_smtp_server():
    # 1. Create a raw TCP socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # Allow port reuse so we don't get "Address already in use" errors if restarted quickly
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # 2. Bind to the local address and port
    server.bind((HOST, PORT))
    
    # 3. Listen for incoming connections (1 at a time for testing is fine)
    server.listen(1)
    
    print("=" * 50)
    print(f"  [SMTP SERVER] Listening on {HOST}:{PORT}")
    print("  Waiting for smtp_notifier.py to connect...")
    print("=" * 50)

    try:
        while True:
            # 4. Accept a new client connection
            client, addr = server.accept()
            print(f"\n[+] Client connected from {addr}")

            # Send the initial welcome greeting (220)
            client.sendall(b"220 Dummy SMTP Server Ready\r\n")

            # Use makefile() to easily read incoming data line-by-line
            # This is crucial for correctly reading the email body during 'DATA'
            reader = client.makefile('r', encoding='utf-8')
            
            in_data_mode = False  # Tracks if we are receiving the email body
            data_lines = []       # Temporarily holds email lines during DATA transmission

            try:
                for line in reader:
                    # Strip trailing whitespace and newlines for easy checking
                    message = line.strip()

                    if in_data_mode:
                        # In DATA mode, the client sends the email body.
                        # It stops when it sends a single dot "." on its own line.
                        if message == ".":
                            print("  [CLIENT] . <End of message>")
                            client.sendall(b"250 Message accepted for delivery\r\n")
                            in_data_mode = False
                            # Parse collected email data and save to emails.json
                            parse_and_save_email(data_lines)
                        else:
                            # Print the email body lines with an indent so it's easy to read
                            print(f"    (email data) {message}")
                            data_lines.append(message)
                        continue

                    # If we are NOT in DATA mode, process normal SMTP commands
                    print(f"  [CLIENT] {message}")

                    # Convert to uppercase for case-insensitive matching of commands
                    upper_msg = message.upper()

                    if upper_msg.startswith("HELO") or upper_msg.startswith("EHLO"):
                        client.sendall(b"250 Hello from Dummy Server\r\n")

                    elif upper_msg.startswith("MAIL FROM"):
                        client.sendall(b"250 Sender OK\r\n")

                    elif upper_msg.startswith("RCPT TO"):
                        client.sendall(b"250 Recipient OK\r\n")

                    elif upper_msg.startswith("DATA"):
                        client.sendall(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                        in_data_mode = True  # Switch to DATA mode for upcoming lines
                        data_lines = []      # Reset lines for a new email

                    elif upper_msg.startswith("QUIT"):
                        client.sendall(b"221 Bye\r\n")
                        break  # End the connection loop

                    else:
                        # Catch-all for unknown commands (so the client doesn't freeze)
                        client.sendall(b"250 OK\r\n")
                        
            except Exception as e:
                print(f"[-] Connection error: {e}")
                        
                client.close()
                print(f"[-] Client {addr} disconnected.")
                
    except KeyboardInterrupt:
        print("\n[!] Shutting down SMTP Server...")
        
    finally:
        server.close()

if __name__ == "__main__":
    start_dummy_smtp_server()