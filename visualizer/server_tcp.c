#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define TCP_SERVER_PORT 5001

static int g_listen_fd = -1;
static int g_client_fd = -1;

static int set_nonblocking(int fd)
{
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0)
        return -1;
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

int setup_tcp_server(int port)
{
    int opt = 1;

    g_listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (g_listen_fd < 0) {
        perror("socket");
        return -1;
    }

    setsockopt(g_listen_fd, SOL_SOCKET, SO_REUSEADDR,
               &opt, sizeof(opt));

    set_nonblocking(g_listen_fd);

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));

    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);

    if (bind(g_listen_fd,
             (struct sockaddr *)&addr,
             sizeof(addr)) < 0)
    {
        perror("bind");
        close(g_listen_fd);
        return -1;
    }

    if (listen(g_listen_fd, 1) < 0)
    {
        perror("listen");
        close(g_listen_fd);
        return -1;
    }

    printf("TCP server listening on port %d\n", port);

    return g_listen_fd;
}

void accept_client(void)
{
    if (g_client_fd >= 0)
        return;

    struct sockaddr_in client;
    socklen_t len = sizeof(client);

    g_client_fd = accept(g_listen_fd,
                         (struct sockaddr *)&client,
                         &len);

    if (g_client_fd < 0)
    {
        if (errno != EAGAIN && errno != EWOULDBLOCK)
            perror("accept");
        return;
    }

    set_nonblocking(g_client_fd);

    printf("Client connected from %s:%d\n",
           inet_ntoa(client.sin_addr),
           ntohs(client.sin_port));
}

int poll_client(char *buffer, size_t size)
{
    if (g_client_fd < 0)
        return -1;

    ssize_t n = recv(g_client_fd, buffer, size, 0);

    if (n == 0)
    {
        printf("Client disconnected\n");
        close(g_client_fd);
        g_client_fd = -1;
        return -1;
    }

    if (n < 0)
    {
        if (errno == EAGAIN || errno == EWOULDBLOCK)
            return 0;

        perror("recv");
        close(g_client_fd);
        g_client_fd = -1;
        return -1;
    }

    return (int)n;
}

static int send_all(const void *buffer, size_t len)
{
    const uint8_t *ptr = buffer;

    while (len)
    {
        ssize_t n = send(g_client_fd,
                         ptr,
                         len,
                         MSG_NOSIGNAL);

        if (n < 0)
        {
            if (errno == EINTR)
                continue;

            perror("send");
            close(g_client_fd);
            g_client_fd = -1;
            return -1;
        }

        ptr += n;
        len -= n;
    }

    return 0;
}

void forward_to_client(const void *data, size_t len)
{
    if (g_client_fd < 0)
        return;

    send_all(data, len);
}

void close_server(void)
{
    if (g_client_fd >= 0)
        close(g_client_fd);

    if (g_listen_fd >= 0)
        close(g_listen_fd);

    g_client_fd = -1;
    g_listen_fd = -1;
}
