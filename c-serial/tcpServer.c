#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <termios.h>
#include <poll.h>
#include <signal.h>
#include <time.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#include "parser.h"
#include "server.h"

#define PKT_TYPE_CLI_RESP 1
#define PKT_TYPE_RADAR    2
#define PKT_TYPE_SYSTEM   99

typedef struct __attribute__((packed)) {
    uint32_t packet_type;
    uint32_t sequence_num;
    uint32_t payload_len;
} AsyncProtocolHeader;

uint32_t g_tx_sequence = 0;

static void handle_sigint(int sig) {
    (void)sig;
    g_stop = 1;
}

int configure_serial_port(const char *port_name, speed_t baud_rate) {
    int fd = open(port_name, O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd < 0) {
        perror("Error opening serial port");
        return -1;
    }

    struct termios tty;
    if (tcgetattr(fd, &tty) != 0) {
        perror("Error from tcgetattr");
        close(fd);
        return -1;
    }

    cfsetospeed(&tty, baud_rate);
    cfsetispeed(&tty, baud_rate);

    tty.c_cflag &= ~PARENB;
    tty.c_cflag &= ~CSTOPB;
    tty.c_cflag &= ~CSIZE;
    tty.c_cflag |= CS8;
    tty.c_cflag |= CREAD | CLOCAL;
    tty.c_cflag &= ~CRTSCTS;

    tty.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG);
    tty.c_iflag &= ~(IXON | IXOFF | IXANY | ICRNL);
    tty.c_oflag &= ~OPOST;

    tty.c_cc[VMIN]  = 0;
    tty.c_cc[VTIME] = 0;

    if (tcsetattr(fd, TCSANOW, &tty) != 0) {
        perror("Error from tcsetattr");
        close(fd);
        return -1;
    }

    return fd;
}

// Encapsulates data payload into our async network protocol frame over TCP
void send_async_packet(int client_fd, uint32_t type, const void *payload, size_t payload_len) {
    if (!g_client_registered || client_fd < 0) return;

    AsyncProtocolHeader header;
    header.packet_type = htonl(type);
    header.sequence_num = htonl(g_tx_sequence++);
    header.payload_len = htonl((uint32_t)payload_len);

    uint8_t tx_buffer[sizeof(AsyncProtocolHeader) + BUFFER_SIZE];
    memcpy(tx_buffer, &header, sizeof(AsyncProtocolHeader));
    if (payload && payload_len > 0) {
        memcpy(tx_buffer + sizeof(AsyncProtocolHeader), payload, payload_len);
    }

    // In TCP, we use send() directly on the client socket connection descriptor
    ssize_t sent = send(client_fd, tx_buffer, sizeof(AsyncProtocolHeader) + payload_len, 0);
    if (sent < 0) {
        if (errno != EAGAIN && errno != EWOULDBLOCK) {
            perror("TCP transmission failed. Disconnecting client.");
            close(g_client_fd);
            g_client_fd = -1;
            g_client_registered = 0;
        }
    }
}

int main() {
    signal(SIGINT, handle_sigint);

    int fd1 = configure_serial_port("/dev/ttyUSB0", B115200);
    int fd2 = configure_serial_port("/dev/ttyUSB1", B921600);
    
    int listen_fd = setup_tcp_server(TCP_SERVER_PORT);
    if (listen_fd < 0) return -1;

    char rx_buffer[BUFFER_SIZE];
    printf("TCP Protocol Engine Server running on port %d...\n", TCP_SERVER_PORT);

    while (!g_stop) {
        struct pollfd fds[4];
        int nfds = 3;

        fds[0].fd = fd1;      fds[0].events = POLLIN; fds[0].revents = 0;
        fds[1].fd = fd2;      fds[1].events = POLLIN; fds[1].revents = 0;
        fds[2].fd = listen_fd; fds[2].events = POLLIN; fds[2].revents = 0;

        // Dynamic addition: only poll the client socket if a connection is established
        if (g_client_registered && g_client_fd >= 0) {
            fds[3].fd = g_client_fd;
            fds[3].events = POLLIN;
            fds[3].revents = 0;
            nfds = 4;
        }

        if (poll(fds, nfds, 100) < 0) {
            if (errno == EINTR) continue;
            break;
        }

        // --- 1. TCP Connection Manager (Listening Socket) ---
        if (fds[2].revents & POLLIN) {
            struct sockaddr_in client_addr;
            socklen_t client_len = sizeof(client_addr);
            int new_client = accept(listen_fd, (struct sockaddr *)&client_addr, &client_len);
            
            if (new_client >= 0) {
                // If an old client exists, drop them to let the new one take control
                if (g_client_fd >= 0) {
                    close(g_client_fd);
                }
                g_client_fd = new_client;
                g_client_registered = 1;
                
                // Set the new client connection to non-blocking execution mode
                int flags = fcntl(g_client_fd, F_GETFL, 0);
                fcntl(g_client_fd, F_SETFL, flags | O_NONBLOCK);
                
                printf("[SERVER] Accepted connection from %s:%d\n", 
                       inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));
            }
        }

        // --- 2. Client Message / Command Input Stream ---
        if (nfds == 4 && (fds[3].revents & POLLIN)) {
            ssize_t n = recv(g_client_fd, rx_buffer, sizeof(rx_buffer) - 1, 0);
            if (n > 0) {
                rx_buffer[n] = '\0';

                if (strncmp(rx_buffer, "RESET", 5) == 0) {
                    printf("\n[SYSTEM] Received Reset Request! Purging queues...\n");
                    tcflush(fd1, TCIOFLUSH);
                    tcflush(fd2, TCIOFLUSH);
                    send_async_packet(g_client_fd, PKT_TYPE_SYSTEM, "RESET_ACK", 9);
                } else {
                    write(fd1, rx_buffer, n);
                }
            } else if (n == 0 || (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) {
                // Client gracefully disconnected (n == 0) or connection threw an error
                printf("[SERVER] Client disconnected.\n");
                close(g_client_fd);
                g_client_fd = -1;
                g_client_registered = 0;
            }
        }

        // --- 3. Port 1 CLI Echo Handler ---
        if (fds[0].revents & POLLIN) {
            ssize_t n = read(fd1, rx_buffer, sizeof(rx_buffer));
            if (n > 0 && g_client_registered) {
                send_async_packet(g_client_fd, PKT_TYPE_CLI_RESP, rx_buffer, n);
            }
        }

        // --- 4. Port 2 Radar Streaming Stream ---
        if (fds[1].revents & POLLIN) {
            ssize_t n = read(fd2, rx_buffer, sizeof(rx_buffer));
            if (n > 0 && g_client_registered) {
                send_async_packet(g_client_fd, PKT_TYPE_RADAR, rx_buffer, n);
            }
        }
    }

    if (g_client_fd >= 0) close(g_client_fd);
    close(listen_fd);
    close(fd1);
    close(fd2);
    return 0;
}
