"""
============================================================
  ChatNet — Task 3 : UDP Reliable File Receiver
  File : file_receiver.py
============================================================

WHAT THIS FILE DOES
--------------------
  Listens on UDP port 13000 for incoming file packets from file_sender.py.
  Reassembles the file in correct order and writes it to disk.

HOW THE RECEIVER WORKS (Stop-and-Wait)
----------------------------------------
  For every packet that arrives:
    1. Extract the sequence number and total_packets from the header.
    2. Check if this is the expected sequence number.
    3. If YES  → store the chunk, send ACK, advance expected sequence number.
    4. If NO   → it is a duplicate (old retransmit). Send the ACK again so
                 the sender can advance, but do NOT store the data again.
    5. When all packets are received → write the assembled bytes to disk.

PACKET FORMAT (same as file_sender.py)
----------------------------------------
  [ 4 bytes: sequence number  (big-endian uint32) ]
  [ 4 bytes: total packets    (big-endian uint32) ]
  [ up to 512 bytes: file data                    ]

USAGE
-----
  python file_receiver.py [output_filename]

  Default output filename: "received_file"
  The extension is preserved if the sender sends a known file name via
  the protocol header (not implemented in this simplified version).
"""

import socket
import sys
import os
import time

# ─────────────────────────────────────────────
#  Configuration  (must match file_sender.py)
# ─────────────────────────────────────────────
LISTEN_PORT   = 13000     # UDP port to listen on
BUFFER_SIZE   = 520 + 64  # Slightly larger than max packet (header + chunk)
IDLE_TIMEOUT  = 30        # If no packet arrives in 30s, consider transfer done


def unpack_packet(raw_bytes):
    """
    Extracts fields from a binary packet.
    Returns (seq_num, total_packets, data_chunk).

    We manually slice the bytes array to show students how the header works
    without using the 'struct' module.
    """
    seq_num       = int.from_bytes(raw_bytes[0:4], byteorder='big')
    total_packets = int.from_bytes(raw_bytes[4:8], byteorder='big')
    data_chunk    = raw_bytes[8:]          # The rest is the file payload
    return seq_num, total_packets, data_chunk


def receive_file(output_filename):
    """
    Listens for UDP packets and reassembles the file.

    Parameters:
      output_filename : the filename to save the reassembled data to
    """

    # ── Create UDP socket ──────────────────────────────────────────────
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Bind to all interfaces on LISTEN_PORT
    udp_socket.bind(('0.0.0.0', LISTEN_PORT))

    # Idle timeout: if no packet arrives in IDLE_TIMEOUT seconds we stop.
    # This prevents the receiver from hanging forever if the sender crashes.
    udp_socket.settimeout(IDLE_TIMEOUT)

    print("=" * 50)
    print("  ChatNet File Receiver — Task 3")
    print(f"  Listening on UDP port {LISTEN_PORT}")
    print(f"  Output file : {output_filename}")
    print("=" * 50)
    print("[RECEIVER] Waiting for incoming file transfer…\n")

    received_chunks = {}    # Maps seq_num → bytes chunk
    expected_seq    = 0     # Next sequence number we expect
    total_packets   = None  # Will be filled from first packet
    start_time      = None

    try:
        while True:
            # ── Wait for a packet ──────────────────────────────────────
            try:
                raw_data, sender_addr = udp_socket.recvfrom(BUFFER_SIZE)
            except socket.timeout:
                print("[RECEIVER] No data received in 30 seconds. Stopping.")
                break

            if start_time is None:
                start_time = time.time()
                print(f"[RECEIVER] Transfer started from {sender_addr}")

            # ── Unpack header ──────────────────────────────────────────
            if len(raw_data) < 8:
                print(f"[WARN] Received malformed packet ({len(raw_data)} bytes). Ignored.")
                continue

            seq_num, tot_pkts, chunk = unpack_packet(raw_data)
            total_packets = tot_pkts    # Update total from every packet (consistent)
            packet_num    = seq_num + 1  # 1-based for display

            # ── Check if this is the expected packet ───────────────────
            if seq_num == expected_seq:
                # ✔ Correct order — store the chunk and advance
                received_chunks[seq_num] = chunk
                print(f"  Received packet {packet_num}/{total_packets} "
                      f"({len(chunk)} bytes)  from {sender_addr[0]}")
                expected_seq += 1

                # Send ACK for this sequence number
                ack = seq_num.to_bytes(4, byteorder='big')
                udp_socket.sendto(ack, sender_addr)
                print(f"  ACK {seq_num} sent")

            elif seq_num < expected_seq:
                # Duplicate packet (retransmitted by sender after ACK was lost)
                # Send the ACK again so sender can move forward
                print(f"  [DUP] Duplicate packet {packet_num} received. Re-ACKing.")
                ack = seq_num.to_bytes(4, byteorder='big')
                udp_socket.sendto(ack, sender_addr)

            else:
                # seq_num > expected_seq — out-of-order packet (shouldn't happen
                # with Stop-and-Wait, but we handle it defensively)
                print(f"  [WARN] Out-of-order packet {packet_num} "
                      f"(expected {expected_seq + 1}). Dropped.")

            # ── Check if we have all packets ───────────────────────────
            if total_packets and len(received_chunks) == total_packets:
                print(f"\n[RECEIVER] All {total_packets} packets received. Assembling file…")
                break

    except KeyboardInterrupt:
        print("\n[RECEIVER] Interrupted by user.")
    finally:
        udp_socket.close()

    # ── Reassemble file ────────────────────────────────────────────────
    if not received_chunks:
        print("[ERROR] No data received. File not saved.")
        return

    # Sort chunks by sequence number and concatenate
    assembled = b"".join(received_chunks[i] for i in sorted(received_chunks.keys()))

    # Write to disk
    try:
        with open(output_filename, 'wb') as f:
            f.write(assembled)

        elapsed = time.time() - start_time if start_time else 0
        size_kb = len(assembled) / 1024

        print(f"[RECEIVER] ✔ File saved as: {output_filename}")
        print(f"[RECEIVER]   Size    : {len(assembled)} bytes ({size_kb:.2f} KB)")
        print(f"[RECEIVER]   Time    : {elapsed:.2f} seconds")
        if elapsed > 0:
            print(f"[RECEIVER]   Speed   : {size_kb / elapsed:.2f} KB/s")
        print("[RECEIVER] Transfer complete!")

    except Exception as e:
        print(f"[ERROR] Could not save file: {e}")


# ─────────────────────────────────────────────
#  Entry Point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Optional: pass output filename as first argument
    # Default to "received_file" if not specified
    if len(sys.argv) >= 2:
        output_name = sys.argv[1]
    else:
        output_name = "received_file"

    receive_file(output_name)
