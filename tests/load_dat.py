import struct
import numpy as np
import matplotlib.pyplot as plt


MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'

# Adjust these based on your specific .cfg file parameters
# (e.g. numAdcSamples and chirp loops)
NUM_RANGE_BINS = 512
NUM_DOPPLER_BINS = 16

def plot_heatmap(heatmap_matrix):
    """
    Takes a 2D numpy array of shape (NUM_RANGE_BINS, NUM_DOPPLER_BINS)
    and plots it as a Range-Doppler Heatmap.
    """
    plt.figure(figsize=(10, 6))
    
    # Shift the Doppler axis so 0 velocity is in the center
    # This moves negative velocities to the left and positive to the right
    shifted_heatmap = np.fft.fftshift(heatmap_matrix, axes=1)
    
    # We transpose (.T) or use origin='lower' to align Range on Y-axis and Doppler on X-axis
    # Log scale (np.log10) is often applied to radar data to see weaker targets better
    log_heatmap = np.log10(shifted_heatmap + 1) 
    
    # Plot using imshow
    # X-axis: Doppler Bins (-32 to +31)
    # Y-axis: Range Bins (0 to 127)
    extent = [-NUM_DOPPLER_BINS//2, NUM_DOPPLER_BINS//2 - 1, 0, NUM_RANGE_BINS]
    
    im = plt.imshow(log_heatmap, cmap='jet', aspect='auto', 
                    extent=extent, origin='lower')
    
    plt.colorbar(im, label='Log Energy / Intensity')
    plt.title('TI mmWave Range-Doppler Heatmap')
    # Fixed using a raw string (r"...") to prevent parsing escape sequences
    plt.xlabel(r'Doppler Bin Index (Velocity $\leftarrow$ Moving Away | Moving Toward $\rightarrow$)')
    plt.ylabel('Range Bin Index (Distance)')
    plt.grid(color='w', linestyle='--', alpha=0.5)
    
    plt.show()

def parse_advanced_mmwave_dat(file_path):
    with open(file_path, 'rb') as f:
        file_data = f.read()
    
    frame_position = 0
    frame_count = 0

    plt.figure()
    
    while True:
        frame_position = file_data.find(MAGIC_WORD, frame_position)
        if frame_position == -1:
            break
            
        try:
            header_format = '<QIIIIIIII' 
            header_size = struct.calcsize(header_format)
            
            if frame_position + header_size > len(file_data):
                break
                
            header_bytes = file_data[frame_position : frame_position + header_size]
            header = struct.unpack(header_format, header_bytes)
            
            total_packet_len = header[2]
            frame_num        = header[4]
            num_tlvs         = header[7]
            
            print(f"\nFrame {frame_num} | Total Packet: {total_packet_len} bytes")
            
            tlv_pointer = frame_position + header_size
            
            for _ in range(num_tlvs):
                if tlv_pointer + 8 > len(file_data):
                    break
                    
                tlv_type, tlv_len = struct.unpack('<II', file_data[tlv_pointer : tlv_pointer + 8])
                data_pointer = tlv_pointer + 8
                
                # --- TYPE 2: RANGE PROFILE ---
                if tlv_type == 2:
                    # TI sends Range Profile as an array of 16-bit unsigned ints (Q9 format)
                    # Length = NUM_RANGE_BINS * 2 bytes
                    num_elements = tlv_len // 2
                    raw_payload = file_data[data_pointer : data_pointer + tlv_len]
                    
                    # Unpack using numpy directly for extreme speed
                    range_profile = np.frombuffer(raw_payload, dtype=np.uint16)
                    print(f"  [TLV Type 2] Parsed Range Profile. Shape: {range_profile.shape}")
                    # print(f"  [TLV Type 2] Parsed Range Profile:\n{range_profile}")       
                    plt.plot(range_profile)
                    plt.grid()
                
                # --- TYPE 5: RANGE-DOPPLER HEATMAP ---
                elif tlv_type == 5:
                    # TI sends the Range-Doppler Heatmap as an array of 16-bit unsigned ints
                    # Total elements = NUM_RANGE_BINS * NUM_DOPPLER_BINS
                    raw_payload = file_data[data_pointer : data_pointer + tlv_len]
                    
                    heatmap_flat = np.frombuffer(raw_payload, dtype=np.uint16)
                    
                    # Reshape into a 2D Matrix (Range Bins x Doppler Bins)
                    try:
                        heatmap_2d = heatmap_flat.reshape((NUM_RANGE_BINS, NUM_DOPPLER_BINS))
                        print(f"  [TLV Type 5] Parsed Range-Doppler Heatmap. Shape: {heatmap_2d.shape}")
                        # custom_processing_function(heatmap_2d) # <-- Your processing code here
                        print(f"  [TLV Type 5] Parsed Range-Doppler Heatmap:\n{heatmap_2d}")
                    except ValueError:
                        print(f"  [TLV Type 5] Warning: Heatmap data size ({len(heatmap_flat)}) mismatched your bin settings.")
                    
                    plot_heatmap(heatmap_2d)

                else:
                    print(f"  [TLV Type {tlv_type}] Found other data layer. Length: {tlv_len} bytes")
                
                tlv_pointer += 8 + tlv_len
                
            frame_position += total_packet_len
            frame_count += 1
            
        except Exception as e:
            print(f"Error: {e}")
            frame_position += 8

if __name__ == "__main__":
    parse_advanced_mmwave_dat("radar_data.dat")
