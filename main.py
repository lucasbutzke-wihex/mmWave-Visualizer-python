# PySide2 Imports
# from PySide6.QtCore import Qt
# from PySide6.QtWidgets import QApplication
# from PySide6.QtGui import QPalette, QColor

# Window Class
# from gui_core import Window
import asyncio
import serial_asyncio_fast

# from serialAsync import SerialReader

from cached_data import CachedDataType
from serialAsync import SerialCore, handle_line

import sys
import os
import logging # Logging (possible levels: DEBUG, INFO, WARNING, ERROR, CRITICAL)

# Uncomment this line for logging with timestamps
logging.basicConfig(format='%(asctime)s,%(msecs)03d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s', datefmt='%Y-%m-%d:%H:%M:%S', level=logging.INFO)
# logging.basicConfig(format='%(levelname)-8s [%(filename)s:%(lineno)d] %(message)s', level=logging.INFO)
log = logging.getLogger(__name__)

# add common folder to path
sys.path.insert(1, os.path.abspath(os.getcwd()) + "\\common") # Uncomment for debug in VSCode or running from Applications_Visualizer dir
sys.path.insert(1, '../common')


async def main():
	try:
		cliTransport, _ = await serial_asyncio_fast.create_serial_connection(
            asyncio.get_running_loop(),
			lambda: SerialCore(handle_line),
            "/dev/ttyUSB0",      # Linux
            baudrate=115200,
        )
		
		# dataTransport, _ = await serial_asyncio_fast.create_serial_connection(
        #     asyncio.get_running_loop(),
        #     SerialCore,
        #     "/dev/ttyUSB1",      # Linux
        #     baudrate=912600,
        # ) 

		# dataTransport.reset_output_buffer()

		try:
			await asyncio.Future()  # Run forever
		finally:
			cliTransport.close()
			# dataTransport.close()
	
	except Exception as e:
		print(f"Exception {e}")

if __name__ == '__main__':
	asyncio.run(main())
