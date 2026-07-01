import asyncio
import struct
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'
HOST = '0.0.0.0'  # Listen on all local network interfaces
PORT = 8888       # Port for clients to connect to

class RadarDataServer:
    def __init__(self, file_path):
        self.file_path = file_path
        self.connected_clients = set()  # Track active client writers
        self.data_queue = asyncio.Queue(maxsize=100)  # Buffer to hold outgoing frames

    async def client_handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handles lifecycle of each connected TCP client."""
        client_address = writer.get_extra_info('peername')
        logging.info(f"Client connected: {client_address}")
        self.connected_clients.add(writer)

        try:
            # Keep the connection alive; wait for client disconnect or errors
            while True:
                # If clients send data back (optional heartbeats), read it to prevent buffer fill
                data = await reader.read(1024)
                if not data:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            logging.info(f"Client disconnected: {client_address}")
            self.connected_clients.remove(writer)
            writer.close()
            await writer.wait_closed()

    async def broadcaster(self):
        """Asynchronously pulls frames from the queue and broadcasts them to everyone."""
        while True:
            # Wait for a parsed frame to arrive in the queue
            frame_bytes = await self.data_queue.get()
            
            if not self.connected_clients:
                self.data_queue.task_done()
                continue

            # Create write tasks for all clients to broadcast concurrently
            disconnect_targets = []
 
            for client in list(self.connected_clients):
                try:
                    client.write(frame_bytes)
                    print(f'Dado enviado: {frame_bytes}')
                    await client.drain()  # Ensure buffer is cleared smoothly
 
                except (ConnectionResetError, BrokenPipeError):
                    disconnect_targets.append(client)
            
            # Clean up dead connections caught during write
            for dead_client in disconnect_targets:
                if dead_client in self.connected_clients:
                    self.connected_clients.remove(dead_client)

            self.data_queue.task_done()

    def parse_file_sync(self):
        """Synchronously reads and yields valid raw frames from the file."""
        with open(self.file_path, 'rb') as f:
            file_data = f.read()

        frame_position = 0
        header_format = '<QIIIIIIII'
        header_size = struct.calcsize(header_format)

        while True:
            frame_position = file_data.find(MAGIC_WORD, frame_position)
            if frame_position == -1:
                break

            try:
                if frame_position + header_size > len(file_data):
                    break

                header_bytes = file_data[frame_position : frame_position + header_size]
                header = struct.unpack(header_format, header_bytes)
                total_packet_len = header[2]

                if frame_position + total_packet_len <= len(file_data):
                    # Slice the ENTIRE frame packet (Header + all TLVs)
                    entire_frame = file_data[frame_position : frame_position + total_packet_len]
                    yield entire_frame
                    frame_position += total_packet_len
                else:
                    break
            except Exception:
                frame_position += 8

    async def frame_producer(self):
        """Feeds the queue from our data generator, mocking the 250ms radar frame interval."""
        # Run the heavy file I/O operations inside an executor pool to prevent blocking the async loop
        loop = asyncio.get_running_loop()
        
        # Generator for reading the packets sequentially
        frame_generator = self.parse_file_sync()
        
        logging.info("Starting frame streaming simulation...")
        for frame in frame_generator:
            # Put the packet data in the queue (waits if queue is full)
            await self.data_queue.put(frame)
            
            # Emulate the physical radar timing (250ms per frame)
            await asyncio.sleep(0.250)
        
        logging.info("Finished streaming all frames from the .dat file.")

    async def start(self):
        """Main runner method initializing the TCP server and parallel tasks."""
        # Start the TCP server instance
        server = await asyncio.start_server(self.client_handler, HOST, PORT)
        logging.info(f"TCP Radar Server running on {HOST}:{PORT}")

        # Schedule background worker loops
        broadcast_task = asyncio.create_task(self.broadcaster())
        producer_task = asyncio.create_task(self.frame_producer())

        # Keep everything running concurrently
        async with server:
            await asyncio.gather(producer_task, broadcast_task, return_exceptions=True)

if __name__ == "__main__":
    # Ensure you match this path with your data file
    radar_server = RadarDataServer("radar_data.dat")
    try:
        asyncio.run(radar_server.start())
    except KeyboardInterrupt:
        logging.info("Server stopped manually.")
