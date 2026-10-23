"""ABC (AVM2 bytecode) builder: deduplicating constant pool and serializer."""
import struct
from dataclasses import dataclass

from autoswf.abc.code import u30

PRIVATE = 0x05
NAMESPACE = 0x08
PACKAGE = 0x16
PACKAGE_INTERNAL = 0x17
PROTECTED = 0x18
STATIC_PROTECTED = 0x1A
QNAME = 0x07
MULTINAME = 0x09
MULTINAME_L = 0x1B
CLASS_PROTECTED_NS = 0x08


@dataclass(frozen=True)
class MethodTrait:
    name_mn: int
    method: int


@dataclass(frozen=True)
class SlotTrait:
    name_mn: int
    slot_id: int
    type_mn: int
    value: int = 0                      # a string constant's index as the default value (0: none)


NEED_ACTIVATION = 0x02
HAS_OPTIONAL = 0x08


class AbcBuilder:
    def __init__(self):
        self._strings: dict[str, int] = {}
        self._namespaces: dict[tuple[int, int], int] = {}
        self._ns_sets: dict[tuple[int, ...], int] = {}
        self._multinames: dict[tuple, int] = {}
        self._methods: list[tuple] = []
        self._classes: list[tuple] = []
        self._scripts: list[tuple[int, int, int]] = []

    @staticmethod
    def _intern(table: dict, key) -> int:
        if key not in table:
            table[key] = len(table) + 1      # index 0 is implicit in every pool
        return table[key]

    def string(self, s: str) -> int:
        return self._intern(self._strings, s)

    def namespace(self, kind: int, name: str) -> int:
        return self._intern(self._namespaces, (kind, self.string(name)))

    def qname(self, ns_kind: int, ns_name: str, name: str) -> int:
        ns = self.namespace(ns_kind, ns_name)
        return self._intern(self._multinames, (QNAME, ns, self.string(name)))

    def multiname(self, name: str, namespaces: list[tuple[int, str]]) -> int:
        """Runtime-resolved name over a set of (kind, name) namespaces, as Flash emits for untyped calls."""
        ns_set = tuple(dict.fromkeys(self.namespace(k, n) for k, n in namespaces))
        set_index = self._intern(self._ns_sets, ns_set)
        return self._intern(self._multinames, (MULTINAME, self.string(name), set_index))

    def multiname_late(self, namespaces: list[tuple[int, str]]) -> int:
        """A name taken from the stack (obj[key]) over a set of (kind, name) namespaces."""
        ns_set = tuple(dict.fromkeys(self.namespace(k, n) for k, n in namespaces))
        return self._intern(self._multinames, (MULTINAME_L, self._intern(self._ns_sets, ns_set), None))

    def method(self, max_stack: int, local_count: int, init_scope_depth: int, max_scope_depth: int,
               code: bytes, *, flags: int = 0, exceptions: tuple = (), traits: tuple = (), params: int = 0,
               optional: tuple = ()) -> int:
        """`exceptions`: (from, to, target, type multiname, variable multiname) code offsets; `traits`: SlotTraits
        of the method body (its activation object); `params`: how many (untyped) arguments it takes, the last ones
        `optional` with these (constant kind, index) defaults."""
        self._methods.append((max_stack, local_count, init_scope_depth, max_scope_depth, code, flags,
                              tuple(exceptions), tuple(traits), params, tuple(optional)))
        return len(self._methods) - 1

    def add_class(self, name_mn: int, super_mn: int, protected_ns: int, iinit: int, cinit: int,
                  instance_traits: list[MethodTrait | SlotTrait],
                  static_traits: list[MethodTrait | SlotTrait] = ()) -> int:
        self._classes.append((name_mn, super_mn, protected_ns, iinit, cinit, list(instance_traits),
                              list(static_traits)))
        return len(self._classes) - 1

    @staticmethod
    def _traits(traits) -> bytes:
        out = bytearray(u30(len(traits)))
        for t in traits:
            if isinstance(t, SlotTrait):
                out += u30(t.name_mn) + bytes([0]) + u30(t.slot_id) + u30(t.type_mn) + u30(t.value)
                out += bytes([0x01]) if t.value else b""             # Utf8 constant
            else:
                out += u30(t.name_mn) + bytes([1]) + u30(0) + u30(t.method)
        return bytes(out)

    def add_script(self, init_method: int, class_name_mn: int, class_index: int) -> None:
        self._scripts.append((init_method, class_name_mn, class_index))

    def serialize(self) -> bytes:
        out = bytearray(struct.pack("<HH", 16, 46))
        out += u30(0) + u30(0) + u30(0)                       # int, uint, double pools
        out += u30(len(self._strings) + 1)
        for s in self._strings:
            data = s.encode("utf-8")
            out += u30(len(data)) + data
        out += u30(len(self._namespaces) + 1)
        for kind, name in self._namespaces:
            out += bytes([kind]) + u30(name)
        out += u30(len(self._ns_sets) + 1)
        for ns_set in self._ns_sets:
            out += u30(len(ns_set)) + b"".join(u30(n) for n in ns_set)
        out += u30(len(self._multinames) + 1)
        for kind, a, b in self._multinames:
            # QName: ns, name / Multiname: name, ns_set / MultinameL: ns_set
            out += bytes([kind]) + u30(a) + (u30(b) if b is not None else b"")
        out += u30(len(self._methods))
        for method in self._methods:
            flags, params, optional = method[5], method[8], method[9]
            # params of type *, return *, no name, flags (+ HAS_OPTIONAL and the defaults)
            out += u30(params) + u30(0) + u30(0) * params + u30(0) + bytes([flags | (HAS_OPTIONAL if optional else 0)])
            if optional:
                out += u30(len(optional)) + b"".join(u30(index) + bytes([kind]) for kind, index in optional)
        out += u30(0)                                          # metadata
        out += u30(len(self._classes))
        for name_mn, super_mn, protected_ns, iinit, _cinit, traits, _static in self._classes:
            out += u30(name_mn) + u30(super_mn) + bytes([CLASS_PROTECTED_NS]) + u30(protected_ns)
            out += u30(0) + u30(iinit) + self._traits(traits)
        for *_rest, cinit, _traits, static in self._classes:
            out += u30(cinit) + self._traits(static)
        out += u30(len(self._scripts))
        for init, class_mn, class_index in self._scripts:
            out += u30(init) + u30(1) + u30(class_mn) + bytes([4]) + u30(1) + u30(class_index)
        out += u30(len(self._methods))
        for index, (max_stack, locals_, init_scope, max_scope, code, _, exceptions, traits, *_) in enumerate(
                self._methods):
            out += u30(index) + u30(max_stack) + u30(locals_) + u30(init_scope) + u30(max_scope)
            out += u30(len(code)) + code + u30(len(exceptions))
            for entry in exceptions:
                out += b"".join(u30(v) for v in entry)
            out += u30(len(traits))
            for t in traits:
                out += u30(t.name_mn) + bytes([0]) + u30(t.slot_id) + u30(t.type_mn) + u30(0)
        return bytes(out)
