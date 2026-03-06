from __future__ import annotations

import logging

from . import epdconfig


EPD_WIDTH = 280
EPD_HEIGHT = 480

GRAY1 = 0xFF
GRAY2 = 0xC0
GRAY3 = 0x80
GRAY4 = 0x00

logger = logging.getLogger(__name__)


class EPD:
    """Minimal 3.7" Waveshare e-paper driver derived from the official code."""

    lut_4Gray_GC = [
        0x2A, 0x06, 0x15, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x28, 0x06, 0x14, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x20, 0x06, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x14, 0x06, 0x28, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x02, 0x02, 0x0A, 0x00, 0x00, 0x00, 0x08, 0x08, 0x02,
        0x00, 0x02, 0x02, 0x0A, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x22, 0x22, 0x22, 0x22, 0x22,
    ]

    def __init__(self) -> None:
        self.reset_pin = epdconfig.RST_PIN
        self.dc_pin = epdconfig.DC_PIN
        self.busy_pin = epdconfig.BUSY_PIN
        self.cs_pin = epdconfig.CS_PIN
        self.width = EPD_WIDTH
        self.height = EPD_HEIGHT
        self.GRAY1 = GRAY1
        self.GRAY2 = GRAY2
        self.GRAY3 = GRAY3
        self.GRAY4 = GRAY4

    def reset(self) -> None:
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(200)
        epdconfig.digital_write(self.reset_pin, 0)
        epdconfig.delay_ms(5)
        epdconfig.digital_write(self.reset_pin, 1)
        epdconfig.delay_ms(200)

    def send_command(self, command: int) -> None:
        epdconfig.digital_write(self.dc_pin, 0)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([command])
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data(self, data: int) -> None:
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte([data])
        epdconfig.digital_write(self.cs_pin, 1)

    def send_data2(self, data: list[int]) -> None:
        epdconfig.digital_write(self.dc_pin, 1)
        epdconfig.digital_write(self.cs_pin, 0)
        epdconfig.spi_writebyte2(data)
        epdconfig.digital_write(self.cs_pin, 1)

    def ReadBusy(self) -> None:
        logger.debug("e-paper busy")
        while epdconfig.digital_read(self.busy_pin) == 1:
            epdconfig.delay_ms(10)
        logger.debug("e-paper busy release")

    def init(self, mode: int) -> int:
        if epdconfig.module_init() != 0:
            return -1
        self.reset()

        self.send_command(0x12)
        epdconfig.delay_ms(300)

        self.send_command(0x46)
        self.send_data(0xF7)
        self.ReadBusy()
        self.send_command(0x47)
        self.send_data(0xF7)
        self.ReadBusy()

        self.send_command(0x01)
        self.send_data(0xDF)
        self.send_data(0x01)
        self.send_data(0x00)

        self.send_command(0x03)
        self.send_data(0x00)

        self.send_command(0x04)
        self.send_data(0x41)
        self.send_data(0xA8)
        self.send_data(0x32)

        self.send_command(0x11)
        self.send_data(0x03)

        self.send_command(0x3C)
        self.send_data(0x03)

        self.send_command(0x0C)
        self.send_data(0xAE)
        self.send_data(0xC7)
        self.send_data(0xC3)
        self.send_data(0xC0)
        self.send_data(0xC0)

        self.send_command(0x18)
        self.send_data(0x80)

        self.send_command(0x2C)
        self.send_data(0x44)

        self.send_command(0x37)
        if mode == 0:
            for value in [0x00] * 10:
                self.send_data(value)
        elif mode == 1:
            for value in [0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0x4F, 0xFF, 0xFF, 0xFF, 0xFF]:
                self.send_data(value)
        else:
            raise ValueError(f"unsupported mode: {mode}")

        self.send_command(0x44)
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_data(0x17)
        self.send_data(0x01)

        self.send_command(0x45)
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_data(0xDF)
        self.send_data(0x01)

        self.send_command(0x22)
        self.send_data(0xCF)
        return 0

    def load_lut(self, lut: list[int]) -> None:
        self.send_command(0x32)
        self.send_data2(lut)

    def getbuffer_4Gray(self, image) -> list[int]:
        buf = [0xFF] * (int(self.width / 4) * self.height)
        image_monocolor = image.convert("L")
        imwidth, imheight = image_monocolor.size
        pixels = image_monocolor.load()
        index = 0
        if imwidth == self.width and imheight == self.height:
            logger.debug("vertical")
            for y in range(imheight):
                for x in range(imwidth):
                    if pixels[x, y] == 0xC0:
                        pixels[x, y] = 0x80
                    elif pixels[x, y] == 0x80:
                        pixels[x, y] = 0x40
                    index += 1
                    if index % 4 == 0:
                        buf[int((x + (y * self.width)) / 4)] = (
                            (pixels[x - 3, y] & 0xC0)
                            | ((pixels[x - 2, y] & 0xC0) >> 2)
                            | ((pixels[x - 1, y] & 0xC0) >> 4)
                            | ((pixels[x, y] & 0xC0) >> 6)
                        )
            return buf

        if imwidth == self.height and imheight == self.width:
            logger.debug("horizontal")
            for x in range(imwidth):
                for y in range(imheight):
                    newx = y
                    newy = imwidth - x - 1
                    if pixels[x, y] == 0xC0:
                        pixels[x, y] = 0x80
                    elif pixels[x, y] == 0x80:
                        pixels[x, y] = 0x40
                    index += 1
                    if index % 4 == 0:
                        buf[int((newx + (newy * self.width)) / 4)] = (
                            (pixels[x, y - 3] & 0xC0)
                            | ((pixels[x, y - 2] & 0xC0) >> 2)
                            | ((pixels[x, y - 1] & 0xC0) >> 4)
                            | ((pixels[x, y] & 0xC0) >> 6)
                        )
            return buf

        raise ValueError(f"unexpected image size: {(imwidth, imheight)}")

    def display_4Gray(self, image: list[int] | None) -> None:
        if image is None:
            return

        self.send_command(0x4E)
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_command(0x4F)
        self.send_data(0x00)
        self.send_data(0x00)

        linewidth = int(self.width / 8) if self.width % 8 == 0 else int(self.width / 8) + 1
        buf = [0x00] * self.height * linewidth

        self.send_command(0x24)
        for i in range(int(self.height * (self.width / 8))):
            temp3 = 0
            for j in range(2):
                temp1 = image[i * 2 + j]
                for k in range(2):
                    temp2 = temp1 & 0xC0
                    if temp2 == 0xC0:
                        temp3 |= 0x01
                    elif temp2 == 0x00:
                        temp3 |= 0x00
                    elif temp2 == 0x80:
                        temp3 |= 0x00
                    else:
                        temp3 |= 0x01
                    temp3 <<= 1
                    temp1 <<= 2
                    temp2 = temp1 & 0xC0
                    if temp2 == 0xC0:
                        temp3 |= 0x01
                    elif temp2 == 0x00:
                        temp3 |= 0x00
                    elif temp2 == 0x80:
                        temp3 |= 0x00
                    else:
                        temp3 |= 0x01
                    if j != 1 or k != 1:
                        temp3 <<= 1
                    temp1 <<= 2
            buf[i] = temp3
        self.send_data2(buf)

        self.send_command(0x4E)
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_command(0x4F)
        self.send_data(0x00)
        self.send_data(0x00)

        self.send_command(0x26)
        for i in range(int(self.height * (self.width / 8))):
            temp3 = 0
            for j in range(2):
                temp1 = image[i * 2 + j]
                for k in range(2):
                    temp2 = temp1 & 0xC0
                    if temp2 == 0xC0:
                        temp3 |= 0x01
                    elif temp2 == 0x00:
                        temp3 |= 0x00
                    elif temp2 == 0x80:
                        temp3 |= 0x01
                    else:
                        temp3 |= 0x00
                    temp3 <<= 1
                    temp1 <<= 2
                    temp2 = temp1 & 0xC0
                    if temp2 == 0xC0:
                        temp3 |= 0x01
                    elif temp2 == 0x00:
                        temp3 |= 0x00
                    elif temp2 == 0x80:
                        temp3 |= 0x01
                    else:
                        temp3 |= 0x00
                    if j != 1 or k != 1:
                        temp3 <<= 1
                    temp1 <<= 2
            buf[i] = temp3
        self.send_data2(buf)

        self.load_lut(self.lut_4Gray_GC)
        self.send_command(0x22)
        self.send_data(0xC7)
        self.send_command(0x20)
        self.ReadBusy()

    def Clear(self, color: int, mode: int) -> None:
        del color

        self.send_command(0x4E)
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_command(0x4F)
        self.send_data(0x00)
        self.send_data(0x00)

        linewidth = int(self.width / 8) if self.width % 8 == 0 else int(self.width / 8) + 1

        self.send_command(0x24)
        self.send_data2([0xFF] * int(self.height * linewidth))

        if mode == 0:
            self.send_command(0x26)
            self.send_data2([0xFF] * int(self.height * linewidth))
            self.load_lut(self.lut_4Gray_GC)
            self.send_command(0x22)
            self.send_data(0xC7)
        elif mode != 1:
            raise ValueError(f"unsupported mode: {mode}")

        self.send_command(0x20)
        self.ReadBusy()

    def sleep(self) -> None:
        self.send_command(0x10)
        self.send_data(0x03)
        epdconfig.delay_ms(2000)
        epdconfig.module_exit()

