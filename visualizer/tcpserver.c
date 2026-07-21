#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>

#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>

#define SERVER_PORT 5001

static int g_client_fd = -1;

int setup_tcp_server(int port)
{
    int server_fd;

    struct sockaddr_in addr;

    server_fd = socket(AF_INET, SOCK_STREAM, 0);

    if(server_fd < 0)
    {
        perror("socket");
        return -1;
    }

    int enable = 1;

    setsockopt(server_fd,
               SOL_SOCKET,
               SO_REUSEADDR,
               &enable,
               sizeof(enable));

    int flags = fcntl(server_fd, F_GETFL);

    fcntl(server_fd,
          F_SETFL,
          flags | O_NONBLOCK);

    memset(&addr,0,sizeof(addr));

    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    addr.sin_addr.s_addr = INADDR_ANY;

    if(bind(server_fd,
            (struct sockaddr*)&addr,
            sizeof(addr)) < 0)
    {
        perror("bind");
        close(server_fd);
        return -1;
    }

    if(listen(server_fd,1) < 0)
    {
        perror("listen");
        close(server_fd);
        return -1;
    }

    printf("Listening on port %d\n",port);

    return server_fd;
}

void accept_client(int server_fd)
{
    if(g_client_fd >= 0)
        return;

    struct sockaddr_in client;

    socklen_t len = sizeof(client);

    g_client_fd = accept(server_fd,
                         (struct sockaddr*)&client,
                         &len);

    if(g_client_fd < 0)
    {
        return;
    }

    printf("Client connected: %s\n",
           inet_ntoa(client.sin_addr));

    int flags = fcntl(g_client_fd,F_GETFL);

    fcntl(g_client_fd,
          F_SETFL,
          flags | O_NONBLOCK);
}

void poll_client(void)
{
    if(g_client_fd < 0)
        return;

    char buffer[256];

    int n = recv(g_client_fd,
                 buffer,
                 sizeof(buffer)-1,
                 0);

    if(n == 0)
    {
        printf("Client disconnected\n");

        close(g_client_fd);

        g_client_fd = -1;

        return;
    }

    if(n < 0)
    {
        if(errno == EAGAIN || errno == EWOULDBLOCK)
            return;

        perror("recv");

        close(g_client_fd);

        g_client_fd = -1;

        return;
    }

    buffer[n]=0;

    printf("RX: %s",buffer);
}

void forward_to_client(const void *data,size_t len)
{
    if(g_client_fd < 0)
        return;

    ssize_t sent = send(g_client_fd,
                        data,
                        len,
                        MSG_NOSIGNAL);

    if(sent <= 0)
    {
        perror("send");

        close(g_client_fd);

        g_client_fd = -1;
    }
}
