#
# The Python Imaging Library.
# $Id$
#
# Windows Cursor support for PIL
#
# notes:
#       uses BmpImagePlugin.py to read the bitmap data.
#
# history:
#       96-05-27 fl     Created
#
# Copyright (c) Secret Labs AB 1997.
# Copyright (c) Fredrik Lundh 1996.
#
# See the README file for information on usage and redistribution.
#
from io import BytesIO

from . import BmpImagePlugin, IcoImagePlugin, Image, ImageFile
from ._binary import i16le as i16
from ._binary import i32le as i32
from ._binary import o8
from ._binary import o16le as o16
from ._binary import o32le as o32

#
# --------------------------------------------------------------------

_MAGIC = b"\0\0\2\0"


def _save(im: Image.Image, fp: BytesIO, filename: str):
    fp.write(_MAGIC)
    bmp = im.encoderinfo.get("bitmap_format", "") == "bmp"
    sizes = im.encoderinfo.get(
        "sizes",
        [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    hotspots = im.encoderinfo.get("hotspots", [(0, 0) for i in range(len(sizes))])
    if len(hotspots) != len(sizes):
        raise ValueError("Number of hotspots must be equal to number of cursor sizes")

    frames = []
    width, height = im.size
    for size in sorted(set(sizes)):
        if size[0] > width or size[1] > height or size[0] > 256 or size[1] > 256:
            continue

        # TODO: invent a more convenient method for proportional scalings
        frame = im.copy()
        frame.thumbnail(size, Image.Resampling.LANCZOS, reducing_gap=None)
        frames.append(frame)

    fp.write(o16(len(frames)))  # idCount(2)
    offset = fp.tell() + len(frames) * 16
    for hotspot, frame in zip(hotspots, frames):
        width, height = frame.size
        # 0 means 256
        fp.write(o8(width if width < 256 else 0))  # bWidth(1)
        fp.write(o8(height if height < 256 else 0))  # bHeight(1)

        bits, colors = BmpImagePlugin.SAVE[frame.mode][1:] if bmp else (32, 0)
        fp.write(o8(colors))  # bColorCount(1)
        fp.write(b"\0")  # bReserved(1)
        fp.write(o16(hotspot[0]))  # x_hotspot(2)
        fp.write(o16(hotspot[1]))  # y_hotspot(2)

        image_io = BytesIO()
        if bmp:
            frame.save(image_io, "dib")

            if bits != 32:
                and_mask = Image.new("1", size)
                ImageFile._save(
                    and_mask, image_io, [("raw", (0, 0) + size, 0, ("1", 0, -1))]
                )
        else:
            frame.save(image_io, "png")
        image_io.seek(0)
        image_bytes = image_io.read()
        if bmp:
            image_bytes = image_bytes[:8] + o32(height * 2) + image_bytes[12:]
        bytes_len = len(image_bytes)
        fp.write(o32(bytes_len))  # dwBytesInRes(4)
        fp.write(o32(offset))  # dwImageOffset(4)
        current = fp.tell()
        fp.seek(offset)
        fp.write(image_bytes)
        offset = offset + bytes_len
        fp.seek(current)


def _accept(prefix):
    return prefix[:4] == _MAGIC


##
# Image plugin for Windows Cursor files.
class CurFile(IcoImagePlugin.IcoFile):
    def __init__(self, buf: BytesIO):
        """
        Parse image from file-like object containing cur file data
        """

        # check if CUR
        s = buf.read(6)
        if not _accept(s):
            raise SyntaxError("not a CUR file")

        self.buf = buf
        self.entry = []

        # Number of items in file
        self.nb_items = i16(s, 4)

        # Get headers for each item
        for _ in range(self.nb_items):
            s = buf.read(16)

            icon_header = {
                "width": s[0],
                "height": s[1],
                "nb_color": s[2],  # No. of colors in image (0 if >=8bpp)
                "reserved": s[3],
                "x_hotspot": i16(s, 4),
                "y_hotspot": i16(s, 6),
                "size": i32(s, 8),
                "offset": i32(s, 12),
            }

            # See Wikipedia
            for j in ("width", "height"):
                if not icon_header[j]:
                    icon_header[j] = 256

            icon_header["dim"] = (icon_header["width"], icon_header["height"])
            icon_header["square"] = icon_header["width"] * icon_header["height"]

            # TODO: This needs further investigation. Cursor files do not really
            # specify their bpp like ICO's as those bits are used for the y_hotspot.
            # For now, bpp is calculated by subtracting the AND mask (equal to number
            # of pixels * 1bpp) and dividing by the number of pixels.
            # This seems to work well so far.
            BITMAP_INFO_HEADER_SIZE = 40
            bpp_without_and = (
                (icon_header["size"] - BITMAP_INFO_HEADER_SIZE) * 8
            ) // icon_header["square"]

            if bpp_without_and != 32:
                icon_header["bpp"] = (
                    (icon_header["size"] - BITMAP_INFO_HEADER_SIZE) * 8
                    - icon_header["square"]
                ) // icon_header["square"]
            else:
                icon_header["bpp"] = bpp_without_and

            self.entry.append(icon_header)

        self.entry = sorted(self.entry, key=lambda x: x["square"])
        self.entry.reverse()

    def sizes(self):
        return [(h["width"], h["height"]) for h in self.entry]

    def hotspots(self):
        return [(h["x_hotspot"], h["y_hotspot"]) for h in self.entry]


class CurImageFile(IcoImagePlugin.IcoImageFile):

    format = "CUR"
    format_description = "Windows Cursor"

    def _open(self):
        self.ico = CurFile(self.fp)
        self.info["sizes"] = self.ico.sizes()
        self.info["hotspots"] = self.ico.hotspots()
        if len(self.ico.entry) > 0:
            self.size = self.ico.entry[0]["dim"]
        else:
            raise TypeError("No cursors were found")
        self.load()


#
# --------------------------------------------------------------------

Image.register_open(CurImageFile.format, CurImageFile, _accept)
Image.register_save(CurImageFile.format, _save)
Image.register_extension(CurImageFile.format, ".cur")
