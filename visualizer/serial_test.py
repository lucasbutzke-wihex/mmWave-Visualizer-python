import serial
import time

# --- CONFIGURATION ---
PORT_NAME = 'COM3'        # Change to your sender port (e.g., '/dev/ttyUSB0' on Linux)
BAUD_RATE = 9600          # Ensure this matches the receiver's baud rate
FILE_PATH = 'data.txt'    # The file you want to read
TIMEOUT = 5               # Seconds to wait for a response before timing out
# ---------------------

try:
    print(f"Opening serial port {PORT_NAME}...")
    with serial.Serial(PORT_NAME, BAUD_RATE, timeout=TIMEOUT) as ser:
        # Give the serial connection a moment to initialize
        time.sleep(2) 
        
        print(f"Reading from {FILE_PATH}...")
        with open(FILE_PATH, 'r', encoding='utf-8') as file:
            for line_num, line in enumerate(file, 1):
                # Ensure the line ends with a newline character so the receiver knows it's complete
                if not line.endswith('\n'):
                    line += '\n'
                
                print(f"[Line {line_num}] Sending: {line.strip()}")
                ser.write(line.encode('utf-8'))
                
                # Wait for the response line from the other port
                # readline() will block until a '\n' is received or the timeout is reached
                response = ser.readline()
                
                if response:
                    print(f"-> Response received: {response.decode('utf-8').strip()}")
                else:
                    print(f"-> [Warning] Timed out waiting for response on line {line_num}!")
                    
    print("File transmission complete.")

except FileNotFoundError:
    print(f"Error: The file '{FILE_PATH}' was not found. Please check the path.")
except serial.SerialException as e:
    print(f"Serial communication error: {e}")
