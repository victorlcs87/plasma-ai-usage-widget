#!/usr/bin/env python3
"""Catálogos de tradução do Plasmoid (só stdlib, determinístico, sem rede).

  python3 tools/i18n.py extract            # plasmoid/**/*.qml|js -> po/<domínio>.pot
  python3 tools/i18n.py update             # sincroniza po/*.po com o .pot (en.po é preenchido sozinho)
  python3 tools/i18n.py compile OUT_DIR    # po/*.po -> OUT_DIR/<lang>/LC_MESSAGES/<domínio>.mo

Chamadas reconhecidas (primeiros argumentos têm de ser literais de string, sem variáveis):
  tr(msg) trc(ctx, msg) trp(one, many, n)  i18n(msg) i18nc(ctx, msg) i18np(one, many, n)
Texto vindo de dados (nome de conta, mensagem do coletor) entra só como argumento %N, nunca como msgid.
"""
from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLASMOID = ROOT / "plasmoid"
PO_DIR = ROOT / "po"
# nome da função -> posições dos argumentos literais: (ctx, msgid, plural)
KEYWORDS = {
    "tr": (None, 0, None), "i18n": (None, 0, None),
    "trc": (0, 1, None), "i18nc": (0, 1, None),
    "trp": (None, 0, 1), "i18np": (None, 0, 1),
}
CALL = re.compile(r"(?<![\w$])(?:[\w$]+\.)*(tr|trc|trp|i18n|i18nc|i18np)\s*\(")
STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')
ESC = {"n": "\n", "t": "\t", '"': '"', "'": "'", "\\": "\\"}


def domain() -> str:
    meta = json.loads((PLASMOID / "metadata.json").read_text(encoding="utf-8"))
    return "plasma_applet_" + meta["KPlugin"]["Id"]


def js_unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: ESC.get(m.group(1), m.group(1)), s)


