# ChatNet — Real-Time Network Programming Chatroom

ChatNet is a Python-based real-time client/server chatroom application developed for a Network Programming project.

The system was built completely from scratch using low-level socket programming to demonstrate how real-world communication systems operate internally.

ChatNet simulates core networking concepts used in modern communication platforms such as Discord and Slack, including:
- TCP/IP communication
- Multithreading
- UDP file transfer
- DNS resolution
- HTTP services
- SMTP email notifications

---

# 🚀 Features

## 🔹 Real-Time TCP Chat
- Multi-client chatroom using TCP sockets
- Real-time message broadcasting
- Timestamped messages
- Graceful disconnect handling

## 🔹 Multithreading
- Dedicated thread for every connected client
- Concurrent communication support
- Thread-safe shared resources using locks

## 🔹 Network Diagnostics
- `/ping` command for RTT measurement
- `/throughput` command for throughput estimation

## 🔹 Private Messaging
```bash
/msg <username> <message>
