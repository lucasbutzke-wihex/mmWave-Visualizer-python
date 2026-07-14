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
#include <stdalign.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>

#include "parser.h"
#include "server.h"
#include "watchdog.h"


#define TCP_SERVER_PORT 5001
#define CMD_LINE_BUF_SIZE 512

#define PKT_TYPE_CLI_RESP 1
#define PKT_TYPE_RADAR    2
#define PKT_TYPE_SYSTEM   99

typedef struct __attribute__((packed)) {
    uint32_t packet_type;
    uint32_t sequence_num;
    uint32_t payload_len;
} AsyncProtocolHeader;

uint32_t g_tx_sequence = 0;
int g_client_fd = -1;

static char g_cmd_line_buf[CMD_LINE_BUF_SIZE];
static size_t g_cmd_line_len = 0;

static void handle_sigint(int sig) {
    (void)sig;
    g_stop = 1;
}

static long now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long)(ts.tv_sec * 1000L + ts.tv_nsec / 1000000L);
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

// // ---------------------------------------------------------------------
// // Port 2: passive data parsing (called as complete lines arrive)
// // ---------------------------------------------------------------------

// static void parse_port2_data(const char *frame, size_t len) {
//     char tmp[BUFFER_SIZE];
//     size_t copy_len = (len < sizeof(tmp) - 1) ? len : sizeof(tmp) - 1;
//     memcpy(tmp, frame, copy_len);
//     tmp[copy_len] = '\0';
//     while (copy_len > 0 && (tmp[copy_len - 1] == '\n' || tmp[copy_len - 1] == '\r')) {
//         tmp[--copy_len] = '\0';
//     }
//     if (copy_len == 0) return;

//     printf("[Port2] Parsed: %s\n", tmp);

//     // Example of adding real logic:
//     // if (strncmp(tmp, "DATA,", 5) == 0) {
//     //     int value = atoi(tmp + 5);
//     //     printf("[Port2] Value=%d\n", value);
//     // }
// }

static void handle_range_profile(const uint8_t *payload, uint32_t length) {
    uint32_t num_elements = length / 2;
    if (num_elements > MAX_RANGE_PROFILE_ELEMENTS) {
        num_elements = MAX_RANGE_PROFILE_ELEMENTS;
    }
    
    // ARM ALIGNMENT FIX: Copy unaligned serial payload into a safely aligned stack buffer
    uint16_t range_profile[MAX_RANGE_PROFILE_ELEMENTS];
    memcpy(range_profile, payload, num_elements * 2);

#ifdef RADAR_DEBUG_PRINT
    printf("  [TLV Type 2] Parsed Range Profile. Elements: %u\n", num_elements);
    for (uint32_t i = 0; i < num_elements; i++) {
        printf("Range Bin %u: %u\n", i, range_profile[i]);
    }
#endif
}

static void handle_range_doppler_heatmap(const uint8_t *payload, uint32_t length) {
    uint32_t total_elements = length / 2;
    if (total_elements != MAX_HEATMAP_ELEMENTS) {
        fprintf(stderr, "  [TLV Type 5] Warning: Heatmap data size (%u elements) mismatched expected size (%d).\n",
                total_elements, MAX_HEATMAP_ELEMENTS);
        return;
    }
    
    // ARM ALIGNMENT FIX: Use aligned static buffer for handling high-throughput matrix bytes safely
    static uint16_t heatmap_flat[MAX_HEATMAP_ELEMENTS];
    memcpy(heatmap_flat, payload, length);

#ifdef RADAR_DEBUG_PRINT
    printf("  [TLV Type 5] Parsed Range-Doppler Heatmap matrix (%d x %d).\n", NUM_RANGE_BINS, NUM_DOPPLER_BINS);
    for (int r = 0; r < NUM_RANGE_BINS; r++) {
        printf("Range Bin %d: ", r);
        for (int d = 0; d < NUM_DOPPLER_BINS; d++) {
            uint16_t intensity = heatmap_flat[r * NUM_DOPPLER_BINS + d];
            printf("%u ", intensity);
        }
        printf("\n");
    }
#endif
}

