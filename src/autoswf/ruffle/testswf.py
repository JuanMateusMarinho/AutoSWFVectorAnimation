"""The SWF that "Open in Ruffle" opens (spec §5.2): the compiled test stage, the armor as AutoSWF holds it and the
stage's settings, both embedded as binary data that the stage's ByteArray classes read."""
import json
import struct

from autoswf.swf.bits import BitWriter, write_string
from autoswf.swf.movie import TAG_DO_ABC, TAG_END, TAG_SHOW_FRAME, TAG_SYMBOL_CLASS, swf_file
from autoswf.swf.reader import decompress, iter_tags
from autoswf.swf.sprite_encoder import tag

TAG_BINARY_DATA = 87
STAGE_CLASS, ARMOR_CLASS, SETTINGS_CLASS = "AutoSWFStage", "AutoSWFArmorBytes", "AutoSWFStageSettings"
DUMMY_CLASS = "AutoSWFDummyBytes"
ARMOR_ID, SETTINGS_ID, DUMMY_ID = 1, 2, 3


def build_test_swf(armor: bytes, settings: dict, *, abc: bytes | None = None, dummy: bytes | None = None,
                   width: int = 960, height: int = 600, fps: float = 24.0) -> bytes:
    """`abc` defaults to the shipped stage (stagecode.stage_abc); `dummy` is AQW's Training Dummy file, when the user's
    cache has it (the stage draws a stand-in otherwise)."""
    if abc is None:
        from autoswf.ruffle.stagecode import stage_abc
        abc = stage_abc()
    binaries = [(ARMOR_ID, ARMOR_CLASS, armor), (SETTINGS_ID, SETTINGS_CLASS, json.dumps(settings).encode("utf-8"))]
    if dummy is not None:
        binaries.append((DUMMY_ID, DUMMY_CLASS, dummy))
    body = bytearray(tag(TAG_DO_ABC, struct.pack("<I", 1) + b"\0" + abc))
    for char_id, _, data in binaries:
        body += tag(TAG_BINARY_DATA, struct.pack("<HI", char_id, 0) + data)
    sc = BitWriter()
    sc.u16(len(binaries) + 1)
    for char_id, name in [(char_id, name) for char_id, name, _ in binaries] + [(0, STAGE_CLASS)]:
        sc.u16(char_id)
        write_string(sc, name)
    body += tag(TAG_SYMBOL_CLASS, sc.getvalue())
    body += tag(TAG_SHOW_FRAME) + tag(TAG_END)
    return swf_file(bytes(body), width=width, height=height, fps=fps)


def _binaries(data: bytes) -> dict[int, bytes]:
    _, _, _, body = decompress(data)
    pos = (5 + 4 * (body[0] >> 3) + 7) // 8 + 4          # after the stage rect, frame rate and frame count
    found = {}
    for code, start, length in iter_tags(body, pos, len(body)):
        if code == TAG_BINARY_DATA:
            found[struct.unpack_from("<H", body, start)[0]] = bytes(body[start + 6:start + length])
    return found


def read_test_swf(data: bytes) -> tuple[dict, bytes]:
    """(settings, armor) back from a test SWF."""
    found = _binaries(data)
    return json.loads(found[SETTINGS_ID].decode("utf-8")), found[ARMOR_ID]


def embedded_dummy(data: bytes) -> bytes | None:
    return _binaries(data).get(DUMMY_ID)
