"""Disassemble AS3 methods of a SWF. Usage: python abcdis.py FILE.swf --find REGEX [--owner] [--max N]

--find matches the disassembly text, or the method's owner name with --owner.
"""
import re
import sys

from autoswf.abc.disasm import disassemble, method_owners
from autoswf.abc.reader import ABC
from autoswf.swf.reader import SWF


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rx = re.compile(argv[argv.index("--find") + 1])
    limit = int(argv[argv.index("--max") + 1]) if "--max" in argv else 20
    shown = 0
    for _, block in SWF(argv[0]).abcs:
        abc = ABC(block)
        owners = method_owners(abc)
        for m, code in abc.bodies.items():
            label = owners.get(m, "method#%d" % m)
            lines = ["%5d  %s %s" % (i.offset, i.op, ", ".join(i.args)) for i in disassemble(abc, code)]
            if rx.search(label if "--owner" in argv else "\n".join(lines)):
                print("\n===== %s %s (%d instrs)" % (label, abc.body_info[m], len(lines)))
                print("\n".join(lines))
                shown += 1
                if shown >= limit:
                    return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
