/* Fixed TCP version (networking portions)

NOTE:
- Replace UDP socket with TCP listen/accept.
- Use send_all() to transmit complete packets.
- Use client_fd (accepted socket) instead of sock_fd for send/recv.

static int send_all(int fd, const void *buf, size_t len)
{
    const uint8_t *p = (const uint8_t*)buf;
    while (len) {
        ssize_t n = send(fd, p, len, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (n == 0) return -1;
        p += n;
        len -= n;
    }
    return 0;
}

void send_async_packet(int client_fd,
                       uint32_t type,
                       const void *payload,
                       uint32_t payload_len)
{
    AsyncProtocolHeader hdr;
    hdr.packet_type = htonl(type);
    hdr.sequence_num = htonl(g_tx_sequence++);
    hdr.payload_len  = htonl(payload_len);

    if (send_all(client_fd, &hdr, sizeof(hdr)) != 0)
        return;

    if (payload_len)
        send_all(client_fd, payload, payload_len);
}

Server setup:

int listen_fd = socket(AF_INET, SOCK_STREAM, 0);

int opt = 1;
setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

bind(...);
listen(listen_fd, 1);

int client_fd = -1;

Loop:

if (client_fd < 0) {
    client_fd = accept(listen_fd, NULL, NULL);
    if (client_fd >= 0) {
        fcntl(client_fd, F_SETFL,
              fcntl(client_fd, F_GETFL, 0) | O_NONBLOCK);
    }
}

if (client_fd >= 0) {
    ssize_t n = recv(client_fd, rx_buffer, sizeof(rx_buffer)-1, 0);

    if (n == 0) {
        close(client_fd);
        client_fd = -1;
    } else if (n > 0) {
        rx_buffer[n] = 0;

        if (!strncmp(rx_buffer, "RESET", 5)) {
            tcflush(fd1, TCIOFLUSH);
            tcflush(fd2, TCIOFLUSH);

            send_async_packet(client_fd,
                              PKT_TYPE_SYSTEM,
                              "RESET_ACK",
                              9);
        } else {
            write(fd1, rx_buffer, n);
        }
    }
}

Also fix TLV parser:

Replace:

offset += tlv.length - sizeof(RadarTLVHeader);

with

offset += tlv.length;

ONLY if tlv.length is payload length (matching your Python parser).
