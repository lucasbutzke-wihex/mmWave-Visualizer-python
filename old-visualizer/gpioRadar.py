import RPi.GPIO as gpio
import time

"""
./dslite.sh --mode serial -e -c /home/wihex/Downloads/IWR6843.ccxml -s COMPort=/dev/ttyUSB0 -f /home/wihex/workspace_ccstheia/wihex_long_range_mss/Debug/long_range_people_det_6843_demo.bin,1 /home/wihex/workspace_ccstheia/wihex_long_range_dss/Debug/long_range_people_det_6843_dss.bin,2
"""

class gpioCommand():
    # Pin assignments
    PIN_SOP = 23      # boot mode select (SOP2), sampled at reset
    PIN_RESET = 24    # NRESET, active low

    # SOP pin levels (adjust to match your board's actual SOP strapping)
    MODE_FUNCTIONAL = gpio.LOW   # normal run mode (flash boot)
    MODE_FLASH = gpio.HIGH       # bootloader/UART flashing mode

    def __init__(self):
        gpio.setmode(gpio.BCM)
        gpio.setwarnings(False)

        # Both pins are outputs we drive
        gpio.setup(self.PIN_SOP, gpio.OUT, initial=self.MODE_FUNCTIONAL)
        gpio.setup(self.PIN_RESET, gpio.OUT, initial=gpio.HIGH)  # idle high (not in reset)

    def set_mode(self, mode):
        """
        Set the SOP/boot-mode pin level. This only takes effect on the
        *next* reset pulse, since the device latches SOP state at reset.

        mode: self.MODE_FUNCTIONAL or self.MODE_FLASH
        """
        gpio.output(self.PIN_SOP, mode)
        time.sleep(0.01)  # small settle time before reset

    def reset_radar(self, hold_time=0.1):
        """
        Pulse NRESET low then high to reset the device in whatever
        mode is currently set on PIN_SOP.
        """
        gpio.output(self.PIN_RESET, gpio.LOW)
        time.sleep(hold_time)
        gpio.output(self.PIN_RESET, gpio.HIGH)
        time.sleep(0.1)  # allow boot ROM to come up before host talks to it

    def set_boot_write_firmware(self):
        """
        Convenience method: switch into flash/bootloader mode and reset
        into it, ready for a firmware write over UART.
        """
        self.set_mode(self.MODE_FLASH)
        self.reset_radar()

    def set_functional_mode(self):
        """
        Convenience method: switch back to normal functional (flash-boot)
        mode and reset into it.
        """
        self.set_mode(self.MODE_FUNCTIONAL)
        self.reset_radar()

    def reset_gpio(self):
        gpio.cleanup()
