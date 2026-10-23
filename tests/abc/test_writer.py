from autoswf.abc.code import Code, u30
from autoswf.abc.reader import ABC
from autoswf.abc.writer import PACKAGE, PROTECTED, AbcBuilder


def test_u30_encoding():
    assert u30(0) == b"\x00" and u30(127) == b"\x7f" and u30(128) == b"\x80\x01" and u30(300) == b"\xac\x02"


def test_one_empty_class_roundtrip():
    b = AbcBuilder()
    name = b.qname(PACKAGE, "", "Demo"); sup = b.qname(PACKAGE, "flash.display", "MovieClip")
    body = Code().getlocal0().pushscope().returnvoid().bytes()
    cinit = b.method(1, 1, 9, 10, body)
    iinit = b.method(1, 1, 10, 11, Code().getlocal0().pushscope().getlocal0().constructsuper(0).returnvoid().bytes())
    ci = b.add_class(name, sup, b.namespace(PROTECTED, "Demo"), iinit, cinit, [])
    b.add_script(b.method(2, 1, 1, 9, body), name, ci)
    a = ABC(b.serialize())
    assert (a.major, a.minor) == (46, 16)
    inst = a.instances[0]
    assert a.mname(inst["name"]) == "Demo" and a.mname(inst["super"]) == "flash.display.MovieClip"
    assert inst["flags"] == 0x08 and a.ns[inst["protected_ns"]] == (PROTECTED, a.strings.index("Demo"))
    assert a.body_info[iinit] == (1, 1, 10, 11)


def test_methods_declare_their_parameters_and_optional_defaults():
    """A real AVM2 rejects a call with more arguments than the method declares (Error #1063): event handlers take
    the event, and `restart:Boolean = false` needs its default."""
    b = AbcBuilder()
    body = Code().returnvoid().bytes()
    plain = b.method(1, 1, 1, 2, body)
    handler = b.method(1, 2, 1, 2, body, params=1)
    two = b.method(1, 3, 1, 2, body, params=2, optional=((0x0A, 0),))
    name = b.qname(PACKAGE, "", "Demo")
    ci = b.add_class(name, b.qname(PACKAGE, "", "Object"), b.namespace(PROTECTED, "Demo"), plain, plain, [])
    b.add_script(plain, name, ci)
    a = ABC(b.serialize())
    assert len(a.method_info[plain]["params"]) == 0 and "optional" not in a.method_info[plain]
    assert len(a.method_info[handler]["params"]) == 1
    assert len(a.method_info[two]["params"]) == 2 and a.method_info[two]["optional"] == [(0x0A, 0)]