static void parse_radar_tlv(uint32_t type, uint32_t length, const uint8_t *payload) {
    switch (type) {
        case 2:
            handle_range_profile(payload, length);
            break;
        case 5:
            handle_range_doppler_heatmap(payload, length);
            break;
        default:
            printf("  [TLV Type %u] Found other data layer. Length: %u bytes\n", type, length);
            break;
    }
}

static void process_radar_frame(const uint8_t *frame_data, size_t size) {
    if (size < sizeof(RadarFrameHeader)) return;

    RadarFrameHeader header;
    memcpy(&header, frame_data, sizeof(RadarFrameHeader));

    printf("\n--- [Radar Frame #%u] ---\n", header.frameNum);
    printf(" Total Packet Length: %u bytes\n", header.totalPacketLen);
    printf(" Detected Objects   : %u\n", header.numDetectedObj);
    printf(" Total TLV Blocks   : %u\n", header.numTLVs);

    size_t offset = sizeof(RadarFrameHeader);

    for (uint32_t i = 0; i < header.numTLVs; i++) {
        if (offset + sizeof(RadarTLVHeader) > header.totalPacketLen) break;

        RadarTLVHeader tlv;
        memcpy(&tlv, frame_data + offset, sizeof(RadarTLVHeader));
        offset += sizeof(RadarTLVHeader);

        if (offset + tlv.length > header.totalPacketLen) {
            fprintf(stderr, "Warning: TLV structural length overflowed frame bound.\n");
            break;
        }

        parse_radar_tlv(tlv.type, tlv.length, frame_data + offset);
        offset += tlv.length;

        // TLV ALIGNMENT FIX: TI mmWave SDK structure pads next TLV to 4-byte alignment boundary
        if (offset % 4 != 0) {
            offset += (4 - (offset % 4));
        }
    }
}

static void port2_feed(char *accum, size_t *accum_len, const char *chunk, size_t n) {
    if (*accum_len + n >= PORT2_ACCUM_SIZE) {
        fprintf(stderr, "[Port2] Buffer saturated! Clearing alignment state.\n");
        *accum_len = 0;
        return;
    }

    memcpy(accum + *accum_len, chunk, n);
    *accum_len += n;

    while (*accum_len >= sizeof(RadarFrameHeader)) {
        size_t magic_idx = 0;
        int found_magic = 0;

        for (size_t i = 0; i <= *accum_len - 8; i++) {
            if (memcmp(accum + i, RADAR_MAGIC_WORD, 8) == 0) {
                magic_idx = i;
                found_magic = 1;
                break;
            }
        }

        if (!found_magic) {
            size_t preserve = 7;
            if (*accum_len > preserve) {
                memmove(accum, accum + (*accum_len - preserve), preserve);
                *accum_len = preserve;
            }
            return;
        }

        if (magic_idx > 0) {
            memmove(accum, accum + magic_idx, *accum_len - magic_idx);
            *accum_len -= magic_idx;
        }

        if (*accum_len < sizeof(RadarFrameHeader)) return;

        // ARM ALIGNMENT FIX: Safe extraction of length using memcpy instead of pointer type casting
        uint32_t total_packet_len;
        memcpy(&total_packet_len, accum + 12, sizeof(uint32_t));

        if (*accum_len < total_packet_len) {
            return;
        }

        process_radar_frame((uint8_t *)accum, total_packet_len);

        size_t consumed = total_packet_len;
        memmove(accum, accum + consumed, *accum_len - consumed);
        *accum_len -= consumed;
    }
}

static void close_client(void) {
    if (g_client_fd >= 0) {
        close(g_client_fd);
        g_client_fd = -1;
        g_cmd_line_len = 0;
        printf("[TCP] Client disconnected.\n");
    }
}

