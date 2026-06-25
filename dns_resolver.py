"""
============================================================
  ChatNet - Task 4 : DNS Resolver Module
  File : dns_resolver.py
============================================================

HOW DNS WORKS (Beginner-Friendly Explanation)
----------------------------------------------
DNS (Domain Name System) is like a phone book for the internet.
When you type "google.com", your computer does NOT know the IP
address directly. It asks a DNS server (like Google's 8.8.8.8)
to look it up and return the answer.

RECURSIVE vs ITERATIVE QUERIES
--------------------------------
  Recursive  → You ask the DNS server and it does ALL the work
               for you, returning the final answer. (Most common)
               Client → DNS Server → (root → TLD → auth) → Client

  Iterative  → The DNS server gives you the address of the NEXT
               server to ask. You keep asking until you find the
               answer. (Used between DNS servers internally)

WHAT IS AN A RECORD?
---------------------
  An "A record" (Address record) maps a hostname to an IPv4 address.
  Example:
    google.com.  →  A record  →  142.250.185.46

  Other record types (not used here):
    AAAA → IPv6 address
    MX   → Mail server
    CNAME → Alias to another hostname
    TXT  → Arbitrary text data

DNS PACKET STRUCTURE (Binary Protocol)
----------------------------------------
  Every DNS message has this layout:

  ┌─────────────────────────────────────────┐
  │  HEADER   (12 bytes, always present)    │
  ├─────────────────────────────────────────┤
  │  QUESTION SECTION  (variable length)    │
  ├─────────────────────────────────────────┤
  │  ANSWER SECTION    (variable length)    │
  ├─────────────────────────────────────────┤
  │  AUTHORITY / ADDITIONAL (not used here) │
  └─────────────────────────────────────────┘

DNS HEADER (12 bytes):
  Bytes 0-1  : Transaction ID  (random 16-bit number to match reply)
  Bytes 2-3  : Flags           (QR, Opcode, AA, TC, RD, RA, Z, RCODE)
  Bytes 4-5  : QDCOUNT         (number of questions, usually 1)
  Bytes 6-7  : ANCOUNT         (number of answers in response)
  Bytes 8-9  : NSCOUNT         (authority records, 0 in our query)
  Bytes 10-11: ARCOUNT         (additional records, 0 in our query)

FLAGS BYTE breakdown:
  QR     (1 bit)  : 0=Query, 1=Response
  Opcode (4 bits) : 0=Standard query
  AA     (1 bit)  : Authoritative Answer
  TC     (1 bit)  : TrunCated
  RD     (1 bit)  : Recursion Desired (we set this to 1)
  RA     (1 bit)  : Recursion Available (set by server in response)
  Z      (3 bits) : Reserved, must be 0
  RCODE  (4 bits) : Response code (0=no error)

DNS QUESTION SECTION:
  QNAME  : The domain encoded as length-prefixed labels
           "google.com" → \x06google\x03com\x00
           Each label is prefixed by its length byte.
           The final \x00 signals end of the name.
  QTYPE  : 2 bytes → Type of record (1 = A record / IPv4)
  QCLASS : 2 bytes → Class (1 = IN = Internet)

DNS ANSWER SECTION (in response):
  NAME    : 2 bytes pointer (0xC0 0x0C) back to question name
  TYPE    : 2 bytes (1 = A record)
  CLASS   : 2 bytes (1 = IN)
  TTL     : 4 bytes (time-to-live in seconds)
  RDLENGTH: 2 bytes (length of RDATA, 4 for IPv4)
  RDATA   : 4 bytes (the actual IPv4 address, one byte per octet)
"""

import socket   # For sending/receiving UDP datagrams
import sys      # For stdout reconfiguration on Windows

# ── Fix Windows terminal encoding so ASCII-safe prints work fine ─────────────
# Without this, printing certain characters may raise UnicodeEncodeError.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import struct   # For packing/unpacking binary data
import random   # For generating a random transaction ID
import time     # For timeout tracking


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

# List of DNS servers to try in order (fallback if first one fails)
DNS_SERVERS = [
    "8.8.8.8",   # Google Public DNS (primary)
    "1.1.1.1",   # Cloudflare DNS (fallback)
]

DNS_PORT    = 53      # Standard DNS port (UDP)
TIMEOUT_SEC = 5       # How long to wait for a DNS reply (seconds)
QTYPE_A     = 1       # Query type for A record (IPv4 address)
QCLASS_IN   = 1       # Query class Internet


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 1 — Encode a domain name into DNS wire format
# ─────────────────────────────────────────────────────────────────────────────

