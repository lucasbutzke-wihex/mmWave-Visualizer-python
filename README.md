# mmWave Visualizer (Python)

A Python-based real-time visualizer for **Texas Instruments mmWave radar sensors**. This project provides a lightweight and extensible interface for receiving, parsing, and displaying radar point cloud data, making it useful for development, debugging, research, and algorithm validation.

The application is designed to serve as an alternative to vendor visualization tools while allowing easy customization and integration into your own projects.

---

## Features

- 📡 Real-time communication with TI mmWave radar sensors
- 📈 Live visualization of detected targets
- 🎯 Point cloud rendering
- ⚡ High-performance Python implementation
- 🔧 Easy to modify and extend
- 🖥️ Cross-platform (Linux, Windows, macOS)
- 🧩 Modular architecture for future radar processing algorithms

---

## Demo

> *(Add screenshots or GIFs here)*

Example:

```
docs/images/demo.gif
```

or

```
docs/images/screenshot.png
```

---

## Supported Hardware

The visualizer is intended for Texas Instruments mmWave radar devices, including (but not limited to):

- IWR6843
- IWR1843
- AWR1843
- Other devices using compatible UART output

---

## Requirements

- Python 3.10+
- Serial connection to the radar
- Radar configured with an appropriate `.cfg` configuration

---

## Installation

Clone the repository:

```bash
git clone https://github.com/lucasbutzke-wihex/mmWave-Visualizer-python.git

cd mmWave-Visualizer-python
```

Create a virtual environment (recommended):

```bash
python -m venv .venv
```

Activate it:

### Linux/macOS

```bash
source .venv/bin/activate
```

### Windows

```cmd
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Running

Connect the radar to your computer.

Determine the serial ports:

- CLI Port
- Data Port

Update the serial port configuration if necessary.

Run:

```bash
python main.py
```

or

```bash
python visualizer.py
```

*(Replace with the actual entry point if different.)*

---

## Radar Configuration

Load your desired radar configuration (`.cfg`) before starting the visualizer.

Typical configuration sequence:

1. Connect radar
2. Open CLI serial port
3. Send configuration file
4. Start frame generation
5. Launch the visualizer

---

## Project Structure

```
mmWave-Visualizer-python/
│
├── parser/            # UART packet parser
├── visualization/     # Plotting and rendering
├── config/            # Radar configuration files
├── utils/             # Utility functions
├── requirements.txt
├── README.md
└── main.py
```

*(Update the structure to match the repository.)*

---

## Future Improvements

- [ ] Range-Doppler heatmaps
- [ ] Range-Azimuth visualization
- [ ] 3D point cloud rendering
- [ ] Target tracking (Kalman Filter)
- [ ] CFAR visualization
- [ ] Recording and playback
- [ ] ROS2 support
- [ ] Occupancy mapping
- [ ] Multi-radar synchronization
- [ ] Export to CSV/PCAP

---

## Contributing

Contributions are welcome!

If you would like to improve the project:

1. Fork the repository
2. Create a feature branch

```bash
git checkout -b feature/my-feature
```

3. Commit your changes

```bash
git commit -m "Add new feature"
```

4. Push

```bash
git push origin feature/my-feature
```

5. Open a Pull Request

---

## References

- Texas Instruments mmWave SDK
- Texas Instruments Industrial Toolbox
- mmWave signal processing literature
- FMCW radar fundamentals :contentReference[oaicite:0]{index=0}

---

## License

This project is released under the MIT License unless stated otherwise.

---

## Author

**Lucas Butzke**

GitHub:
https://github.com/lucasbutzke-wihex

---

## Acknowledgments

Special thanks to the Texas Instruments mmWave ecosystem and the open-source radar community for providing valuable examples, documentation, and research that inspired this project. :contentReference[oaicite:1]{index=1}