def strip_comments(src: str) -> str:
    """Troca comentários por espaços (mantém offsets/linhas); respeita strings."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            m = STRING.match(src, i)
            j = m.end() if m else i + 1
            out.append(src[i:j]); i = j
        elif src.startswith("//", i):
            j = src.find("\n", i); j = n if j < 0 else j
            out.append(" " * (j - i)); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i); j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j])); i = j
        else:
            out.append(c); i += 1
    return "".join(out)


def parse_args(src: str, pos: int):
    """Argumentos de topo da chamada que abre em src[pos-1]=='('; cada um é lista de pedaços."""
    args, cur, depth, i = [], "", 1, pos
    while i < len(src) and depth:
        c = src[i]
        if c in "\"'":
            m = STRING.match(src, i)
            if not m:
                break
            cur += m.group(0); i = m.end(); continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                break
        if c == "," and depth == 1:
            args.append(cur); cur = ""
        else:
            cur += c
        i += 1
    args.append(cur)
    return [a.strip() for a in args]


def literal(arg: str):
    """'"a" + "b"' -> 'ab'; None se não for só literais concatenados."""
    parts = re.split(r'(?<=["\'])\s*\+\s*(?=["\'])', arg)
    out = ""
    for p in parts:
        m = STRING.fullmatch(p.strip())
        if not m:
            return None
        out += js_unescape(m.group(1) if m.group(1) is not None else m.group(2))
    return out


def source_files():
    return sorted(p for p in (PLASMOID / "contents").rglob("*") if p.suffix in (".qml", ".js") and p.name != "I18n.js")


def extract():
    """-> (entradas {(ctx,msgid,plural): [refs]}, erros)"""
    entries, errors = {}, []
    for path in source_files():
        raw = path.read_text(encoding="utf-8")
        src = strip_comments(raw)
        rel = path.relative_to(PLASMOID).as_posix()
        for m in CALL.finditer(src):
            if re.search(r"function\s+$", src[max(0, m.start() - 12):m.start()]):
                continue  # declaração, não chamada
            line = src.count("\n", 0, m.start()) + 1
            ci, mi, pi = KEYWORDS[m.group(1)]
            args = parse_args(src, m.end())
            vals = [literal(args[k]) if k is not None and k < len(args) else None for k in (ci, mi, pi)]
            if (ci is not None and vals[0] is None) or vals[1] is None or (pi is not None and vals[2] is None):
                errors.append(f"{rel}:{line}: {m.group(1)}() com argumento não literal")
                continue
            entries.setdefault((vals[0], vals[1], vals[2]), []).append(f"{rel}:{line}")
    return entries, errors


# ---- strings visíveis fora de i18n ----

VISIBLE = re.compile(r"(?<![\w.])((?:Accessible\.(?:name|description))|accessibleName|(?:[\w]+\.)?ToolTip\.text|"
                     r"text|title|placeholderText|hint|summary|description|displayText|toolTipMainText|toolTipSubText)\s*:(?!:)")
# Nomes próprios e símbolos que não se traduzem
ALLOWED = {"Claude", "Codex", "Gemini", "Claude Code", "Gemini CLI", "ai-usage-collector"}


def value_extent(src: str, pos: int) -> str:
    """Expressão QML que começa em `pos` (depois do ':') até o fim da propriedade."""
    i, depth, n = pos, 0, len(src)
    while i < n:
        c = src[i]
        if c in "\"'":
            m = STRING.match(src, i)
            i = m.end() if m else i + 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            break
        elif c == ";" and depth == 0:
            break
        elif c == "\n" and depth == 0:
            rest = src[i + 1:].lstrip(" \t")
            before = src[pos:i].rstrip()
            if not (rest[:1] in ("?", ":", "+", "|", "&") or before[-1:] in ("?", ":", "+", "|", "&", "")):
                break
        i += 1
    return src[pos:i]


def untranslated_literals(expr: str):
    """Literais com texto de gente (>= 2 letras seguidas) que não estão dentro de tr()/i18n()."""
    out, stack, i = [], [], 0
    while i < len(expr):
        c = expr[i]
        if c in "\"'":
            m = STRING.match(expr, i)
            if not m:
                break
            val = m.group(1) if m.group(1) is not None else m.group(2)
            cmp_ = re.search(r"[=!]==?\s*$", expr[:i]) or re.match(r"\s*[=!]==?", expr[m.end():])  # comparação, não texto
            if not any(stack) and not cmp_ and re.search(r"[^\W\d_]{2}", val) and val not in ALLOWED:
                out.append(val)
            i = m.end(); continue
        if c == "(":
            before = re.search(r"([\w$.]+)\s*$", expr[:i])
            name = before.group(1).split(".")[-1] if before else ""
            stack.append(name in KEYWORDS)
        elif c in "[{":
            stack.append(bool(stack and stack[-1]))
        elif c in ")]}" and stack:
            stack.pop()
        i += 1
    return out


def visible_literals():
    """-> [(arquivo:linha, literal)] de textos visíveis (text:/title:/... ) sem passar por tr()/i18n()."""
    found = []
    for path in sorted(PLASMOID.joinpath("contents").rglob("*.qml")):
        src = strip_comments(path.read_text(encoding="utf-8"))
        for m in VISIBLE.finditer(src):
            for lit_ in untranslated_literals(value_extent(src, m.end())):
                found.append((f"{path.relative_to(PLASMOID).as_posix()}:{src.count(chr(10), 0, m.start()) + 1}", lit_))
    return found


# ---- formato .po ----

def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t") + '"'


def unquote(s: str) -> str:
    return js_unescape(s[1:-1])


def parse_po(text: str):
    """-> lista de dicts {ctx, id, plural, str: [..], fuzzy, refs}; o cabeçalho é a entrada id == ''."""
    out, cur, field = [], None, None

    def flush():
        nonlocal cur
        if cur is not None and cur["id"] is not None:
            out.append(cur)
        cur = None

    for raw in text.splitlines() + [""]:
        line = raw.strip()
        if not line:
            flush(); field = None; continue
        if cur is None:
            cur = {"ctx": None, "id": None, "plural": None, "str": {}, "fuzzy": False, "refs": []}
        if line.startswith("#,"):
            cur["fuzzy"] |= "fuzzy" in line
        elif line.startswith("#:"):
            cur["refs"] += line[2:].split()
        elif line.startswith("#"):
            pass
        elif line.startswith('"'):
            if field is None:
                raise ValueError(f"string solta: {line}")
            if field[0] == "str":
                cur["str"][field[1]] += unquote(line)
            else:
                cur[field[0]] += unquote(line)
        else:
            m = re.fullmatch(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+(".*")', line)
            if not m:
                raise ValueError(f"linha inválida: {line}")
            kw = m.group(1)
            if kw.startswith("msgstr"):
                idx = int(m.group(2) or 0)
                cur["str"][idx] = unquote(m.group(3)); field = ("str", idx)
            else:
                key = {"msgctxt": "ctx", "msgid": "id", "msgid_plural": "plural"}[kw]
                cur[key] = unquote(m.group(3)); field = (key,)
    return out


def write_po(header: str, entries) -> str:
    lines = ['msgid ""', 'msgstr ""'] + [quote(h + "\n") for h in header.strip("\n").split("\n")] + [""]
    for e in entries:
        if e["refs"]:
            lines.append("#: " + " ".join(e["refs"]))
        if e["ctx"] is not None:
            lines.append("msgctxt " + quote(e["ctx"]))
        lines.append("msgid " + quote(e["id"]))
        if e["plural"] is not None:
            lines.append("msgid_plural " + quote(e["plural"]))
            for i in range(len(e["str"])):
                lines.append(f"msgstr[{i}] " + quote(e["str"][i]))
        else:
            lines.append("msgstr " + quote(e["str"].get(0, "")))
        lines.append("")
    return "\n".join(lines)


PLURALS = {"pt_BR": "(n > 1)"}  # demais línguas: inglês (n != 1)


def header_for(lang: str) -> str:
    return ("Project-Id-Version: plasma-ai-usage-widget\nMIME-Version: 1.0\nContent-Type: text/plain; charset=UTF-8\n"
            f"Content-Transfer-Encoding: 8bit\nLanguage: {lang}\nPlural-Forms: nplurals=2; plural={PLURALS.get(lang, '(n != 1)')};")


def template_entries(entries):
    return [{"ctx": k[0], "id": k[1], "plural": k[2], "str": {0: "", 1: ""} if k[2] is not None else {0: ""},
             "fuzzy": False, "refs": sorted(set(v), key=lambda r: (r.rsplit(":", 1)[0], int(r.rsplit(":", 1)[1])))}
            for k, v in sorted(entries.items(), key=lambda kv: (kv[1][0].rsplit(":", 1)[0], int(kv[1][0].rsplit(":", 1)[1])))]


def cmd_extract():
    entries, errors = extract()
    if errors:
        sys.exit("\n".join(errors))
    PO_DIR.mkdir(exist_ok=True)
    (PO_DIR / f"{domain()}.pot").write_text(write_po(header_for(""), template_entries(entries)), encoding="utf-8")
    print(f"{len(entries)} mensagens -> po/{domain()}.pot")


def cmd_update():
    pot = parse_po((PO_DIR / f"{domain()}.pot").read_text(encoding="utf-8"))[1:]
    for po in sorted(PO_DIR.glob("*.po")):
        lang = po.stem
        old = {(e["ctx"], e["id"]): e for e in parse_po(po.read_text(encoding="utf-8"))[1:]}
        merged = []
        for t in pot:
            e = dict(t); prev = old.get((t["ctx"], t["id"]))
            if lang == "en":  # a língua-fonte é o inglês: msgstr == msgid
                e["str"] = {0: t["id"], 1: t["plural"]} if t["plural"] is not None else {0: t["id"]}
            elif prev and prev["plural"] == t["plural"]:
                e["str"] = prev["str"]
            merged.append(e)
        po.write_text(write_po(header_for(lang), merged), encoding="utf-8")
        print(f"{po.name}: {sum(1 for e in merged if not any(e['str'].values()))} sem tradução")


def build_mo(entries) -> bytes:
    """Entradas traduzidas (não fuzzy, sem msgstr vazio) -> bytes de um .mo (little endian)."""
    msgs = {}
    for e in entries:
        strs = [e["str"][i] for i in sorted(e["str"])]
        if e["id"] and (e["fuzzy"] or not all(strs)):
            continue
        key = (e["ctx"] + "\x04" if e["ctx"] is not None else "") + e["id"]
        if e["plural"] is not None:
            key += "\x00" + e["plural"]
        msgs[key.encode()] = "\x00".join(strs).encode()
    keys = sorted(msgs)
    n = len(keys)
    ids = b"".join(k + b"\x00" for k in keys)
    strs = b"".join(msgs[k] + b"\x00" for k in keys)
    ktab_off = 28
    vtab_off = ktab_off + 8 * n
    kstart = vtab_off + 8 * n
    vstart = kstart + len(ids)
    ktab, vtab, o = b"", b"", 0
    for k in keys:
        ktab += struct.pack("<II", len(k), kstart + o); o += len(k) + 1
    o = 0
    for k in keys:
        vtab += struct.pack("<II", len(msgs[k]), vstart + o); o += len(msgs[k]) + 1
    return struct.pack("<IIIIIII", 0x950412DE, 0, n, ktab_off, vtab_off, 0, 0) + ktab + vtab + ids + strs


def cmd_compile(out: Path):
    for po in sorted(PO_DIR.glob("*.po")):
        dest = out / po.stem / "LC_MESSAGES" / f"{domain()}.mo"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(build_mo(parse_po(po.read_text(encoding="utf-8"))))
        print(f"{po.name} -> {dest}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "extract": cmd_extract()
    elif cmd == "update": cmd_update()
    elif cmd == "check":
        bad = extract()[1] + [f"{w}: texto visível fora de i18n: {v!r}" for w, v in visible_literals()]
        sys.exit("\n".join(bad) or 0)
    elif cmd == "compile" and len(sys.argv) == 3: cmd_compile(Path(sys.argv[2]))
    else: sys.exit(__doc__)
