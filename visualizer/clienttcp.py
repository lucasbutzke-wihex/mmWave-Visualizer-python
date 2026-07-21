import sys
import socket
import struct
import numpy as np

from PyQt5 import QtCore, QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# --- Network & Radar Dimensions ---
SERVER_IP = "192.168.2.100"
SERVER_PORT = 5001
MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

NUM_RANGE_BINS = 512
NUM_DOPPLER_BINS = 16


class RadarNetworkWorker(QtCore.QThread):
    range_profile_signal = QtCore.pyqtSignal(np.ndarray)
    heatmap_signal = QtCore.pyqtSignal(np.ndarray)

    def __init__(self):
        super().__init__()
        self.running = True
        self.sock = None
        
        # Accumulators for TCP stream slicing
        self.network_buffer = bytearray()
        self.data_buffer = bytearray()
        
        # Network Header: packet_type (I), sequence_num (I), payload_len (I)
        self.header_struct = struct.Struct('!III')

    def connect_to_server(self):
        """Attempts to establish a reliable TCP handshake connection."""
        while self.running:
            try:
                print(f"Connecting to TCP Server at {SERVER_IP}:{SERVER_PORT}...")
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(2.0)
                self.sock.connect((SERVER_IP, SERVER_PORT))
                print("TCP Connected! Registering device...")
                self.sock.sendall(b"RESET\n")
                return True
            except Exception as e:
                print(f"Connection failed: {e}. Retrying in 2 seconds...")
                QtCore.QThread.msleep(2000)
        return False

    def run(self):
        if not self.connect_to_server():
            return

        while self.running:
            try:
                # Read incoming raw TCP chunk streams
                chunk = self.sock.recv(16384)
                if not chunk:
                    print("Server closed connection.")
                    raise ConnectionError()

                self.network_buffer.extend(chunk)

                # --- Outer TCP Stream Slicing Loop ---
                # Extracts individual protocol packets based on the network header
                while len(self.network_buffer) >= self.header_struct.size:
                    p_type, _, p_len = self.header_struct.unpack(
                        self.network_buffer[:self.header_struct.size]
                    )
                    
                    total_packet_size = self.header_struct.size + p_len
                    if len(self.network_buffer) < total_packet_size:
                        break  # Wait for the rest of this payload to arrive

                    # Extract payload data out of the stream slice bounds
                    payload = self.network_buffer[self.header_struct.size : total_packet_size]
                    del self.network_buffer[:total_packet_size]

                    if p_type == 99:
                        print("[SYSTEM ACK] Queue cleared.")
                        self.data_buffer.clear()
                    elif p_type == 2:  # Radar packet payload
                        self.data_buffer.extend(payload)
                        self.parse_buffer()

            except (socket.timeout, socket.error) as e:
                if isinstance(e, socket.timeout):
                    # TCP Keepalive check
                    try:
                        self.sock.sendall(b"\n")
                    except:
                        pass
                else:
                    print(f"Connection lost: {e}")
                    self.sock.close()
                    if not self.connect_to_server():
                        break

    def parse_buffer(self):
        """Sliding window alignment parsing tailored for TI mmWave Frames."""
        while len(self.data_buffer) >= 48:
            magic_idx = self.data_buffer.find(MAGIC_WORD)
            if magic_idx == -1:
                if len(self.data_buffer) > 32:
                    self.data_buffer = self.data_buffer[-7:]
                break

            if magic_idx > 0:
                self.data_buffer = self.data_buffer[magic_idx:]

            if len(self.data_buffer) < 16:
                break

            total_packet_len = struct.unpack('<I', self.data_buffer[12:16])[0]
            if len(self.data_buffer) < total_packet_len:
                break

            frame_bytes = self.data_buffer[:total_packet_len]
            self.data_buffer = self.data_buffer[total_packet_len:]
            self.extract_tlvs(frame_bytes)

    def extract_tlvs(self, frame_bytes):
        header_format = '<QIIIIIIII'
        h_size = struct.calcsize(header_format)
        if len(frame_bytes) < h_size:
            return

        header = struct.unpack(header_format, frame_bytes[:h_size])
        num_tlvs = header[7]

        pointer = h_size
        for _ in range(num_tlvs):
            if pointer + 8 > len(frame_bytes):
                break
            tlv_type, tlv_len = struct.unpack('<II', frame_bytes[pointer: pointer + 8])
            data_ptr = pointer + 8

            payload = frame_bytes[data_ptr: data_ptr + tlv_len]

            if tlv_type == 2:
                arr = np.frombuffer(payload, dtype=np.uint16)
                self.range_profile_signal.emit(arr[:NUM_RANGE_BINS].copy())

            elif tlv_type == 5:
                expected_elements = NUM_RANGE_BINS * NUM_DOPPLER_BINS
                expected_bytes = expected_elements * 2

                truncated_payload = payload[:expected_bytes]
                matrix_flat = np.frombuffer(truncated_payload, dtype=np.int16)

                if len(matrix_flat) < expected_elements:
                    padded_array = np.zeros(expected_elements, dtype=np.int16)
                    padded_array[:len(matrix_flat)] = matrix_flat
                    matrix_flat = padded_array

                matrix_2d = matrix_flat.reshape((NUM_RANGE_BINS, NUM_DOPPLER_BINS))
                shifted_matrix = np.fft.fftshift(matrix_2d, axes=1)
                
                log_matrix = np.log10(np.abs(shifted_matrix) + 1.0)
                self.heatmap_signal.emit(log_matrix.copy())

            pointer += 8 + tlv_len

    def stop(self):
        self.running = False
        try:
            if self.sock:
                self.sock.close()
        except:
            pass
        self.wait()


class RangeProfileCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4))
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self.line, = self.ax.plot([], [])
        self.ax.set_title("Range Profile")
        self.ax.set_xlabel("Range Bin Index")
        self.ax.set_ylabel("Amplitude")
        self.ax.grid(True)

    def update_data(self, range_profile):
        self.line.set_data(np.arange(len(range_profile)), range_profile)
        self.ax.relim()
        self.ax.autoscale_view()
        self.draw()


class HeatmapCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4))
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        
        init_data = np.zeros((NUM_RANGE_BINS, NUM_DOPPLER_BINS))
        extent = [-NUM_DOPPLER_BINS // 2, NUM_DOPPLER_BINS // 2 - 1, 0, NUM_RANGE_BINS]
        
        self.im = self.ax.imshow(init_data, cmap='jet', aspect='auto', extent=extent, origin='lower')
        self.colorbar = self.fig.colorbar(self.im, ax=self.ax, label='Log Energy / Intensity')
        
        self.ax.set_title('TI mmWave Range-Doppler Heatmap')
        self.ax.set_xlabel(r'Doppler Bin Index ($\leftarrow$ Away | Toward $\rightarrow$)')
        self.ax.set_ylabel('Range Bin Index (Distance)')
        self.ax.grid(color='w', linestyle='--', alpha=0.5)

    def update_data(self, log_matrix):
        self.im.set_data(log_matrix)
        self.im.set_clim(vmin=log_matrix.min(), vmax=log_matrix.max())
        self.draw()


class RadarMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TI mmWave Radar Live Plotter (TCP Client)")
        self.resize(1300, 700)

        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        layout = QtWidgets.QHBoxLayout(central_widget)

        self.range_canvas = RangeProfileCanvas(self)
        self.heatmap_canvas = HeatmapCanvas(self)
        layout.addWidget(self.range_canvas)
        layout.addWidget(self.heatmap_canvas)

        self.thread = RadarNetworkWorker()
        self.thread.range_profile_signal.connect(self.update_line_plot)
        self.thread.heatmap_signal.connect(self.update_heatmap_plot)
        self.thread.start()

    @QtCore.pyqtSlot(np.ndarray)
    def update_line_plot(self, data):
        self.range_canvas.update_data(data)

    @QtCore.pyqtSlot(np.ndarray)
    def update_heatmap_plot(self, log_matrix):
        self.heatmap_canvas.update_data(log_matrix.astype(np.float32))

    def closeEvent(self, event):
        self.thread.stop()
        event.accept()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = RadarMainWindow()
    window.show()
    sys.exit(app.exec_())
