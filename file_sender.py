"""
============================================================
  ChatNet — Task 3 : UDP Reliable File Sender
  File : file_sender.py
============================================================

WHAT THIS FILE DOES
--------------------
  Sends a file to a receiver using UDP with Stop-and-Wait ARQ reliability.

WHY UDP FOR FILE TRANSFER?
---------------------------
  TCP already guarantees delivery, so using TCP for file transfer would be
  trivially easy — just send and receive. The goal of this task is to
  LEARN how reliability is built from scratch, which is why we use UDP
  (which provides NO reliability by itself) and implement ARQ manually.

STOP-AND-WAIT ARQ (Automatic Repeat reQuest)
---------------------------------------------
  This is the simplest ARQ protocol:

    Sender                          Receiver
    ──────                          ────────
    Send Packet 1  ─────────────►  Receive Packet 1
                   ◄─────────────  Send ACK 1
    Send Packet 2  ─────────────►  Receive Packet 2
                   ◄─────────────  Send ACK 2
       (packet 3 is lost)
    Send Packet 3  ─────────────►  (LOST — no ACK received)
    [TIMEOUT 2s]
    Retransmit Packet 3 ─────────►  Receive Packet 3
                        ◄─────────  Send ACK 3
    ...

  Rules:
    ● Sender sends ONE packet, then WAITS.
    ● Sender only advances when it receives the correct ACK.
    ● If 2 seconds pass without an ACK → retransmit the same packet.
    ● Receiver ignores duplicate packets (old retransmits that arrive late).

PACKET FORMAT (binary, packed with manual byte operations)
-----------------------------------------------------------
  [ 4 bytes: sequence number (big-endian uint32) ]
  [ 4 bytes: total packets   (big-endian uint32) ]
  [ up to 512 bytes: file payload                ]

  Total maximum UDP datagram size used: 4 + 4 + 512 = 520 bytes.

USAGE
-----
  python file_sender.py <filename> <receiver_ip>

  The receiver must be running:  python file_receiver.py
"""

import socket
import os
import sys
import time

# ─────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────
RECEIVER_PORT = 13000     # UDP port the receiver listens on
CHUNK_SIZE    = 512       # Each packet carries at most 512 bytes of file data
TIMEOUT_SEC   = 2.0       # Seconds to wait for ACK before retransmitting
MAX_RETRIES   = 10        # Give up after this many consecutive failed attempts


def pack_packet(seq_num, total_packets, data_chunk):
    """
    Builds a binary packet:
      Bytes 0-3  : sequence number  (4-byte big-endian unsigned int)
      Bytes 4-7  : total packets    (4-byte big-endian unsigned int)
      Bytes 8+   : file data chunk  (up to 512 bytes)

    We do this manually with int.to_bytes() instead of the 'struct'
    module so beginners can see exactly what is happening byte-by-byte.
    """
    seq_bytes   = seq_num.to_bytes(4, byteorder='big')
    total_bytes = total_packets.to_bytes(4, byteorder='big')
    return seq_bytes + total_bytes + data_chunk    # Concatenate bytes


def send_file(filename, receiver_ip):
    """
    Main function: reads the file, splits it into 512-byte chunks,
    and sends each chunk reliably using Stop-and-Wait ARQ.

    Parameters:
      filename    : path to the file to send
      receiver_ip : IP address of the machine running file_receiver.py
    """

    # ── Verify the file exists ─────────────────────────────────────────
    if not os.path.isfile(filename):
        print(f"[ERROR] File not found: '{filename}'")
        sys.exit(1)

    file_size = os.path.getsize(filename)
    print(f"\n[FILE SENDER] File      : {filename}")
    print(f"[FILE SENDER] Size      : {file_size} bytes")
    print(f"[FILE SENDER] Receiver  : {receiver_ip}:{RECEIVER_PORT}")
    print(f"[FILE SENDER] Chunk size: {CHUNK_SIZE} bytes")

    # ── Read and split the file into chunks ────────────────────────────
    chunks = []
    with open(filename, 'rb') as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)

    total_packets = len(chunks)
    if total_packets == 0:
        print("[ERROR] File is empty. Nothing to send.")
        sys.exit(1)

    print(f"[FILE SENDER] Packets   : {total_packets}")
    print("-" * 50)

    # ── Create UDP socket ──────────────────────────────────────────────
    # SOCK_DGRAM = UDP.  No connection is established; datagrams are just sent.
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Set a timeout on the socket.  After sendto(), if recvfrom() does not
    # return within TIMEOUT_SEC seconds, it raises socket.timeout.
    udp_socket.settimeout(TIMEOUT_SEC)

    start_time = time.time()

    try:
        for seq_num, chunk in enumerate(chunks):
            packet_num   = seq_num + 1    # Human-readable 1-based number
            retries      = 0
            packet_sent  = False

            # ── Stop-and-Wait loop for this one packet ─────────────────
            while not packet_sent:
                if retries >= MAX_RETRIES:
                    print(f"[ABORT] Packet {packet_num}/{total_packets} failed "
                          f"after {MAX_RETRIES} retries. Aborting transfer.")
                    udp_socket.close()
                    sys.exit(1)

                # Build and send the packet
                packet = pack_packet(seq_num, total_packets, chunk)
                udp_socket.sendto(packet, (receiver_ip, RECEIVER_PORT))

                if retries == 0:
                    print(f"  Packet {packet_num}/{total_packets} sent "
                          f"({len(chunk)} bytes payload)")
                else:
                    print(f"  Timeout… retransmitting packet {packet_num}/{total_packets} "
                          f"(retry {retries})")

                # ── Wait for ACK ───────────────────────────────────────
                try:
                    ack_data, _ = udp_socket.recvfrom(64)
                    ack_seq = int.from_bytes(ack_data[:4], byteorder='big')

                    if ack_seq == seq_num:
                        # Correct ACK → advance to next packet
                        print(f"  ACK received for packet {packet_num}")
                        packet_sent = True
                    else:
                        # Wrong ACK (out-of-order) → resend current packet
                        print(f"  [WARN] Wrong ACK {ack_seq}, expected {seq_num}. Resending.")
                        retries += 1

                except socket.timeout:
                    # No ACK within TIMEOUT_SEC → will retransmit at top of loop
                    retries += 1

        # ── All packets sent and acknowledged ─────────────────────────
        elapsed = time.time() - start_time
        print("-" * 50)
        print(f"[FILE SENDER] ✔ File transfer complete!")
        print(f"[FILE SENDER]   Sent {total_packets} packets in {elapsed:.2f}s")
        print(f"[FILE SENDER]   Effective throughput: "
              f"{(file_size / elapsed / 1024):.2f} KB/s")

    finally:
        udp_socket.close()


# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python file_sender.py <filename> <receiver_ip>")
        print("Example: python file_sender.py notes.pdf 192.168.1.5")
        sys.exit(1)

    filename    = sys.argv[1]
    receiver_ip = sys.argv[2]
    send_file(filename, receiver_ip)
