"""
============================================================
  ChatNet — Task 4 : HTTP Chat Log Server Module
  File : log_server.py
============================================================

HOW HTTP WORKS (Beginner-Friendly Explanation)
----------------------------------------------
HTTP (Hypertext Transfer Protocol) is the language web browsers and
servers use to talk to each other. When you visit a website, your
browser sends an "HTTP Request" to a server. The server reads it,
figures out what you want, and sends back an "HTTP Response"
containing the webpage.

REQUEST/RESPONSE CYCLE
-----------------------
1. Browser connects to the server (using TCP on port 80 or 8080).
2. Browser sends a Request:
     GET /chatlog HTTP/1.1
     Host: localhost:8080
     (empty line)
3. Server processes the request, generating HTML dynamically or reading static files.
4. Server sends a Response:
     HTTP/1.1 200 OK
     Content-Type: text/html
     Content-Length: 125
     (empty line)
     <html><body><h1>Hello</h1></body></html>
5. Server closes the connection.

WHY THREADING IS NEEDED HERE
-----------------------------
Browsers often request multiple files simultaneously (HTML, CSS).
Multiple users can also connect at the same time.
Threading creates a new "worker" for every browser request,
so the main server never gets blocked waiting for one request to finish.
"""

import socket
import threading
import os
import datetime
import json

# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
HOST = '0.0.0.0'         # Listen on all network interfaces
PORT = 8080              # The port the HTTP server will run on
LOG_FILE = 'server.log'  # The file where ChatNet saves chat history
MAX_LINES = 50           # Number of recent messages to show
TEMPLATES_DIR = 'templates'
STATIC_DIR = 'static'


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 1 — Utility Functions
# ─────────────────────────────────────────────────────────────────────────────
def get_current_time():
    """Returns the current formatted timestamp."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def get_recent_logs():
    """
    Reads the ChatNet log file and returns the last MAX_LINES.
    If the file doesn't exist or is empty, returns an empty list.
    """
    if not os.path.exists(LOG_FILE):
        return []

    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        # Get only the last MAX_LINES lines
        return lines[-MAX_LINES:]
    except Exception as e:
        print(f"[ERROR] Could not read log file: {e}")
        return []

def load_template(filename):
    """
    Reads an HTML template from the templates folder.
    Returns a fallback error message if the file is missing.
    """
    path = os.path.join(TEMPLATES_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"[ERROR] Failed to load template {filename}: {e}")
            return "<h1>Server Error: Could not read template.</h1>"
    return "<h1>Template Missing</h1>"

def generate_logs_html(logs):
    """
    Formats raw logs into HTML div elements for injection into logs.html.
    """
    if not logs:
        return "<p class='no-logs'>No logs found. Is the chat server running?</p>"
    
    html_logs = []
    for line in logs:
        line = line.strip()
        # Basic sanitization to prevent HTML injection if users typed <script>
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html_logs.append(f"<div class='log-entry'><span class='log-message'>{line}</span></div>")
        
    return "\n".join(html_logs)


EMAILS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emails.json")

def load_emails_for_server():
    """
    Loads emails from emails.json.
    If the file doesn't exist or is corrupted, returns None.
    """
    if not os.path.exists(EMAILS_FILE):
        return None
    try:
        with open(EMAILS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Could not load emails: {e}")
        return None

def generate_inbox_html(emails):
    """
    Formats the list of emails into an HTML table.
    Handles empty lists, None, missing fields, etc. gracefully.
    """
    if not emails:
        return "<p class='no-emails'>No emails available.</p>"
        
    html_parts = []
    html_parts.append("<table class='inbox-table'>")
    html_parts.append("<thead><tr><th>ID</th><th>From</th><th>To</th><th>Subject</th><th>Time</th><th>Action</th></tr></thead>")
    html_parts.append("<tbody>")
    
    for idx, email in enumerate(emails, 1):
        # Gracefully handle missing/empty fields
        email_from = email.get("from", "Unknown Sender")
        email_to = email.get("to", "Unknown Recipient")
        email_subject = email.get("subject", "No Subject")
        email_time = email.get("timestamp", "Unknown Time")
        
        # Basic HTML sanitization to prevent injection
        email_from = email_from.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        email_to = email_to.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        email_subject = email_subject.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        email_time = email_time.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Fully clickable row redirecting to /inbox/<id>
        html_parts.append(f"<tr onclick=\"window.location.href='/inbox/{idx}';\" style='cursor: pointer;'>")
        html_parts.append(f"<td class='email-id'>{idx}</td>")
        html_parts.append(f"<td><span class='badge'>{email_from}</span></td>")
        html_parts.append(f"<td>{email_to}</td>")
        html_parts.append(f"<td><span class='subject-text'>{email_subject}</span></td>")
        html_parts.append(f"<td class='time-col'>{email_time}</td>")
        # Direct Action link, stopping event propagation so the row click is not doubly-triggered
        html_parts.append(f"<td><a href='/inbox/{idx}' class='view-link' onclick='event.stopPropagation();'>View</a></td>")
        html_parts.append("</tr>")
        
    html_parts.append("</tbody></table>")
    return "\n".join(html_parts)


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 2 — HTTP Response Helpers
# ─────────────────────────────────────────────────────────────────────────────
def send_response(client_socket, status_code, content_type, body_bytes):
    """
    Helper function to send standard HTTP responses back to the browser.
    Takes the HTTP body as bytes to handle both text (HTML) and binary files.
    """
    if status_code == 200:
        status_line = "HTTP/1.1 200 OK\r\n"
    elif status_code == 404:
        status_line = "HTTP/1.1 404 Not Found\r\n"
    else:
        status_line = f"HTTP/1.1 {status_code} Unknown\r\n"
        
    headers = (
        f"{status_line}"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "Connection: close\r\n"
        "\r\n"  # Crucial empty line separating headers from body!
    )
    
    client_socket.sendall(headers.encode('utf-8') + body_bytes)

def send_404(client_socket):
    """
    Sends the dynamically loaded 404 Error page.
    """
    html = load_template("404.html")
    # Inject dynamic data
    html = html.replace("{{ current_time }}", get_current_time())
    
    send_response(client_socket, 404, "text/html; charset=utf-8", html.encode('utf-8'))

def serve_static_file(client_socket, path):
    """
    Serves static files (like CSS) from the file system.
    """
    # Security: Prevent directory traversal attacks (e.g., ../../../etc/passwd)
    if '..' in path:
        send_404(client_socket)
        return

    # Remove the leading '/' so it becomes a valid relative path on the OS
    filepath = path.lstrip('/')
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            
            # Determine correct content type
            content_type = "text/plain"
            if filepath.endswith('.css'):
                content_type = "text/css"
            elif filepath.endswith('.js'):
                content_type = "application/javascript"
                
            send_response(client_socket, 200, content_type, content)
        except Exception as e:
            print(f"[ERROR] Failed to serve static file {filepath}: {e}")
            send_404(client_socket)
    else:
        send_404(client_socket)


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 3 — Handle Individual Browser Connections
# ─────────────────────────────────────────────────────────────────────────────
def handle_client(client_socket, client_address):
    """
    Runs in a separate thread for every incoming HTTP request.
    It reads the request, determines the route, and responds appropriately.
    """
    ip, port = client_address
    try:
        # Timeout so broken connections don't hang threads forever
        client_socket.settimeout(5.0)

        # 1. Read HTTP request from the browser
        request_data = client_socket.recv(4096).decode('utf-8')
        if not request_data:
            return

        # 2. Parse request line (e.g., "GET /chatlog HTTP/1.1")
        lines = request_data.split('\r\n')
        request_line = lines[0]
        
        parts = request_line.split(' ')
        if len(parts) < 3:
            return

        method = parts[0]
        path = parts[1]

        # Only allow GET requests
        if method != 'GET':
            return
            
        # Ignore favicon safely without logging it to the terminal
        if path == '/favicon.ico':
            send_response(client_socket, 404, "text/plain", b"Not Found")
            return

        print(f"[HTTP] {method} {path} from {ip}")

        # 3. ROUTING
        if path == '/' or path == '/chatlog':
            # Serve Logs Page directly on root and /chatlog
            logs = get_recent_logs()
            html = load_template("logs.html")
            
            # Dynamically replace placeholders in the HTML
            logs_content = generate_logs_html(logs)
            html = html.replace("{{ current_time }}", get_current_time())
            html = html.replace("{{ total_messages }}", str(len(logs)))
            html = html.replace("{{ logs_content }}", logs_content)
            
            send_response(client_socket, 200, "text/html; charset=utf-8", html.encode('utf-8'))
            
        elif path == '/inbox':
            # Serve Inbox page
            emails = load_emails_for_server()
            html = load_template("inbox.html")
            
            total_emails = len(emails) if isinstance(emails, list) else 0
            inbox_content = generate_inbox_html(emails)
            
            html = html.replace("{{ current_time }}", get_current_time())
            html = html.replace("{{ total_emails }}", str(total_emails))
            html = html.replace("{{ inbox_content }}", inbox_content)
            
            send_response(client_socket, 200, "text/html; charset=utf-8", html.encode('utf-8'))
            
        elif path.startswith('/inbox/'):
            # Serve individual email page (e.g. /inbox/1)
            parts_path = path.split('/')
            email_id_str = parts_path[2] if len(parts_path) > 2 else ""
            
            emails = load_emails_for_server()
            
            # Find the email by index (1-based from the user's perspective)
            email_found = None
            if email_id_str.isdigit() and isinstance(emails, list):
                email_idx = int(email_id_str) - 1
                if 0 <= email_idx < len(emails):
                    email_found = emails[email_idx]
                    
            if email_found:
                # Load the template for email details
                html = load_template("email_details.html")
                
                # Extract fields with safe defaults
                email_from = email_found.get("from", "Unknown Sender")
                email_to = email_found.get("to", "Unknown Recipient")
                email_subject = email_found.get("subject", "No Subject")
                email_time = email_found.get("timestamp", "Unknown Time")
                email_body = email_found.get("body", "")
                
                # Sanitize to prevent HTML injection
                email_from = email_from.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                email_to = email_to.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                email_subject = email_subject.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                email_time = email_time.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                email_body = email_body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                
                # Replace template placeholders
                html = html.replace("{{ subject }}", email_subject)
                html = html.replace("{{ from }}", email_from)
                html = html.replace("{{ to }}", email_to)
                html = html.replace("{{ timestamp }}", email_time)
                html = html.replace("{{ body }}", email_body)
                html = html.replace("{{ current_time }}", get_current_time())
                
                send_response(client_socket, 200, "text/html; charset=utf-8", html.encode('utf-8'))
            else:
                # Serve the custom 404 Email Not Found page
                html = load_template("email_404.html")
                html = html.replace("{{ current_time }}", get_current_time())
                send_response(client_socket, 404, "text/html; charset=utf-8", html.encode('utf-8'))
            
        elif path.startswith('/static/'):
            # Serve CSS and other static assets
            serve_static_file(client_socket, path)
            
        else:
            # Unknown path -> 404 Error Page
            send_404(client_socket)

    except socket.timeout:
        pass # Expected if client sends nothing
    except Exception as e:
        print(f"[ERROR] Connection from {ip} failed: {e}")
    finally:
        # 4. Always close the connection
        client_socket.close()


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 4 — Main Server Loop
# ─────────────────────────────────────────────────────────────────────────────
def start_server():
    """
    Initializes the TCP server and continuously accepts incoming connections.
    """
    print("=" * 55)
    print("  ChatNet HTTP Log Server — Task 4 (Upgraded)")
    print("=" * 55)
    print(f"  Listening on : http://localhost:{PORT}")
    print(f"  Log File     : {LOG_FILE}")
    print("=" * 55 + "\n")

    # Create a raw TCP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # Allow immediately reusing the port if restarted
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        # Bind and listen
        server_socket.bind((HOST, PORT))
        server_socket.listen(5)
        print("[SYSTEM] Server is running and waiting for browsers...\n")

        while True:
            # Accept blocks until a browser connects
            client_socket, client_address = server_socket.accept()
            
            # Spawn a worker thread to handle the request so main loop can continue
            client_thread = threading.Thread(
                target=handle_client, 
                args=(client_socket, client_address),
                daemon=True
            )
            client_thread.start()

    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutting down log server...")
    except Exception as e:
        print(f"\n[FATAL] {e}")
    finally:
        server_socket.close()
        print("[SYSTEM] Server closed.")


if __name__ == "__main__":
    start_server()
