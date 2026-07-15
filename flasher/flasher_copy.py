#!/usr/bin/env python3
import sys
import os
import argparse

# Define a mock image object mimicking what the Uniflash UI usually passes
class ConsoleImage:
    def __init__(self, path, order=1):
        self.path = path
        self.order = order  # Order 1 maps to Meta Image 1 (offset 0x2000)

# Callback adapter to satisfy the BootLdr's GUI update expectations
class ConsoleCallback:
    def update_progress(self, message, percentage):
        print(f"[{percentage:3d}%] {message}")

    def push_message(self, message, level):
        # Maps trace levels to clean CLI logs
        # levels: 3=FATAL, 2=ERROR, 1=WARNING, 0=INFO, 255=DEBUG
        if level == 3:
            print(f"\033[91m[FATAL] {message}\033[0m")
        elif level == 2:
            print(f"\033[91m[ERROR] {message}\033[0m")
        elif level == 1:
            print(f"\033[93m[WARNING] {message}\033[0m")
        elif level == 0 or level == 255:
            print(f"[INFO] {message}")

    def check_is_cancel_set(self):
        return False

def main():
    parser = argparse.ArgumentParser(description="ARM Linux IWR6843/IWRL6844 Firmware Flasher")
    parser.add_argument("-p", "--port", required=True, help="Serial port (e.g., /dev/ttyUSB0)")
    parser.add_argument("-f", "--file", required=True, help="Path to firmware .bin file")
    parser.add_argument("-e", "--erase", action="store_true", help="Erase/Format SFLASH storage before writing")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.file):
        print(f"Error: Firmware file '{args.file}' not found.")
        sys.exit(1)

    # 1. Import TI's underlying engine
    try:
        import mmWaveProgFlash
    except ImportError:
        print("Error: Could not find TI's 'mmWaveProgFlash.py' library in this directory.")
        print("Ensure 'mmWaveProgFlash.py' and its dependencies are in the same folder.")
        sys.exit(1)

    print(f"Initializing flash sequence on {args.port}...")
    print("Please ensure the radar is in SOP5 (Flashing Mode) and has been reset.")

    # 2. Instantiate our CLI callback adapter and the BootLoader object
    callback = ConsoleCallback()
    # BootLdr takes (callback_instance, default_com_port, trace_level)
    ldr = mmWaveProgFlash.BootLdr(callback, args.port, trace_level=0)

    # 3. Define target properties (aligned with your IWR6843/IWRL6844 configs)
    # The serial bootloader identifies AWRL68/IWRL68 part prefixes as supported
    part_num = "IWRL6844"
    storage = "SFLASH"
    baudrate = 115200
    timeout_value = 10
    
    # Standard image placement offsets for xWRL68xx family
    address_offsets = [0x2000, 0xfc000, 0x1f6000, 0x2f0000]

    # 4. Begin Connection
    connected = ldr.connect(timeout_value, args.port, baudrate)
    if not connected:
        print("\033[91mFailed to connect to the serial port. Check connections and permissions.\033[0m")
        sys.exit(1)

    try:
        # Set target device type
        if ldr.isPartNumSupported(part_num):
            ldr.setPartNum(part_num)
        else:
            print(f"Unsupported Part Number: {part_num}")
            ldr.disconnect()
            sys.exit(1)

        # Prepare images queue
        images = [ConsoleImage(args.file, order=1)]
        files_list = ldr.copyImagesList(images)

        # Validate file header (expects 0x5254534D for xWR68xx)
        file_size_sum = 8192 # FIRST_IMAGE_OFFSET
        for item in files_list:
            if not ldr.checkFileHeader(item.path, item):
                print("\033[91mFile header check failed. Invalid radar binary format.\033[0m")
                ldr.disconnect()
                sys.exit(1)
            file_size_sum += item.fileSize

        # Calculate tracking milestones
        ldr.calcProgressValues(files_list, file_size_sum, args.erase)

        # 5. Optional Format Step
        if args.erase:
            callback.push_message("Formatting SFLASH storage...", 0)
            ldr.debug_fix()
            ldr.erase_storage()

        # 6. Flash Header Writes
        # Writes the dynamic flash index headers (mirroring offsets) to the 0th and 4KB sectors
        callback.push_message("Writing Flash Headers...", 0)
        flash_header_bytes = ldr.get_flash_header_bytes(address_offsets)
        if flash_header_bytes == b"":
            print("\033[91mFailed to generate Flash Header payload.\033[0m")
            ldr.disconnect()
            sys.exit(1)

        for sector in range(2):
            flash_offset = sector * 4096 # Write to 0x0000 and 0x1000
            success = ldr.download_flashheader_file(flash_offset, storage, flash_header_bytes)
            if not success:
                print("\033[91mFlash header write failed.\033[0m")
                ldr.disconnect()
                sys.exit(1)

        # 7. Write Firmware Binary
        # Writes your actual application binary to the designated offset location (0x2000)
        callback.push_message("Writing Firmware Binary to flash...", 0)
        for item in files_list:
            prog_milestones = ldr.getImageProgCntList(item)
            target_offset = address_offsets[item.order - 1] # Meta Image 1 -> 0x2000

            success = ldr.download_file_6844(
                item.path, 
                target_offset, 
                0, 0, 
                storage, 
                prog_milestones
            )
            if not success:
                print(f"\033[91mFailed to download file {item.path} to offset {hex(target_offset)}\033[0m")
                break
            else:
                print(f"\033[92mSuccessfully flashed MetaImage {item.order}!\033[0m")

    except Exception as e:
        print(f"\nRuntime Error during flashing: {e}")
    finally:
        # 8. Cleanup and Exit
        ldr.disconnect()
        print("\nProcess finished. Change switches to SOP4 (Functional) and reset your radar to execute.")

if __name__ == "__main__":
    main()
