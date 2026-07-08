"""
TI mmWave Radar .dat File Viewer (PyQt5 version)

Converts the original matplotlib-script into an interactive PyQt5 application.
Parses TLV Type 2 (Range Profile) and TLV Type 5 (Range-Doppler Heatmap) frames
from a recorded .dat capture and lets you step through frames with a GUI.

Dependencies:
    pip install PyQt5 matplotlib numpy
"""

import sys
import struct
import numpy as np

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QSlider, QSpinBox, QMessageBox,
    QGroupBox, QFormLayout
)
from PyQt5.QtCore import Qt

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

# Adjust these based on your specific .cfg file parameters
# (e.g. numAdcSamples and chirp loops)
NUM_RANGE_BINS = 512
NUM_DOPPLER_BINS = 16


class RadarFrame:
    """Container for a single parsed frame's data."""
    def __init__(self, frame_num, total_packet_len):
        self.frame_num = frame_num
        self.total_packet_len = total_packet_len
        self.range_profile = None   # 1D np.uint16 array
        self.heatmap = None         # 2D np.uint16 array (RANGE_BINS x DOPPLER_BINS)


def parse_mmwave_dat(file_path, num_range_bins=NUM_RANGE_BINS, num_doppler_bins=NUM_DOPPLER_BINS, log_fn=print):
    """
    Parses a .dat file and returns a list of RadarFrame objects.
    log_fn is called with status/debug strings (defaults to print, but the
    GUI passes in something that writes to a log widget instead).
    """
    with open(file_path, 'rb') as f:
        file_data = f.read()

    frames = []
    frame_position = 0

    while True:
        frame_position = file_data.find(MAGIC_WORD, frame_position)
        if frame_position == -1:
            break

        try:
            header_format = '<QIIIIIIII'
            header_size = struct.calcsize(header_format)

            if frame_position + header_size > len(file_data):
                break

            header_bytes = file_data[frame_position: frame_position + header_size]
            header = struct.unpack(header_format, header_bytes)

            total_packet_len = header[2]
            frame_num = header[4]
            num_tlvs = header[7]

            log_fn(f"Frame {frame_num} | Total Packet: {total_packet_len} bytes")

            frame_obj = RadarFrame(frame_num, total_packet_len)

            tlv_pointer = frame_position + header_size

            for _ in range(num_tlvs):
                if tlv_pointer + 8 > len(file_data):
                    break

                tlv_type, tlv_len = struct.unpack('<II', file_data[tlv_pointer: tlv_pointer + 8])
                data_pointer = tlv_pointer + 8

                # --- TYPE 2: RANGE PROFILE ---
                if tlv_type == 2:
                    raw_payload = file_data[data_pointer: data_pointer + tlv_len]
                    range_profile = np.frombuffer(raw_payload, dtype=np.uint16)
                    log_fn(f"  [TLV Type 2] Parsed Range Profile. Shape: {range_profile.shape}")
                    frame_obj.range_profile = range_profile

                # --- TYPE 5: RANGE-DOPPLER HEATMAP ---
                elif tlv_type == 5:
                    raw_payload = file_data[data_pointer: data_pointer + tlv_len]
                    heatmap_flat = np.frombuffer(raw_payload, dtype=np.uint16)

                    try:
                        heatmap_2d = heatmap_flat.reshape((num_range_bins, num_doppler_bins))
                        log_fn(f"  [TLV Type 5] Parsed Range-Doppler Heatmap. Shape: {heatmap_2d.shape}")
                        frame_obj.heatmap = heatmap_2d
                    except ValueError:
                        log_fn(f"  [TLV Type 5] Warning: Heatmap data size "
                               f"({len(heatmap_flat)}) mismatched your bin settings.")

                else:
                    log_fn(f"  [TLV Type {tlv_type}] Found other data layer. Length: {tlv_len} bytes")

                tlv_pointer += 8 + tlv_len

            frames.append(frame_obj)
            frame_position += total_packet_len

        except Exception as e:
            log_fn(f"Error: {e}")
            frame_position += 8

    return frames


class RangeProfileCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4))
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)

    def plot(self, range_profile):
        self.ax.clear()
        if range_profile is not None:
            self.ax.plot(range_profile)
            self.ax.set_title("Range Profile")
            self.ax.set_xlabel("Range Bin Index")
            self.ax.set_ylabel("Amplitude")
            self.ax.grid(True)
        else:
            self.ax.set_title("No Range Profile TLV in this frame")
        self.draw()


class HeatmapCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(6, 4))
        super().__init__(self.fig)
        self.setParent(parent)
        self.ax = self.fig.add_subplot(111)
        self.colorbar = None

    def plot(self, heatmap_matrix, num_doppler_bins):
        # Fully clear the figure (not just the axes) and rebuild the axes
        # from scratch each time. fig.colorbar() permanently shrinks the
        # parent axes to make room for itself, and colorbar.remove() does
        # NOT restore the original axes geometry -- so reusing the same ax
        # across frames causes the plot to shrink sideways a little more
        # on every redraw. Recreating the axes avoids that entirely.
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self.colorbar = None

        if heatmap_matrix is not None:
            shifted_heatmap = np.fft.fftshift(heatmap_matrix, axes=1)
            log_heatmap = np.log10(shifted_heatmap + 1)

            extent = [-num_doppler_bins // 2, num_doppler_bins // 2 - 1,
                      0, heatmap_matrix.shape[0]]

            im = self.ax.imshow(log_heatmap, cmap='jet', aspect='auto',
                                 extent=extent, origin='lower')
            self.colorbar = self.fig.colorbar(im, ax=self.ax, label='Log Energy / Intensity')
            self.ax.set_title('TI mmWave Range-Doppler Heatmap')
            self.ax.set_xlabel(r'Doppler Bin Index ($\leftarrow$ Away | Toward $\rightarrow$)')
            self.ax.set_ylabel('Range Bin Index (Distance)')
            self.ax.grid(color='w', linestyle='--', alpha=0.5)
        else:
            self.ax.set_title("No Heatmap TLV in this frame")

        self.draw()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TI mmWave Radar .dat Viewer")
        self.resize(1300, 750)

        self.frames = []
        self.current_index = 0

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # --- Top control bar ---
        controls = QHBoxLayout()

        self.load_btn = QPushButton("Load .dat File...")
        self.load_btn.clicked.connect(self.load_file)
        controls.addWidget(self.load_btn)

        settings_group = QGroupBox("Reshape Settings")
        settings_layout = QFormLayout()
        self.range_bins_spin = QSpinBox()
        self.range_bins_spin.setRange(1, 8192)
        self.range_bins_spin.setValue(NUM_RANGE_BINS)
        self.doppler_bins_spin = QSpinBox()
        self.doppler_bins_spin.setRange(1, 1024)
        self.doppler_bins_spin.setValue(NUM_DOPPLER_BINS)
        settings_layout.addRow("Range Bins:", self.range_bins_spin)
        settings_layout.addRow("Doppler Bins:", self.doppler_bins_spin)
        settings_group.setLayout(settings_layout)
        controls.addWidget(settings_group)

        controls.addStretch()

        self.prev_btn = QPushButton("<< Prev Frame")
        self.prev_btn.clicked.connect(self.show_prev_frame)
        self.prev_btn.setEnabled(False)
        controls.addWidget(self.prev_btn)

        self.next_btn = QPushButton("Next Frame >>")
        self.next_btn.clicked.connect(self.show_next_frame)
        self.next_btn.setEnabled(False)
        controls.addWidget(self.next_btn)

        main_layout.addLayout(controls)

        # --- Frame slider + label ---
        slider_layout = QHBoxLayout()
        self.frame_label = QLabel("No file loaded")
        slider_layout.addWidget(self.frame_label)

        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setEnabled(False)
        self.frame_slider.valueChanged.connect(self.on_slider_changed)
        slider_layout.addWidget(self.frame_slider)

        main_layout.addLayout(slider_layout)

        # --- Plots ---
        plots_layout = QHBoxLayout()
        self.range_canvas = RangeProfileCanvas(self)
        self.heatmap_canvas = HeatmapCanvas(self)
        plots_layout.addWidget(self.range_canvas)
        plots_layout.addWidget(self.heatmap_canvas)
        main_layout.addLayout(plots_layout, stretch=1)

        # --- Log output ---
        self.log_label = QLabel("Log:")
        main_layout.addWidget(self.log_label)

    def log(self, msg):
        # Keep only the last line visible to avoid an ever-growing label;
        # swap this out for a QTextEdit if you want full scrollback.
        self.log_label.setText(f"Log: {msg}")
        QApplication.processEvents()

    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select mmWave .dat File", "", "DAT Files (*.dat);;All Files (*)"
        )
        if not file_path:
            return

        num_range_bins = self.range_bins_spin.value()
        num_doppler_bins = self.doppler_bins_spin.value()

        try:
            self.frames = parse_mmwave_dat(
                file_path,
                num_range_bins=num_range_bins,
                num_doppler_bins=num_doppler_bins,
                log_fn=self.log
            )
        except Exception as e:
            QMessageBox.critical(self, "Error parsing file", str(e))
            return

        if not self.frames:
            QMessageBox.warning(self, "No frames found",
                                 "No valid frames (magic word) were found in this file.")
            return

        self.current_index = 0
        self.frame_slider.setEnabled(True)
        self.frame_slider.setMinimum(0)
        self.frame_slider.setMaximum(len(self.frames) - 1)
        self.frame_slider.setValue(0)

        self.prev_btn.setEnabled(True)
        self.next_btn.setEnabled(True)

        self.update_display()

    def on_slider_changed(self, value):
        self.current_index = value
        self.update_display()

    def show_prev_frame(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.frame_slider.setValue(self.current_index)

    def show_next_frame(self):
        if self.current_index < len(self.frames) - 1:
            self.current_index += 1
            self.frame_slider.setValue(self.current_index)

    def update_display(self):
        if not self.frames:
            return

        frame = self.frames[self.current_index]
        num_doppler_bins = self.doppler_bins_spin.value()

        self.frame_label.setText(
            f"Frame {frame.frame_num} ({self.current_index + 1}/{len(self.frames)}) "
            f"| Packet size: {frame.total_packet_len} bytes"
        )

        self.range_canvas.plot(frame.range_profile)
        self.heatmap_canvas.plot(frame.heatmap, num_doppler_bins)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
