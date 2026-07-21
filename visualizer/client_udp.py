import sys
import socket
import struct
import numpy as np
from PyQt5 import QtCore, QtWidgets
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


# --- Network & Radar Dimensions ---
SERVER_IP = "192.168.1.7"
SERVER_PORT = 5001
MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

NUM_RANGE_BINS = 512
NUM_DOPPLER_BINS = 16


class RadarNetworkWorker(QtCore.QThread):
    range_profile_signal = QtCore.pyqtSignal(np.ndarray)
    heatmap_signal = QtCore.pyqtSignal(np.ndarray)

    def __init__(self):
        super().__init__()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(1.0)
        self.running = True
        self.data_buffer = bytearray()
        self.header_struct = struct.Struct('!III')

    def run(self):
        self.sock.sendto(b"RESET\n", (SERVER_IP, SERVER_PORT))

        while self.running:
            try:
                packet, _ = self.sock.recvfrom(8192)
                if len(packet) < self.header_struct.size:
                    continue

                p_type, _, p_len = self.header_struct.unpack(packet[:self.header_struct.size])
                payload = packet[self.header_struct.size: self.header_struct.size + p_len]

                if p_type == 99:
                    self.data_buffer = bytearray()
                elif p_type == 2:
                    self.data_buffer.extend(payload)
                    self.parse_buffer()

            except socket.timeout:
                self.sock.sendto(b"\n", (SERVER_IP, SERVER_PORT))
            except Exception as e:
                print(f"Network error: {e}")

    def parse_buffer(self):
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

            # tlv_len is the PAYLOAD length only (it does NOT include the
            # 8-byte type+length TLV header). This must match the pointer
            # advance below (`pointer += 8 + tlv_len`) -- previously this
            # line subtracted 8 from tlv_len here, which silently chopped
            # the last 4 uint16 samples off of every single TLV (including
            # the heatmap), corrupting/zero-padding the reshaped matrix.
            payload = frame_bytes[data_ptr: data_ptr + tlv_len]

            print(f"Extracted TLV Type: {tlv_type}, Length: {tlv_len}, "
                  f"Payload bytes actually available: {len(payload)}")

            if tlv_type == 2:
                arr = np.frombuffer(payload, dtype=np.uint16)
                self.range_profile_signal.emit(arr.copy())

            elif tlv_type == 5:  # Heatmap matrix target array handling
                expected_elements = NUM_RANGE_BINS * NUM_DOPPLER_BINS  # 512 * 16 = 8192
                expected_bytes = expected_elements * 2                 # uint16 -> 16384 bytes

                if len(payload) != expected_bytes:
                    print(f"  [WARN] Heatmap TLV size mismatch: got {len(payload)} bytes, "
                          f"expected {expected_bytes} bytes "
                          f"(tlv_len={tlv_len}). Check NUM_RANGE_BINS/NUM_DOPPLER_BINS "
                          f"against your .cfg, and confirm tlv_len semantics with the server.")

                # Bound the payload to what we need, then pad with zeros if short
                # so a partial/corrupt frame doesn't crash the reshape.
                truncated_payload = payload[:expected_bytes]
                matrix_flat = np.frombuffer(truncated_payload, dtype=np.uint16)

                if len(matrix_flat) < expected_elements:
                    padded_array = np.zeros(expected_elements, dtype=np.uint16)
                    padded_array[:len(matrix_flat)] = matrix_flat
                    matrix_flat = padded_array

                matrix_2d = matrix_flat.reshape((NUM_RANGE_BINS, NUM_DOPPLER_BINS))

                shifted_matrix = np.fft.fftshift(matrix_2d, axes=1)
                log_matrix = np.log10(shifted_matrix + 1)

                self.heatmap_signal.emit(log_matrix.copy())

            pointer += 8 + tlv_len

    def stop(self):
        self.running = False
        self.wait()


class RangeProfileCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4))
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self.line, = self.ax.plot([])
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
        self.colorbar = None
        self.im = None

    def update_data(self, log_matrix, num_doppler_bins=NUM_DOPPLER_BINS):
        if self.im is None:
            extent = [-num_doppler_bins // 2, num_doppler_bins // 2 - 1,
                      0, log_matrix.shape[0]]

            self.im = self.ax.imshow(log_matrix, cmap='jet', aspect='auto',
                                      extent=extent, origin='lower')
            self.colorbar = self.fig.colorbar(self.im, ax=self.ax, label='Log Energy / Intensity')
            self.ax.set_title('TI mmWave Range-Doppler Heatmap')
            self.ax.set_xlabel(r'Doppler Bin Index ($\leftarrow$ Away | Toward $\rightarrow$)')
            self.ax.set_ylabel('Range Bin Index (Distance)')
            self.ax.grid(color='w', linestyle='--', alpha=0.5)
        else:
            self.im.set_data(log_matrix)
            self.im.set_clim(vmin=float(log_matrix.min()), vmax=float(log_matrix.max()))

        self.draw_idle()


class RadarMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TI mmWave Radar Live Plotter (TCP, matplotlib)")
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
        min_val = float(np.min(log_matrix))
        max_val = float(np.max(log_matrix))
        print(f"[DEBUG GRAPH UPDATE] Processing bounds: Min={min_val:.2f}, Max={max_val:.2f}")
        self.heatmap_canvas.update_data(log_matrix.astype(np.float32))

    def closeEvent(self, event):
        self.thread.stop()
        event.accept()


if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    window = RadarMainWindow()
    window.show()
    sys.exit(app.exec_())
