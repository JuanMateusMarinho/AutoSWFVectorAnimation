from autoswf.abc.disasm import disassemble


class FakeABC:   # only what disassemble needs for these opcodes
    strings = ["", "Skin"]

    def mname(self, i):
        return "*"


def test_disassemble_drops_debug_and_formats_operands():
    code = bytes([0xD0, 0x30, 0xF0, 0x05, 0x2C, 0x01, 0x10, 0x00, 0x00, 0x00, 0x47])
    ops = [(i.op, i.args) for i in disassemble(FakeABC(), code)]
    assert ops == [("getlocal0", ()), ("pushscope", ()), ("pushstring", ("'Skin'",)),
                   ("jump", ("->10",)), ("returnvoid", ())]
