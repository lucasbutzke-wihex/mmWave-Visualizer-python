CC = gcc
FLAGS = -Wall -Wextra -O2

all:
	$(CC) $(FLAGS) -o serial_reader main.c

foward:
	$(CC) $(FLAGS) -o udpServerForwarder udpServerForwarder.c
asm:
	$(CC) $(FLAGS) -S udpServerForwarder.c

claude:
	$(CC) $(FLAGS) -o claude claude_tcp_server.c