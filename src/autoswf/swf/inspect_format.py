"""Human-readable reports of a parsed SWF (used by `autoswf inspect`)."""
import collections

from autoswf.abc.reader import ABC

TRAIT_KINDS = {0: "var", 1: "fn", 2: "get", 3: "set", 4: "class", 5: "func", 6: "const"}


def fmt_place(o, swf):
    c = swf.chars.get(o.get("char"), {})
    parts = ["d%d" % o["depth"]]
    if "char" in o:
        k = c.get("kind", "?")
        cls = swf.symbols.get(o["char"])
        parts.append("%s#%d%s" % (k, o["char"], ("(" + cls + ")") if cls else ""))
    if o.get("move"):
        parts.append("move")
    if "name" in o:
        parts.append('name="%s"' % o["name"])
    if "matrix" in o:
        sx, r0, r1, sy, tx, ty = o["matrix"]
        parts.append("at(%.1f,%.1f)" % (tx, ty) + ("" if (sx, r0, r1, sy) == (1, 0, 0, 1) else " m(%.2f,%.2f,%.2f,%.2f)" % (sx, r0, r1, sy)))
    if "cx" in o:
        parts.append("cx%s" % (o["cx"],))
    for k in ("ratio", "clipdepth", "blend", "filters", "class", "visible", "cacheAsBitmap"):
        if k in o:
            parts.append("%s=%s" % (k, o[k]))
    return " ".join(parts)


def dump_sprite(swf, cid, indent, maxdepth, seen, out, allframes=False):
    c = swf.chars.get(cid)
    if not c or c["kind"] != "sprite":
        return
    tl = c["timeline"]
    pad = "  " * indent
    lab = (" labels=%s" % tl["labels"]) if tl["labels"] else ""
    out.append("%ssprite#%d frames=%d%s" % (pad, cid, c["nframes"], lab))
    if indent >= maxdepth:
        return
    frames = tl["frames"] if allframes else tl["frames"][:1]
    for fi, fr in enumerate(frames):
        if allframes and len(tl["frames"]) > 1:
            out.append("%s  [frame %d]" % (pad, fi + 1))
        for o in fr:
            if o["_t"] == "place":
                out.append("%s  - %s" % (pad, fmt_place(o, swf)))
                ch = o.get("char")
                if ch is not None and ch not in seen and swf.chars.get(ch, {}).get("kind") == "sprite":
                    seen.add(ch)
                    dump_sprite(swf, ch, indent + 2, maxdepth, seen, out)
            else:
                out.append("%s  - remove d%d" % (pad, o["depth"]))
    if not allframes and len(tl["frames"]) > 1:
        names = collections.OrderedDict()
        for fr in tl["frames"][1:]:
            for o in fr:
                if o["_t"] == "place" and "name" in o:
                    names[o["name"]] = 1
        if names:
            out.append("%s  (later frames add names: %s)" % (pad, ", ".join(names)))


def format_report(swf, tree=False, abc=False, strings=False, shapes=False, maxdepth=6, allframes=False, title=""):
    out = []
    out.append("== %s  sig=%s ver=%d size=%sx%s fps=%.2f frames=%d fileattrs=%s" % (
        title, swf.sig, swf.ver, swf.size[1] - swf.size[0], swf.size[3] - swf.size[2], swf.fps, swf.frames,
        None if swf.attrs is None else bin(swf.attrs)))
    out.append("tags: %s" % dict(swf.tagcount))
    out.append("characters: %s" % dict(collections.Counter(c["kind"] for c in swf.chars.values())))
    out.append("SymbolClass:")
    for cid, name in sorted(swf.symbols.items(), key=lambda x: x[1]):
        c = swf.chars.get(cid, {})
        extra = ""
        if c.get("kind") == "sprite":
            extra = " frames=%d labels=%s" % (c["nframes"], c["timeline"]["labels"] or "")
        out.append("  %-40s -> %s#%d%s" % (name, c.get("kind", "?"), cid, extra))
    if swf.exports:
        out.append("ExportAssets: %s" % swf.exports)
    if swf.root["labels"]:
        out.append("root labels: %s" % swf.root["labels"])
    if tree:
        seen = set()
        for cid, name in sorted(swf.symbols.items(), key=lambda x: x[1]):
            if swf.chars.get(cid, {}).get("kind") == "sprite":
                out.append("")
                out.append("### %s" % name)
                dump_sprite(swf, cid, 1, maxdepth, seen, out, allframes=allframes)
        out.append("")
        out.append("### root timeline (frame 1)")
        for o in swf.root["frames"][0] if swf.root["frames"] else []:
            if o["_t"] == "place":
                out.append("  - " + fmt_place(o, swf))
    if shapes:
        cols = collections.Counter()
        for c in swf.chars.values():
            if c["kind"].startswith("shape") and "fills" in c:
                for f in c["fills"]:
                    cols[f[0] if f[0] != "solid" else f[1]] += 1
                for ln in c["lines"]:
                    cols["LINE w=%.2f %s" % (ln[1], ln[2] if isinstance(ln[2], str) else ln[2][0])] += 1
        out.append("")
        out.append("fill/line usage (top 60):")
        for k, v in cols.most_common(60):
            out.append("  %5d  %s" % (v, k))
        tot = [c for c in swf.chars.values() if c["kind"].startswith("shape") and "edges" in c]
        out.append("shapes=%d edges=%d curves=%d" % (len(tot), sum(c["edges"] for c in tot), sum(c["curves"] for c in tot)))
    if abc or strings:
        for name, data in swf.abcs:
            try:
                parsed = ABC(data)
            except Exception as e:  # report and keep going with other blocks
                out.append("ABC %s parse error: %s" % (name, e))
                continue
            out.append("")
            out.append("ABC block %r: v%d.%d classes=%d methods=%d strings=%d" % (
                name, parsed.major, parsed.minor, len(parsed.instances), len(parsed.methods), len(parsed.strings)))
            if abc:
                for inst in parsed.instances:
                    out.append("  class %s extends %s" % (parsed.mname(inst["name"]), parsed.mname(inst["super"])))
                    for t in inst["traits"]:
                        out.append("      %s %s%s" % (TRAIT_KINDS[t["kind"]], parsed.mname(t["name"]),
                                                    (":" + parsed.mname(t["type"])) if "type" in t else ""))
            if strings:
                out.append("  strings: " + " | ".join(s for s in parsed.strings if s))
    return "\n".join(out)
