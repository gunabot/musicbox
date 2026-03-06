from __future__ import annotations

import time


RST_PIN = 17
DC_PIN = 25
CS_PIN = 8
BUSY_PIN = 24


class RaspberryPiInterface:
    """Minimal Raspberry Pi GPIO/SPI bridge for the 3.7" Waveshare panel.

    This intentionally omits the stock Waveshare GPIO18 power-toggle path.
    GPIO18 is already used by the WM8960 I2S audio bus in this project.
    """

    def __init__(self) -> None:
        self._gpiozero = None
        self._spidev = None
        self._spi = None
        self._rst = None
        self._dc = None
        self._busy = None

    def _ensure_gpio(self) -> None:
        if self._gpiozero is not None and self._spidev is not None:
            return

        import gpiozero
        import spidev

        self._gpiozero = gpiozero
        self._spidev = spidev
        self._rst = gpiozero.LED(RST_PIN)
        self._dc = gpiozero.LED(DC_PIN)
        self._busy = gpiozero.Button(BUSY_PIN, pull_up=False)

    def digital_write(self, pin: int, value: int) -> None:
        self._ensure_gpio()
        if pin == RST_PIN:
            self._rst.on() if value else self._rst.off()
            return
        if pin == DC_PIN:
            self._dc.on() if value else self._dc.off()
            return
        if pin == CS_PIN:
            return
        raise ValueError(f"unsupported output pin: {pin}")

    def digital_read(self, pin: int) -> int:
        self._ensure_gpio()
        if pin == BUSY_PIN:
            return int(self._busy.value)
        raise ValueError(f"unsupported input pin: {pin}")

    @staticmethod
    def delay_ms(delaytime: int) -> None:
        time.sleep(delaytime / 1000.0)

    def spi_writebyte(self, data: list[int]) -> None:
        if self._spi is None:
            raise RuntimeError("SPI not initialized")
        self._spi.writebytes(data)

    def spi_writebyte2(self, data: list[int]) -> None:
        if self._spi is None:
            raise RuntimeError("SPI not initialized")
        self._spi.writebytes2(data)

    def module_init(self) -> int:
        self._ensure_gpio()
        if self._spi is None:
            self._spi = self._spidev.SpiDev()
            self._spi.open(0, 0)
        self._spi.max_speed_hz = 4_000_000
        self._spi.mode = 0b00
        return 0

    def module_exit(self) -> None:
        if self._spi is not None:
            self._spi.close()
            self._spi = None
        if self._rst is not None:
            self._rst.off()
        if self._dc is not None:
            self._dc.off()


_EPD = RaspberryPiInterface()


def digital_write(pin: int, value: int) -> None:
    _EPD.digital_write(pin, value)


def digital_read(pin: int) -> int:
    return _EPD.digital_read(pin)


def delay_ms(delaytime: int) -> None:
    _EPD.delay_ms(delaytime)


def spi_writebyte(data: list[int]) -> None:
    _EPD.spi_writebyte(data)


def spi_writebyte2(data: list[int]) -> None:
    _EPD.spi_writebyte2(data)


def module_init() -> int:
    return _EPD.module_init()


def module_exit() -> None:
    _EPD.module_exit()
