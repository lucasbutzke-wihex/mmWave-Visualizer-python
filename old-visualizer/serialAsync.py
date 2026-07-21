import asyncio
import serial, serial_asyncio_fast


import logging # Logging (possible levels: DEBUG, INFO, WARNING, ERROR, CRITICAL)

# Uncomment this line for logging with timestamps
logging.basicConfig(format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s', datefmt='%Y-%m-%d:%H:%M:%S', level=logging.INFO)
# logging.basicConfig(format='%(levelname)-8s [%(filename)s:%(lineno)d] %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)

from gui_parser import UARTParser
from demo_defines import *
from parseFrame import parseStandardFrame

def handle_line(line: str):
    print(f"LINE: {line!r}")

class SerialCore(asyncio.Protocol):
	def __init__(self, on_line):
		self.device = "xWR6843"
		self.demo = DEMO_OOB_x843

		self.on_line = on_line
		self.buf = bytearray()
		
		self.transport = None
		self.parser = UARTParser(type="DoubleCOMPort")
	
	def connection_made(self, transport):
		self.transport = transport
		print("Serial port opened")
		self.write_data('help\n')  # Write serial data via transport
	
	def connection_lost(self, exc):
		print("Serial port closed")
		asyncio.get_event_loop().stop()

	def data_received(self, data: bytes):
		self.buf.extend(data)
		try:
			# data = data.decode(errors='ignore')
			while b'\n' in self.buf:
				line, _, rest = self.buf.partition(b'\n')
				self.buf = bytearray(rest)

				# Strip stray \r (this device uses \n\r instead of \r\n)
				text = line.replace(b'\r', b'').decode(errors='replace')

				if text:  # skip empty lines from \n\r\n sequences
					self.on_line(text)

		except Exception as e:
			log.exception(f'{e}')
		
		# if data not in ['', ' ']:
		# 	print(data.encode())
	
	def write_data(self, data: bytes):
		self.transport.write(data.encode())  # Write serial data via transport

	def connection_lost(self, exc):
        # flush any remaining partial line
		if self.buf:
			text = self.buf.replace(b'\r', b'').decode(errors='replace')
			if text:
				self.on_line(text)
			log.exception(f"Serial connection closed: {exc}")


# async def main():
#     try:
#         transport, protocol = await serial_asyncio.create_serial_connection(
#             asyncio.get_running_loop(),
#             SerialReader,
#             "/dev/ttyUSB0",      # Linux
#             baudrate=115200,
#         )
#         try:
#             await asyncio.Future()  # Run forever
#         finally:
#             transport.close()

#     except serial.serialutil.SerialException as e:
#         print(f"Exception {e}")


# if __name__ == "__main__":
#     asyncio.run(main())