def encode_domain_name(domain):
    """
    Converts a human-readable domain name into the DNS binary label format.

    Example:
        "google.com"   →  b'\\x06google\\x03com\\x00'
        "example.co.uk"→  b'\\x07example\\x02co\\x02uk\\x00'

    Each part (label) between dots is prefixed with its length as 1 byte.
    The sequence ends with a null byte (\\x00) to indicate root.

    Parameters:
        domain (str): The hostname to encode, e.g. "google.com"

    Returns:
        bytes: The encoded domain name in DNS wire format.
    """
    encoded = b""                         # We'll build the result here

    # Split "google.com" → ["google", "com"]
    for label in domain.strip(".").split("."):
        # Encode label length as one byte, then the label itself as ASCII bytes
        encoded += bytes([len(label)]) + label.encode("ascii")

    encoded += b"\x00"                   # Null byte = end of domain name
    return encoded


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 2 — Build the full DNS query packet
# ─────────────────────────────────────────────────────────────────────────────

def build_dns_query(domain):
    """
    Constructs a complete DNS query packet (header + question section) as bytes.

    Packet layout:
        [HEADER 12 bytes][QNAME variable][QTYPE 2 bytes][QCLASS 2 bytes]

    Parameters:
        domain (str): The domain name to query, e.g. "google.com"

    Returns:
        tuple: (packet_bytes, transaction_id)
               packet_bytes  → the raw bytes to send over UDP
               transaction_id → 16-bit int we use to verify the reply matches
    """

    # ── Transaction ID ──────────────────────────────────────────────────────
    # A random 16-bit number. The server echoes it back so we can confirm
    # the reply belongs to our query (not a stale or forged packet).
    transaction_id = random.randint(0, 65535)

    # ── Flags ───────────────────────────────────────────────────────────────
    # 0x0100 in hex means:
    #   QR=0 (query), Opcode=0 (standard), AA=0, TC=0, RD=1 (recursion desired)
    # We want recursion so the server does the full lookup for us.
    flags = 0x0100

    # ── Counts ──────────────────────────────────────────────────────────────
    qdcount = 1   # We are sending exactly 1 question
    ancount = 0   # No answers in a query
    nscount = 0   # No authority records
    arcount = 0   # No additional records

    # ── Pack the 12-byte header using struct ────────────────────────────────
    # "!" = network byte order (big-endian)
    # "H" = unsigned short (2 bytes) — used for each of the 6 header fields
    header = struct.pack("!HHHHHH",
                         transaction_id,
                         flags,
                         qdcount,
                         ancount,
                         nscount,
                         arcount)

    # ── Build the question section ──────────────────────────────────────────
    qname  = encode_domain_name(domain)          # Encoded domain name
    qtype  = struct.pack("!H", QTYPE_A)          # 2-byte A record type (1)
    qclass = struct.pack("!H", QCLASS_IN)        # 2-byte Internet class (1)

    question = qname + qtype + qclass

    # ── Combine header + question into the full packet ──────────────────────
    packet = header + question

    return packet, transaction_id


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 3 — Parse the DNS response packet
# ─────────────────────────────────────────────────────────────────────────────

