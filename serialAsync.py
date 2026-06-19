import asyncio
import serial, serial_asyncio


class SerialReader(asyncio.Protocol):
    def connection_made(self, transport):
        self.transport = transport
        print("Serial port opened")

    def data_received(self, data):
        try:
            data = data.decode(errors='ignore')
        except AttributeError:
            pass

        if data not in ['', ' ']:
            print(data.encode())

    def connection_lost(self, exc):
        print("Serial port closed")
        asyncio.get_event_loop().stop()


async def main():
    try:
        transport, protocol = await serial_asyncio.create_serial_connection(
            asyncio.get_running_loop(),
            SerialReader,
            "/dev/ttyUSB0",      # Linux
            baudrate=115200,
        )
        try:
            await asyncio.Future()  # Run forever
        finally:
            transport.close()

    except serial.serialutil.SerialException as e:
        print(f"Exception {e}")


asyncio.run(main())