void send_async_packet(uint32_t type, const void *payload, size_t payload_len) {
    if (g_client_fd < 0) return;

    AsyncProtocolHeader header;
    header.packet_type = htonl(type);
    header.sequence_num = htonl(g_tx_sequence++);
    header.payload_len = htonl((uint32_t)payload_len);

    uint8_t tx_buffer[sizeof(AsyncProtocolHeader) + BUFFER_SIZE];
    memcpy(tx_buffer, &header, sizeof(AsyncProtocolHeader));
    if (payload && payload_len > 0) {
        memcpy(tx_buffer + sizeof(AsyncProtocolHeader), payload, payload_len);
    }

    size_t total_len = sizeof(AsyncProtocolHeader) + payload_len;
    size_t sent = 0;

    while (sent < total_len) {
        ssize_t n = send(g_client_fd, tx_buffer + sent, total_len - sent, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                fprintf(stderr, "[TCP] Send would block, dropping packet type %u\n", type);
                return;
            }
            perror("[TCP] send failed");
            close_client();
            return;
        }
        sent += (size_t)n;
    }
}

static void handle_client_command(const char *line, size_t len, int fd1, int fd2) {
    if (len == 0) return;

    if (strncmp(line, "RESET", 5) == 0) {
        printf("\n[SYSTEM] Received Reset Request! Purging queues...\n");
        tcflush(fd1, TCIOFLUSH);
        tcflush(fd2, TCIOFLUSH);
        send_async_packet(PKT_TYPE_SYSTEM, "RESET_ACK", 9);
    } else {
        char cmd_buf[CMD_LINE_BUF_SIZE + 1];
        size_t copy_len = (len < CMD_LINE_BUF_SIZE) ? len : CMD_LINE_BUF_SIZE;
        memcpy(cmd_buf, line, copy_len);
        cmd_buf[copy_len] = '\n';
        write(fd1, cmd_buf, copy_len + 1);
    }
}

static void handle_client_data(int fd1, int fd2) {
    char rx_buffer[BUFFER_SIZE];
    ssize_t n = recv(g_client_fd, rx_buffer, sizeof(rx_buffer), 0);

    if (n == 0) {
        close_client();
        return;
    }
    if (n < 0) {
        if (errno == EAGAIN || errno == EWOULDBLOCK) return;
        perror("[TCP] recv failed");
        close_client();
        return;
    }

    for (ssize_t i = 0; i < n; i++) {
        char c = rx_buffer[i];
        if (c == '\n' || c == '\r') {
            if (g_cmd_line_len > 0) {
                handle_client_command(g_cmd_line_buf, g_cmd_line_len, fd1, fd2);
                g_cmd_line_len = 0;
            }
        } else if (g_cmd_line_len < CMD_LINE_BUF_SIZE - 1) {
            g_cmd_line_buf[g_cmd_line_len++] = c;
        } else {
            fprintf(stderr, "[TCP] Command line too long, discarding.\n");
            g_cmd_line_len = 0;
        }
    }
}

