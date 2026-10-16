import struct
import zlib

from autoswf.swf.reader import SWF, decompress

BODY = b"\x00" + b"\x00\x18" + b"\x01\x00" + b"\x40\x00" + b"\x00\x00"   # RECT nbits=0, 24 fps, 1 frame, ShowFrame, End


def fws(body=BODY, version=10):
    return b"FWS" + bytes([version]) + struct.pack("<I", 8 + len(body)) + body


def test_decompress_fws_and_cws_agree():
    cws = b"CWS" + bytes([10]) + struct.pack("<I", 8 + len(BODY)) + zlib.compress(BODY)
    assert decompress(fws()) == ("FWS", 10, 8 + len(BODY), BODY)
    assert decompress(cws) == ("CWS", 10, 8 + len(BODY), BODY)


def test_swf_from_bytes_minimal_movie():
    swf = SWF(fws())
    assert (swf.fps, swf.frames, swf.size) == (24.0, 1, (0.0, 0.0, 0.0, 0.0))
    assert dict(swf.tagcount) == {"ShowFrame": 1, "End": 1}
