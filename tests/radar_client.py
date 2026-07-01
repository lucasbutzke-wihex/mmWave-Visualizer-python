import asyncio
import struct
import numpy as np

MAGIC_WORD = b'\x02\x01\x04\x03\x06\x05\x08\x07'
SERVER_IP = '127.0.0.1'
SERVER_PORT = 8888

# As determined by your hardware parameters (256x32 setup or downsampled 128x64 setup)
NUM_RANGE_BINS = 256    
NUM_DOPPLER_BINS = 32   

async def parse_tlvs(data_bytes, num_tlvs):
    """Parses individual TLV sections from a verified frame's byte payload."""
    tlv_pointer = 0
    
    for _ in range(num_tlvs):
        if tlv_pointer + 8 > len(data_bytes):
            break
            
        tlv_type, tlv_len = struct.unpack('<II', data_bytes[tlv_pointer : tlv_pointer + 8])
        data_pointer = tlv_pointer + 8
        
        # Guard against truncated or incomplete TLV chunks over network
        if data_pointer + tlv_len > len(data_bytes):
            break
            
        raw_payload = data_bytes[data_pointer : data_pointer + tlv_len]
        
        # --- TYPE 2: RANGE PROFILE ---
        if tlv_type == 2:
            range_profile = np.frombuffer(raw_payload, dtype=np.uint16)
            print(f"    [TLV Type 2] Range Profile | Shape: {range_profile.shape}")
            # Process range_profile here (e.g., send to plotting queue)

        # --- TYPE 5: RANGE-DOPPLER HEATMAP ---
        elif tlv_type == 5:
            heatmap_flat = np.frombuffer(raw_payload, dtype=np.uint16)
            try:
                heatmap_2d = heatmap_flat.reshape((NUM_RANGE_BINS, NUM_DOPPLER_BINS))
                print(f"    [TLV Type 5] Range-Doppler Heatmap | Shape: {heatmap_2d.shape}")
                # Process heatmap_2d matrix here
            except ValueError:
                print(f"    [TLV Type 5] Warning: Heatmap mismatch. Data elements: {len(heatmap_flat)}")

        tlv_pointer += 8 + tlv_len

async def receive_radar_stream():
    """Connects to the server, parses headers, and handles the TCP chunk assembly."""
    print(f"Connecting to Radar Server at {SERVER_IP}:{SERVER_PORT}...")
    
    try:
        reader, writer = await asyncio.open_connection(SERVER_IP, SERVER_PORT)
        print("Connected successfully!")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    header_format = '<QIIIIIIII'
    header_size = struct.calcsize(header_format)
    
    # Persistent tracking buffer for the incoming stream fragments
    stream_buffer = b''

    try:
        while True:
            # Read network chunks as they arrive
            chunk = await reader.read(4096)
            if not chunk:
                print("Server closed connection.")
                break
                
            stream_buffer += chunk
            
            # Process as many complete frames as possible within our stream buffer
            while True:
                # 1. Search for the beginning of a frame
                magic_idx = stream_buffer.find(MAGIC_WORD)
                if magic_idx == -1:
                    # Keep only the last few bytes in case the magic word was cut in half
                    if len(stream_buffer) > len(MAGIC_WORD):
                        stream_buffer = stream_buffer[-(len(MAGIC_WORD)-1):]
                    break
                
                # Align stream buffer to start exactly at the magic word
                if magic_idx > 0:
                    stream_buffer = stream_buffer[magic_idx:]
                
                # 2. Check if we have enough bytes to decode the header safely
                if len(stream_buffer) < header_size:
                    break
                    
                header_bytes = stream_buffer[:header_size]
                header = struct.unpack(header_format, header_bytes)
                
                total_packet_len = header[2]
                frame_num        = header[4]
                num_tlvs         = header[7]
                
                # 3. Check if the entire packet payload has fully arrived over the wire
                if len(stream_buffer) < total_packet_len:
                    break # Wait for more data chunks to append to the buffer
                
                print(f"\n[Client Core] Received Frame #{frame_num} ({total_packet_len} bytes)")
                
                # Extract the TLV data block (excluding the fixed header)
                packet_payload = stream_buffer[header_size:total_packet_len]
                
                # Pass off to processing task so we don't stall network collection loops
                await parse_tlvs(packet_payload, num_tlvs)
                
                # Slice out the processed frame from the buffer, leaving trailing fragments intact
                stream_buffer = stream_buffer[total_packet_len:]
                
    except asyncio.CancelledError:
        print("\nStopping client listener...")
    finally:
        writer.close()
        await writer.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(receive_radar_stream())
    except KeyboardInterrupt:
        print("\nClient terminated manually.")
