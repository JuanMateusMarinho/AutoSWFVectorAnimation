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
ARMOR_ID, SETTINGS_ID = 1, 2


def build_test_swf(armor: bytes, settings: dict, *, abc: bytes | None = None, width: int = 960, height: int = 600,
                   fps: float = 24.0) -> bytes:
    """`abc` defaults to the shipped stage (stagecode.stage_abc)."""
    if abc is None:
        from autoswf.ruffle.stagecode import stage_abc
        abc = stage_abc()
    body = bytearray(tag(TAG_DO_ABC, struct.pack("<I", 1) + b"\0" + abc))
    for char_id, data in ((ARMOR_ID, armor), (SETTINGS_ID, json.dumps(settings).encode("utf-8"))):
        body += tag(TAG_BINARY_DATA, struct.pack("<HI", char_id, 0) + data)
    sc = BitWriter()
    sc.u16(3)
    for char_id, name in ((ARMOR_ID, ARMOR_CLASS), (SETTINGS_ID, SETTINGS_CLASS), (0, STAGE_CLASS)):
        sc.u16(char_id)
        write_string(sc, name)
    body += tag(TAG_SYMBOL_CLASS, sc.getvalue())
    body += tag(TAG_SHOW_FRAME) + tag(TAG_END)
    return swf_file(bytes(body), width=width, height=height, fps=fps)


def read_test_swf(data: bytes) -> tuple[dict, bytes]:
    """(settings, armor) back from a test SWF."""
    _, _, _, body = decompress(data)
    pos = (5 + 4 * (body[0] >> 3) + 7) // 8 + 4          # after the stage rect, frame rate and frame count
    found = {}
    for code, start, length in iter_tags(body, pos, len(body)):
        if code == TAG_BINARY_DATA:
            found[struct.unpack_from("<H", body, start)[0]] = bytes(body[start + 6:start + length])
    return json.loads(found[SETTINGS_ID].decode("utf-8")), found[ARMOR_ID]