def parse_dns_response(response, expected_txid):
    """
    Parses the binary DNS response and extracts the IPv4 address.

    The response has the same header format as the query, followed by
    the question section (echoed back) and then the answer section.

    Parameters:
        response (bytes)    : Raw UDP payload received from the DNS server
        expected_txid (int) : Transaction ID we sent; must match reply

    Returns:
        str or None: The resolved IPv4 address string, or None if not found.

    Raises:
        ValueError: If the transaction ID doesn't match or RCODE != 0
    """

    # ── Minimum sanity check ────────────────────────────────────────────────
    if len(response) < 12:
        raise ValueError("Response too short to be a valid DNS packet.")

    # ── Unpack the 12-byte header ───────────────────────────────────────────
    txid, flags, qdcount, ancount, nscount, arcount = struct.unpack(
        "!HHHHHH", response[:12]
    )

    # ── Verify transaction ID matches our query ──────────────────────────────
    if txid != expected_txid:
        raise ValueError(
            f"Transaction ID mismatch: expected {expected_txid}, got {txid}"
        )

    # ── Check the response code (RCODE) ────────────────────────────────────
    # RCODE is the last 4 bits of the flags field
    rcode = flags & 0x000F   # Mask out lower 4 bits
    if rcode != 0:
        rcode_messages = {
            1: "Format error — query was malformed",
            2: "Server failure — DNS server error",
            3: "Name error (NXDOMAIN) — domain does not exist",
            4: "Not implemented — query type not supported",
            5: "Refused — server refused the query",
        }
        msg = rcode_messages.get(rcode, f"Unknown error (RCODE={rcode})")
        raise ValueError(f"DNS error: {msg}")

    # ── No answers? ─────────────────────────────────────────────────────────
    if ancount == 0:
        return None   # The server found nothing

    # ── Skip past the header (12 bytes) ─────────────────────────────────────
    offset = 12

    # ── Skip the Question Section ───────────────────────────────────────────
    # We need to skip past the echoed question to reach the answer section.
    # The question contains the QNAME (variable) + QTYPE (2) + QCLASS (2).
    for _ in range(qdcount):
        offset = skip_name(response, offset)   # Skip QNAME
        offset += 4                            # Skip QTYPE + QCLASS (4 bytes)

    # ── Parse each Answer Record ─────────────────────────────────────────────
    for _ in range(ancount):
        # NAME field — DNS uses compression pointers (0xC0 xx) to save space.
        # We just skip it using our helper.
        offset = skip_name(response, offset)

        # Each resource record has: TYPE(2) CLASS(2) TTL(4) RDLENGTH(2)
        if offset + 10 > len(response):
            break   # Malformed / truncated packet

        rtype, rclass, ttl, rdlength = struct.unpack(
            "!HHIH", response[offset:offset + 10]
        )
        offset += 10   # Move past these fixed fields

        # ── Check if this answer is an A record (IPv4) ───────────────────
        if rtype == QTYPE_A and rdlength == 4:
            # RDATA for an A record is exactly 4 bytes (one per IPv4 octet)
            ip_bytes = response[offset:offset + 4]
            # Convert 4 raw bytes to dotted-decimal string e.g. "142.250.1.46"
            ip_address = ".".join(str(b) for b in ip_bytes)
            return ip_address

        # Not an A record — skip over RDATA and check the next record
        offset += rdlength

    return None   # No A record found in any answer


# ─────────────────────────────────────────────────────────────────────────────
#  HELPER — Skip a DNS name field (handles compression pointers)
# ─────────────────────────────────────────────────────────────────────────────

def skip_name(data, offset):
    """
    Advances the offset past a DNS name field in a packet.

    DNS names can either be:
      a) A sequence of length-prefixed labels ending in 0x00
      b) A compression pointer: 2 bytes starting with 0xC0 (11 in top 2 bits)
         which points to an earlier location in the packet.

    Parameters:
        data   (bytes): The full DNS packet
        offset (int)  : Current position in the packet

    Returns:
        int: The new offset position after the name field.
    """
    while offset < len(data):
        length = data[offset]

        # ── Compression pointer (top 2 bits = 11) ──────────────────────────
        # 0xC0 = 1100 0000 in binary; if top 2 bits are set, it's a pointer.
        if (length & 0xC0) == 0xC0:
            # The pointer is 2 bytes total; skip both and stop here.
            return offset + 2

        # ── End of name ────────────────────────────────────────────────────
        if length == 0:
            return offset + 1   # Skip the terminating null byte

        # ── Regular label — skip length byte + label bytes ─────────────────
        offset += 1 + length

    return offset


# ─────────────────────────────────────────────────────────────────────────────
#  STEP 4 — Main resolve function (tries multiple DNS servers)
# ─────────────────────────────────────────────────────────────────────────────

