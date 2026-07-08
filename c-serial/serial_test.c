#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <termios.h>

#define SERIAL_PORT "/dev/ttyUSB0"  // Change to your UART port (e.g., /dev/ttyS0)
#define BUFFER_SIZE 256

// Function to configure the UART serial port
int configure_uart(const char *port) {
    int fd = open(port, O_RDWR | O_NOCTTY | O_NDELAY);
    if (fd == -1) {
        perror("Error: Unable to open UART port");
        return -1;
    }

    // Clear the non-blocking flag so read() actually waits for data
    fcntl(fd, F_SETFL, 0);

    struct termios options;
    tcgetattr(fd, &options);

    // Set standard Baud Rate (e.g., 115200)
    cfsetispeed(&options, B115200);
    cfsetospeed(&options, B115200);

    // 8N1 Mode: 8 data bits, no parity, 1 stop bit
    options.c_cflag &= ~PARENB;
    options.c_cflag &= ~CSTOPB;
    options.c_cflag &= ~CSIZE;
    options.c_cflag |= CS8;

    // Enable receiver and set local mode
    options.c_cflag |= (CLOCAL | CREAD);
    
    // Set raw input/output (no preprocessing)
    options.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG);
    options.c_oflag &= ~OPOST;

    // Set timeout to wait for data (VMIN = 1 means wait for at least 1 byte)
    options.c_cc[VMIN] = 1;
    options.c_cc[VTIME] = 0;

    tcsetattr(fd, TCSANOW, &options);
    return fd;
}

int main() {
    const char *filename = "commands.txt";
    char line_buffer[BUFFER_SIZE];
    char rx_buffer[BUFFER_SIZE];

    // 1. Open the file to read
    FILE *file = fopen(filename, "r");
    if (!file) {
        perror("Error: Unable to open input file");
        return EXIT_FAILURE;
    }

    // 2. Open and configure UART
    int uart_fd = configure_uart(SERIAL_PORT);
    if (uart_fd == -1) {
        fclose(file);
        return EXIT_FAILURE;
    }

    printf("Starting transmission on %s...\n", SERIAL_PORT);

    // 3. Read file line by line
    while (fgets(line_buffer, sizeof(line_buffer), file) != NULL) {
        printf("Sending: %s", line_buffer); // The line already includes '\n'

        // Write line to UART
        int bytes_written = write(uart_fd, line_buffer, strlen(line_buffer));
        if (bytes_written < 0) {
            perror("Failed to write to UART");
            break;
        }

        // 4. Wait for Response
        printf("Waiting for response...\n");
        memset(rx_buffer, 0, sizeof(rx_buffer));
        
        // This blocks until at least 1 byte arrives (as configured by VMIN)
        int bytes_read = read(uart_fd, rx_buffer, sizeof(rx_buffer) - 1);
        
        if (bytes_read > 0) {
            rx_buffer[bytes_read] = '\0'; // Null-terminate string
            printf("Received: %s\n", rx_buffer);
        } else {
            perror("Error or timeout reading from UART");
        }
        
        printf("-----------------------------------\n");
    }

    // Clean up
    close(uart_fd);
    fclose(file);
    printf("Finished successfully.\n");
    return EXIT_SUCCESS;
}