static int setup_tcp_listener(int port) {
    int listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd < 0) {
        perror("socket() failed");
        return -1;
    }

    int opt = 1;
    setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in servaddr = {0};
    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = INADDR_ANY;
    servaddr.sin_port = htons(port);

    if (bind(listen_fd, (struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) {
        perror("bind() failed");
        close(listen_fd);
        return -1;
    }

    if (listen(listen_fd, 1) < 0) {
        perror("listen() failed");
        close(listen_fd);
        return -1;
    }

    fcntl(listen_fd, F_SETFL, fcntl(listen_fd, F_GETFL, 0) | O_NONBLOCK);
    return listen_fd;
}

static void accept_new_client(int listen_fd) {
    struct sockaddr_in client_addr;
    socklen_t client_len = sizeof(client_addr);

    int new_fd = accept(listen_fd, (struct sockaddr *)&client_addr, &client_len);
    if (new_fd < 0) {
        if (errno != EAGAIN && errno != EWOULDBLOCK) {
            perror("accept() failed");
        }
        return;
    }

    if (g_client_fd >= 0) {
        printf("[TCP] New client connecting, dropping previous client.\n");
        close_client();
    }

    fcntl(new_fd, F_SETFL, fcntl(new_fd, F_GETFL, 0) | O_NONBLOCK);

    int nodelay = 1;
    setsockopt(new_fd, IPPROTO_TCP, TCP_NODELAY, &nodelay, sizeof(nodelay));

    g_client_fd = new_fd;
    g_cmd_line_len = 0;

    printf("[TCP] Client connected: %s:%d\n",
           inet_ntoa(client_addr.sin_addr), ntohs(client_addr.sin_port));
}

int main() {
    RadarWatchdog wdt;
    watchdog_start(&wdt, "21", 5.0); //pino 21, 5s de timeout

    const char *port1_path = dataPort; // config/command port
    const char *port2_path = cliPort ; // passive data listener port
    const char *file_path  = configFile; // file to send to Port 1
    speed_t baud1 = B115200;
    speed_t baud2 = B921600;

    signal(SIGINT, handle_sigint);

    int fd1 = configure_serial_port(port1_path, baud1);
    int fd2 = configure_serial_port(port2_path, baud2);
    int sock_fd = setup_udp_server(UDP_SERVER_PORT);

    if (fd1 < 0 || fd2 < 0 || sock_fd < 0) {
        fprintf(stderr, "Initialization failed.\n");
        return EXIT_FAILURE;
    }

    int listen_fd = setup_tcp_listener(TCP_SERVER_PORT);
    if (listen_fd < 0) {
        fprintf(stderr, "Failed to start TCP listener, exiting.\n");
        return 1;
    }

    printf("Async Server Active! Listening for UDP commands on port %d...\n", UDP_SERVER_PORT);

    FILE *file = fopen(file_path, "r");
    if (!file) {
        perror("Error opening input file");
        close(fd1);
        close(fd2);
        close(sock_fd);
        return EXIT_FAILURE;
    }

    // Port 1 state
    port1_state_t state = PORT1_IDLE;
    char response_buffer[BUFFER_SIZE];
    size_t response_len = 0;
    long response_deadline_ms = 0;
    long cooldown_until_ms = 0; // non-blocking replacement for usleep(100ms)

    // Port 2 state
    static char port2_accum[PORT2_ACCUM_SIZE];
    size_t port2_accum_len = 0;

    char line_buffer[BUFFER_SIZE];

    printf("Starting file transmission to %s (Port 2 listening on %s)...\n",
           port1_path, port2_path);

    // Dynamic multiplexer array monitoring 3 independent streams
    struct pollfd fds[3];
    fds[0].fd = fd1;     fds[0].events = POLLIN; // Serial Port 1 (CLI RX)
    fds[1].fd = fd2;     fds[1].events = POLLIN; // Serial Port 2 (Radar Data RX)
    fds[2].fd = sock_fd; fds[2].events = POLLIN; // UDP Socket RX

    char network_buffer[BUFFER_SIZE];

    printf("Protocol Engine Server (TCP) running on port %d...\n", TCP_SERVER_PORT);

    while (!g_stop) {
        struct pollfd fds[5];
        int nfds = 0;

        fds[nfds].fd = fd1; fds[nfds].events = POLLIN; nfds++;
        fds[nfds].fd = fd2; fds[nfds].events = POLLIN; nfds++;
        fds[nfds].fd = listen_fd; fds[nfds].events = POLLIN; nfds++;
        int udp_idx = nfds;
        fds[nfds].fd = sock_fd; fds[nfds].events = POLLIN; nfds++;

        int client_idx = -1;
        if (g_client_fd >= 0) {
            client_idx = nfds;
            fds[nfds].fd = g_client_fd; fds[nfds].events = POLLIN; nfds++;
        }

        int timeout_ms = POLL_IDLE_MS;
        if (state == PORT1_WAITING_RESPONSE) {
            long remaining = response_deadline_ms - now_ms();
            if (remaining < 0) remaining = 0;
            timeout_ms = (int)(remaining < POLL_IDLE_MS ? remaining : POLL_IDLE_MS);
        } else if (state == PORT1_IDLE && now_ms() < cooldown_until_ms) {
            long remaining = cooldown_until_ms - now_ms();
            if (remaining < 0) remaining = 0;
            timeout_ms = (int)(remaining < POLL_IDLE_MS ? remaining : POLL_IDLE_MS);
        }

        int poll_count = poll(fds, nfds, timeout_ms);
        if (poll_count < 0) {
            if (errno == EINTR) continue;
            perror("Poll error");
            break;
        }

        if (fds[2].revents & POLLIN) {
            accept_new_client(listen_fd);
        }

        if (client_idx >= 0 && (fds[client_idx].revents & (POLLIN | POLLHUP | POLLERR))) {
            handle_client_data(fd1, fd2);
        }

        if (fds[udp_idx].revents & POLLIN) {
            ssize_t n = recvfrom(sock_fd, network_buffer, sizeof(network_buffer) - 1, 0,
                                 (struct sockaddr *)&g_client_addr, &g_client_len);
            if (n > 0) {
                network_buffer[n] = '\0';
                g_client_registered = 1; // Lock onto client address space
                
                printf("[UDP Network Command]: %s", network_buffer);
                
                // Route command directly into CLI hardware port
                int ret = write(fd1, network_buffer, n);
                if (ret < 0) {
                    perror("Failed to write to CLI port");
                }
            }
        }

        // --- Advance Port 1 state machine when idle: send the next line ---
        if (state == PORT1_IDLE && now_ms() >= cooldown_until_ms) {
            if (fgets(line_buffer, sizeof(line_buffer), file) != NULL) {
                printf("\nSending: %s", line_buffer);
                size_t len = strlen(line_buffer);
                ssize_t written = write(fd1, line_buffer, len);
                if (written < 0) {
                    perror("Failed to write to Port 1");
                    break;
                }
                response_len = 0;
                memset(response_buffer, 0, sizeof(response_buffer));
                response_deadline_ms = now_ms() + RESPONSE_TIMEOUT_MS;
                state = PORT1_WAITING_RESPONSE;
                printf("Waiting for response...\n");
            } else {
                state = PORT1_DONE; // File exhausted, but do NOT break!
                printf("\n[Port1] File transmission complete. Continuing to listen on Port 2...\n");
            }
        }

        if (fds[0].revents & POLLIN) {
            char rx_buffer[BUFFER_SIZE];
            ssize_t n = read(fd1, rx_buffer, sizeof(rx_buffer) - 1);
            if (n > 0) {
                send_async_packet(PKT_TYPE_CLI_RESP, rx_buffer, n);
                watchdog_feed(&wdt);

                if (state == PORT1_WAITING_RESPONSE) {
                    if (response_len + (size_t)n < sizeof(response_buffer)) {
                        memcpy(response_buffer + response_len, rx_buffer, (size_t)n);
                        response_len += (size_t)n;
                        response_buffer[response_len] = '\0';
                    }

                    int line_count = 0;
                    for (size_t idx = 0; idx < response_len; idx++) {
                        if (response_buffer[idx] == '\n') line_count++;
                    }

                    if (line_count >= 2) { 
                        printf("[Port1 Response]:\n%s", response_buffer);
                        state = PORT1_IDLE;
                        cooldown_until_ms = now_ms() + 50; // brief delay
                    }
                }
            }
        }

        if (state == PORT1_WAITING_RESPONSE && now_ms() >= response_deadline_ms) {
            fprintf(stderr, "Timeout! No response from Port 1.\n");
            printf("Skipping or retrying due to timeout...\n");
            state = PORT1_IDLE;
            cooldown_until_ms = now_ms() + 100;
        }

        if (fds[1].revents & POLLIN) {
            char rx_buffer[BUFFER_SIZE]; 
            ssize_t n = read(fd2, rx_buffer, sizeof(rx_buffer));
            if (n > 0) {
                send_async_packet(PKT_TYPE_RADAR, rx_buffer, n);
                watchdog_feed(&wdt);

                port2_feed(port2_accum, &port2_accum_len, rx_buffer, (size_t)n);
            } else if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
                perror("[Port2] Read error");
            }
        }
        if (fds[1].revents & (POLLERR | POLLHUP | POLLNVAL)) {
            fprintf(stderr, "[Port2] Port error/hangup detected.\n");
        }

        if (fds[0].revents & POLLIN) {
            char rx_buffer[BUFFER_SIZE];
            ssize_t n = read(fd1, rx_buffer, sizeof(rx_buffer));
            if (n > 0) {
                send_async_packet(PKT_TYPE_CLI_RESP, rx_buffer, n);
            }
            watchdog_feed(&wdt);
        }
    }

    fclose(file);
    close_client();
    close(listen_fd);
    if (fd1 >= 0) close(fd1);
    if (fd2 >= 0) close(fd2);
    watchdog_stop(&wdt);
    return 0;
}