def resolve(domain, dns_servers=None, timeout=TIMEOUT_SEC):
    """
    Resolves a domain name to an IPv4 address by sending a raw DNS query
    over UDP to a real DNS server.

    Tries each server in dns_servers in order. Returns the first
    successful result. If all servers fail, raises an exception.

    Parameters:
        domain      (str)       : Hostname to resolve, e.g. "google.com"
        dns_servers (list[str]) : DNS server IPs to try (default: 8.8.8.8, 1.1.1.1)
        timeout     (int/float) : Seconds to wait for a response per server

    Returns:
        str: Resolved IPv4 address, e.g. "142.250.185.46"

    Raises:
        Exception: If all DNS servers fail or domain cannot be resolved.
    """
    if dns_servers is None:
        dns_servers = DNS_SERVERS

    # ── Basic validation — reject obviously invalid inputs ──────────────────
    if not domain or "." not in domain:
        raise ValueError(
            f"'{domain}' does not look like a valid domain name. "
            "Expected something like 'google.com'."
        )

    last_error = None   # Keep track of the most recent error for reporting

    # ── Try each DNS server in turn ─────────────────────────────────────────
    for server_ip in dns_servers:
        print(f"  [DNS] Querying {server_ip}:{DNS_PORT} for '{domain}' ...")

        try:
            # ── Build the DNS query packet ──────────────────────────────────
            packet, txid = build_dns_query(domain)

            # ── Create a UDP socket ─────────────────────────────────────────
            # AF_INET   = IPv4
            # SOCK_DGRAM = UDP (connectionless, like DNS uses)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:

                # Set how long we'll wait for a reply before giving up
                sock.settimeout(timeout)

                # ── Send the query ──────────────────────────────────────────
                # UDP is connectionless — sendto() both sends and addresses.
                sock.sendto(packet, (server_ip, DNS_PORT))

                # ── Wait for the response ────────────────────────────────────
                # DNS responses are always under 512 bytes for standard queries
                # (UDP payload limit for DNS without EDNS).
                response, _ = sock.recvfrom(512)

            # ── Parse the binary response ───────────────────────────────────
            ip = parse_dns_response(response, txid)

            if ip:
                return ip   # ✓ Successfully resolved!
            else:
                last_error = f"No A record returned by {server_ip}"
                print(f"  [DNS] {server_ip} returned no A record.")

        except socket.timeout:
            last_error = f"Timeout waiting for response from {server_ip}"
            print(f"  [DNS] Timeout from {server_ip} — trying next server...")

        except ValueError as e:
            last_error = str(e)
            print(f"  [DNS] Parse error from {server_ip}: {e}")

        except OSError as e:
            last_error = str(e)
            print(f"  [DNS] Network error reaching {server_ip}: {e}")

    # ── All servers failed ───────────────────────────────────────────────────
    raise Exception(
        f"Could not resolve '{domain}'. Last error: {last_error}"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  CHATNET INTEGRATION HELPER
# ─────────────────────────────────────────────────────────────────────────────

def resolve_for_chatnet(hostname):
    """
    Wrapper around resolve() designed for use inside chat_client_v2.py.

    When the user types a hostname instead of an IP at the "Server IP:" prompt,
    this function automatically resolves it to an IPv4 address so the client
    can connect via TCP as normal.

    Usage in chat_client_v2.py:
        from dns_resolver import resolve_for_chatnet

        server_ip = input("Server IP or hostname: ").strip()
        if not server_ip.replace(".", "").isdigit():   # Not a raw IP
            server_ip = resolve_for_chatnet(server_ip)

    Parameters:
        hostname (str): A domain name, e.g. "chatnet.local" or "google.com"

    Returns:
        str: IPv4 address string, or None if resolution failed (with error printed).
    """
    try:
        ip = resolve(hostname)
        print(f"  [DNS] Resolved {hostname} → {ip}")
        return ip
    except Exception as e:
        print(f"  [DNS ERROR] {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  INTERACTIVE DEMO — runs when you execute: python dns_resolver.py
# ─────────────────────────────────────────────────────────────────────────────

def interactive_demo():
    """
    Provides an interactive prompt so you can test DNS resolution directly
    from the terminal without modifying any other code.

    Type a domain name and press Enter to resolve it.
    Type 'quit' or press Ctrl+C to exit.
    """
    print("=" * 55)
    print("  ChatNet DNS Resolver — Task 4")
    print("  Uses raw UDP sockets + manually built DNS packets")
    print("=" * 55)
    print(f"  DNS Servers : {', '.join(DNS_SERVERS)}")
    print(f"  Port        : {DNS_PORT}")
    print(f"  Timeout     : {TIMEOUT_SEC}s per server")
    print("-" * 55)
    print("  Type a domain to resolve it, or 'quit' to exit.")
    print("=" * 55 + "\n")

    # Pre-run a few automatic examples to demonstrate the module
    demo_domains = ["google.com", "github.com", "cloudflare.com"]
    print("[AUTO DEMO] Resolving example domains...\n")
    for d in demo_domains:
        try:
            ip = resolve(d)
            print(f"  [OK]   Resolved {d:<25} ->  {ip}\n")
        except Exception as e:
            print(f"  [FAIL] Failed  {d:<25}    {e}\n")

    print("-" * 55)
    print("[INTERACTIVE] Enter any domain to resolve (or 'quit'):\n")

    # Interactive loop
    while True:
        try:
            domain = input("  Domain > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n[EXIT] Goodbye!")
            break

        if not domain:
            continue

        if domain.lower() in ("quit", "exit", "q"):
            print("[EXIT] Goodbye!")
            break

        try:
            start  = time.time()
            ip     = resolve(domain)
            elapsed = (time.time() - start) * 1000
            print(f"  [OK]  Resolved {domain} -> {ip}  ({elapsed:.1f} ms)\n")
        except Exception as e:
            print(f"  [FAIL] Error: {e}\n")


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    interactive_demo()
