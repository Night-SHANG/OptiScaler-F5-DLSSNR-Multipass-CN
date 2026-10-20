#!/usr/bin/env python3
from __future__ import annotations
import ast, fnmatch, hashlib, json, re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
LOC = ROOT / "Localization"
CHANNELS = ("master",)

def localization_channel_dir(channel: str) -> Path:
    if channel not in CHANNELS:
        raise ValueError(f"unsupported localization channel: {channel}")
    return LOC / channel

def localization_channel_paths(channel: str) -> dict[str, Path]:
    base = localization_channel_dir(channel)
    return {
        "base": base,
        "catalog": base / "catalog.json",
        "en": base / "en-US.json",
        "pending": base / "pending.json",
        "meta": base / "meta.json",
    }

def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8-sig"))

def save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")

def read_source_text(path: Path) -> tuple[str, str]:
    """Read upstream C/C++ text while preserving its original byte encoding.

    OptiScaler contains a small number of legacy Windows-encoded source files.
    Localization injection only adds ASCII source text, so retaining the original
    encoding avoids changing unrelated upstream bytes.
    """
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", raw, 0, len(raw), "unable to decode source file")

def write_source_text(path: Path, text: str, encoding: str) -> None:
    path.write_bytes(text.encode(encoding))

def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def key_for_source(text: str) -> str:
    return "ui.auto." + hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

def cpp_unescape(content: str) -> str:
    # Interpret common C/C++ escapes without touching non-ASCII characters.
    try:
        return ast.literal_eval('"' + content.replace('"', '\\"') + '"')
    except Exception:
        # Conservative fallback.
        return bytes(content, "utf-8").decode("unicode_escape", errors="replace")

def decode_cpp_string_token(token: str) -> str | None:
    token = token.strip()
    m = re.fullmatch(r'(?:u8|u|U|L)?"((?:\\.|[^"\\])*)"', token, re.S)
    if not m:
        return None
    raw = m.group(1)
    out = []
    i = 0
    while i < len(raw):
        if raw[i] != '\\':
            out.append(raw[i]); i += 1; continue
        i += 1
        if i >= len(raw): out.append('\\'); break
        c = raw[i]; i += 1
        table = {'n':'\n','r':'\r','t':'\t','0':'\0','\\':'\\','"':'"',"'":"'"}
        if c in table: out.append(table[c]); continue
        if c == 'x':
            j=i
            while j < len(raw) and raw[j] in '0123456789abcdefABCDEF': j += 1
            try: out.append(chr(int(raw[i:j],16))); i=j
            except: out.append('\\x')
            continue
        if c == 'u' and i+4 <= len(raw):
            try: out.append(chr(int(raw[i:i+4],16))); i += 4
            except: out.append('\\u')
            continue
        if c == 'U' and i+8 <= len(raw):
            try: out.append(chr(int(raw[i:i+8],16))); i += 8
            except: out.append('\\U')
            continue
        out.append(c)
    return ''.join(out)

def extract_string_expression(expr: str) -> str | None:
    # Accept concatenated ordinary/u8 C++ string literals only.
    pos = 0; parts=[]
    pat = re.compile(r'\s*(?:u8|u|U|L)?"((?:\\.|[^"\\])*)"', re.S)
    while pos < len(expr):
        m = pat.match(expr, pos)
        if not m: break
        token = expr[m.start():m.end()].strip()
        dec = decode_cpp_string_token(token)
        if dec is None: return None
        parts.append(dec); pos=m.end()
    if not parts or expr[pos:].strip(): return None
    return ''.join(parts)

@lru_cache(maxsize=4)
def mask_cpp(text: str) -> str:
    out=list(text); i=0; n=len(text); state='code'
    while i<n:
        if state=='code':
            if text.startswith('//',i): out[i]=out[i+1]=' '; i+=2; state='line'; continue
            if text.startswith('/*',i): out[i]=out[i+1]=' '; i+=2; state='block'; continue
            if text[i]=='"': out[i]=' '; i+=1; state='str'; continue
            if text[i]=="'": out[i]=' '; i+=1; state='char'; continue
            i+=1
        elif state=='line':
            if text[i]=='\n': state='code'
            else: out[i]=' '
            i+=1
        elif state=='block':
            if text.startswith('*/',i): out[i]=out[i+1]=' '; i+=2; state='code'
            else: out[i]=' '; i+=1
        elif state in ('str','char'):
            quote='"' if state=='str' else "'"
            if text[i]=='\\':
                out[i]=' '; i+=1
                if i<n: out[i]=' '; i+=1
            elif text[i]==quote: out[i]=' '; i+=1; state='code'
            else:
                if text[i] != '\n': out[i]=' '
                i+=1
    return ''.join(out)

def find_matching(text: str, start: int, open_c='(', close_c=')') -> int:
    depth=0; i=start; n=len(text); state='code'
    while i<n:
        c=text[i]
        if state=='code':
            if text.startswith('//',i): i+=2; state='line'; continue
            if text.startswith('/*',i): i+=2; state='block'; continue
            if c=='"': i+=1; state='str'; continue
            if c=="'": i+=1; state='char'; continue
            if c==open_c: depth+=1
            elif c==close_c:
                depth-=1
                if depth==0: return i
            i+=1
        elif state=='line':
            if c=='\n': state='code'
            i+=1
        elif state=='block':
            if text.startswith('*/',i): i+=2; state='code'
            else: i+=1
        elif state in ('str','char'):
            q='"' if state=='str' else "'"
            if c=='\\': i+=2
            elif c==q: i+=1; state='code'
            else: i+=1
    return -1

def split_args(text: str, start: int, end: int):
    ranges=[]; arg_start=start; i=start; depths={'(':0,'[':0,'{':0}; state='code'
    pairs={')':'(',']':'[','}':'{'}
    while i<end:
        c=text[i]
        if state=='code':
            if text.startswith('//',i): i+=2; state='line'; continue
            if text.startswith('/*',i): i+=2; state='block'; continue
            if c=='"': i+=1; state='str'; continue
            if c=="'": i+=1; state='char'; continue
            if c in depths: depths[c]+=1
            elif c in pairs and depths[pairs[c]]>0: depths[pairs[c]]-=1
            elif c==',' and all(v==0 for v in depths.values()):
                ranges.append((arg_start,i)); arg_start=i+1
            i+=1
        elif state=='line':
            if c=='\n': state='code'
            i+=1
        elif state=='block':
            if text.startswith('*/',i): i+=2; state='code'
            else: i+=1
        else:
            q='"' if state=='str' else "'"
            if c=='\\': i+=2
            elif c==q: i+=1; state='code'
            else: i+=1
    ranges.append((arg_start,end))
    return ranges

@dataclass
class Candidate:
    file: str
    callee: str
    arg_index: int
    source: str
    start: int
    end: int
    line: int
    original_expr: str
    rewrite: bool = True


def should_exclude(source: str, rules: dict) -> bool:
    s=source.strip()
    if s in rules.get('exclude_exact',[]): return True
    if any(s.startswith(p) for p in rules.get('exclude_prefixes',[])): return True
    # Hidden ImGui suffix is fine; visible prefix still localizable.
    visible=s.split('##',1)[0]
    if not visible.strip(): return True
    for rx in rules.get('technical_regex',[]):
        if re.fullmatch(rx, visible.strip()): return True
    if not re.search(r'[A-Za-z]', visible): return True
    return False


def _string_literals_in_region(text: str, start: int, end: int):
    """Yield string literals in a C++ region, excluding comments/chars."""
    i=start; state='code'
    while i < end:
        if state=='code':
            if text.startswith('//', i): i += 2; state='line'; continue
            if text.startswith('/*', i): i += 2; state='block'; continue
            if text[i]=="'": i += 1; state='char'; continue
            prefix_start=i; quote=-1
            if text.startswith('u8\"', i): quote=i+2
            elif i+1<end and text[i] in 'uUL' and text[i+1]=='\"': quote=i+1
            elif text[i]=='\"': quote=i
            if quote >= 0:
                j=quote+1
                while j<end:
                    if text[j]=='\\': j += 2; continue
                    if text[j]=='\"':
                        tok_end=j+1; token=text[prefix_start:tok_end]
                        decoded=decode_cpp_string_token(token)
                        if decoded is not None: yield prefix_start,tok_end,decoded,token
                        i=tok_end; break
                    j += 1
                else: return
                continue
            i += 1
        elif state=='line':
            if text[i]=='\n': state='code'
            i += 1
        elif state=='block':
            if text.startswith('*/',i): i += 2; state='code'
            else: i += 1
        else:
            if text[i]=='\\': i += 2
            elif text[i]=="'": i += 1; state='code'
            else: i += 1


def find_container_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Catalog initializer labels/tooltips; central TL(source) translates them at runtime."""
    masked=mask_cpp(text); out=[]
    for anchor in rules.get('scan_containers',[]):
        pos=0
        while True:
            idx=masked.find(anchor,pos)
            if idx<0: break
            limit=min(len(masked),idx+8000)
            semi=masked.find(';',idx,limit)
            if semi<0: semi=limit
            eq=masked.find('=',idx,semi)
            brace=masked.find('{',eq+1,semi) if eq>=0 else -1
            if eq<0 or brace<0:
                pos=idx+len(anchor); continue
            close=find_matching(text,brace,'{','}')
            if close<0:
                pos=idx+len(anchor); continue
            for a,b,src,expr in _string_literals_in_region(text,brace+1,close):
                if should_exclude(src,rules): continue
                out.append(Candidate(rel,'container:'+anchor,0,src,a,b,text.count('\n',0,a)+1,expr,False))
            pos=close+1
    return out

def find_member_assignment_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Catalog direct assignments to known user-visible string members such as MenuOption.label."""
    masked=mask_cpp(text); out=[]
    for member in rules.get('member_assignments',[]):
        pattern=re.compile(r'\.'+re.escape(member)+r'\s*=')
        for m in pattern.finditer(masked):
            eq=masked.find('=',m.start(),m.end()+1)
            if eq < 0: continue
            semi=masked.find(';',eq+1)
            if semi < 0: continue
            expr=text[eq+1:semi]
            source=extract_string_expression(expr.strip())
            if source is None or should_exclude(source,rules): continue
            left=eq+1+(len(expr)-len(expr.lstrip()))
            right=semi-(len(expr)-len(expr.rstrip()))
            out.append(Candidate(rel,f'assignment:.{member}',0,source,left,right,
                                 text.count('\n',0,left)+1,text[left:right],True))
    return out


def find_vararg_literal_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Find literal strings passed as printf-style data to UI calls.

    OptiScaler sometimes renders a user-facing choice through a format string,
    e.g. ImGui::Text("%s", enabled ? "Active" : "Passive").  Those literals
    are UI even though they are not the format argument itself.
    """
    masked=mask_cpp(text); out=[]
    for name,start_index in rules.get('vararg_literal_calls',{}).items():
        pattern=re.compile(r'(?<![\w:])'+re.escape(name)+r'\s*\(')
        for m in pattern.finditer(masked):
            p=masked.find('(',m.start(),m.end()+2)
            if p < 0: continue
            q=find_matching(text,p)
            if q < 0: continue
            args=split_args(text,p+1,q)
            for arg_index,(a,b) in enumerate(args):
                if arg_index < int(start_index): continue
                for left,right,source,expr in _string_literals_in_region(text,a,b):
                    if should_exclude(source,rules): continue
                    out.append(Candidate(rel,f'{name}:vararg',arg_index,source,left,right,
                                         text.count('\n',0,left)+1,expr,True))
    return out


def find_nested_ui_call_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Catalog format calls nested in a UI string argument.

    A nested call is represented by its entire call expression so the injector
    can replace compile-time std::format with the runtime-safe Loc::F helper.
    """
    masked=mask_cpp(text); out=[]
    outer_calls=dict(rules.get('calls',{}))
    for scoped in rules.get('scoped_calls',[]):
        if fnmatch.fnmatch(rel, scoped.get('glob','')):
            outer_calls.update(scoped.get('calls',{}))
    nested_rules=rules.get('nested_ui_calls',{})
    for outer,indexes in outer_calls.items():
        if outer.startswith('.'): continue
        pattern=re.compile(r'(?<![\w:])'+re.escape(outer)+r'\s*\(')
        for m in pattern.finditer(masked):
            p=masked.find('(',m.start(),m.end()+2)
            if p < 0: continue
            q=find_matching(text,p)
            if q < 0: continue
            args=split_args(text,p+1,q)
            for idx in indexes:
                if idx >= len(args): continue
                a,b=args[idx]
                region_masked=masked[a:b]
                for nested,arg_indexes in nested_rules.items():
                    npat=re.compile(r'(?<![\w:])'+re.escape(nested)+r'\s*\(')
                    for nm in npat.finditer(region_masked):
                        call_start=a+nm.start()
                        call_p=masked.find('(',call_start,a+nm.end()+2)
                        if call_p < 0: continue
                        call_q=find_matching(text,call_p)
                        if call_q < 0 or call_q > b: continue
                        nargs=split_args(text,call_p+1,call_q)
                        for nidx in arg_indexes:
                            if nidx >= len(nargs): continue
                            na,nb=nargs[nidx]
                            source=extract_string_expression(text[na:nb].strip())
                            if source is None or should_exclude(source,rules): continue
                            out.append(Candidate(rel,f'nested:{nested}',nidx,source,call_start,call_q+1,
                                                 text.count('\n',0,call_start)+1,
                                                 text[call_start:call_q+1],True))
    return out



def find_scoped_c_string_array_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Find user-facing C string lookup arrays in narrowly-scoped UI files.

    OptiScaler uses local ``const char* foo[]`` tables for Combo/Selectable
    values.  Rewriting each literal is safe because Loc::T returns a stable
    ``const char*`` for the process lifetime.
    """
    if not any(fnmatch.fnmatch(rel, glob) for glob in rules.get('c_string_array_globs', [])):
        return []
    masked=mask_cpp(text); out=[]
    pattern=re.compile(r'(?:(?:static|constexpr)\s+)*const\s+char\s*\*\s*(?:const\s+)?[A-Za-z_]\w*\s*\[\s*\]\s*=')
    for m in pattern.finditer(masked):
        brace=masked.find('{',m.end())
        semi=masked.find(';',m.end())
        if brace < 0 or (semi >= 0 and brace > semi): continue
        close=find_matching(text,brace,'{','}')
        if close < 0: continue
        for left,right,source,expr in _string_literals_in_region(text,brace+1,close):
            if should_exclude(source,rules): continue
            visible = source.split('##', 1)[0].strip()
            if any(re.fullmatch(rx, visible) for rx in rules.get('c_string_array_exclude_regex', [])):
                continue
            out.append(Candidate(rel,'c-string-array',0,source,left,right,
                                 text.count('\n',0,left)+1,expr,True))
    return out


def find_conditional_arg_literal_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    """Find literals in configured ternary UI arguments.

    Pure literal arguments are already handled by ``find_candidates``.  This
    path exists for expressions such as ``condition ? "A" : "B"``.
    """
    masked=mask_cpp(text); out=[]
    for name in rules.get('conditional_literal_calls', []):
        pattern=re.compile(r'(?<![\w:])'+re.escape(name)+r'\s*\(')
        for m in pattern.finditer(masked):
            p=masked.find('(',m.start(),m.end()+2)
            if p < 0: continue
            q=find_matching(text,p)
            if q < 0: continue
            args=split_args(text,p+1,q)
            indexes=rules.get('calls',{}).get(name,[0])
            for idx in indexes:
                if idx >= len(args): continue
                a,b=args[idx]
                if '?' not in masked[a:b]: continue
                for left,right,source,expr in _string_literals_in_region(text,a,b):
                    if should_exclude(source,rules): continue
                    out.append(Candidate(rel,f'{name}:conditional',idx,source,left,right,
                                         text.count('\n',0,left)+1,expr,True))
    return out

def find_candidates(text: str, rel: str, rules: dict) -> list[Candidate]:
    masked=mask_cpp(text)
    results=[]
    calls=dict(rules['calls'])
    # Additional calls can be enabled only for narrow source scopes. This is
    # useful for formatting helpers such as StrFmt that are UI-facing inside
    # menu code but also used for internal diagnostics elsewhere.
    for scoped in rules.get('scoped_calls', []):
        if fnmatch.fnmatch(rel, scoped.get('glob', '')):
            for callee, indexes in scoped.get('calls', {}).items():
                calls[callee] = indexes
    # Longest first avoids matching Text inside TextColored.
    names=sorted(calls, key=len, reverse=True)
    for name in names:
        # Method pseudo-name begins with dot.
        if name.startswith('.'):
            pattern=re.compile(re.escape(name)+r'\s*\(')
        else:
            pattern=re.compile(r'(?<![\w:])'+re.escape(name)+r'\s*\(')
        for m in pattern.finditer(masked):
            p=masked.find('(',m.start(),m.end()+2)
            if p<0: continue
            q=find_matching(text,p)
            if q<0: continue
            args=split_args(text,p+1,q)
            for idx in calls[name]:
                if idx>=len(args): continue
                a,b=args[idx]; expr=text[a:b]
                src=extract_string_expression(expr.strip())
                if src is None or should_exclude(src,rules): continue
                # Preserve leading/trailing whitespace boundaries for rewrite.
                left=a + (len(expr)-len(expr.lstrip()))
                right=b - (len(expr)-len(expr.rstrip()))
                results.append(Candidate(rel,name,idx,src,left,right,text.count('\n',0,left)+1,text[left:right]))
    results.extend(find_container_candidates(text, rel, rules))
    results.extend(find_member_assignment_candidates(text, rel, rules))
    results.extend(find_vararg_literal_candidates(text, rel, rules))
    results.extend(find_nested_ui_call_candidates(text, rel, rules))
    results.extend(find_scoped_c_string_array_candidates(text, rel, rules))
    results.extend(find_conditional_arg_literal_candidates(text, rel, rules))
    # De-duplicate overlaps; prefer a rewritable call-site candidate.
    uniq={}
    for c in results:
        k=(c.start,c.end)
        if k not in uniq or c.rewrite:
            uniq[k]=c
    return sorted(uniq.values(), key=lambda c:c.start)

def iter_source_files(source_root: Path, rules: dict) -> Iterable[Path]:
    seen=set()
    for pat in rules.get('include_globs',[]):
        for p in source_root.glob(pat):
            if not p.is_file(): continue
            rel=p.relative_to(source_root).as_posix()
            if rel != 'OptiScaler/include/imgui/ImGuiNotify.hpp' and any(fnmatch.fnmatch(rel,x) for x in rules.get('exclude_globs',[])): continue
            if p not in seen:
                seen.add(p); yield p

def printf_tokens(s: str):
    # Preserve %% and positional/width modifiers sufficiently for validation.
    # Plain prose percentages such as "2-4% additional" can otherwise look
    # like the valid printf token "% a" (space flag + hex-float specifier).
    pattern = re.compile(r'%(?:\d+\$)?[-+#0 \'I]*(?:\d+|\*)?(?:\.\d+|\.\*)?(?:hh|h|ll|l|j|z|t|L)?[diuoxXfFeEgGaAcspn%]')
    tokens=[]
    for m in pattern.finditer(s):
        token=m.group(0)
        if m.start()>0 and (s[m.start()-1].isdigit() or (s[m.start()-1] == '}' and format_tokens(s[:m.start()]))) and token.startswith('% '):
            continue
        tokens.append(token)
    return tokens
def format_tokens(s: str):
    # std::format/fmt supports automatic fields (`{}` / `{:.2f}`), indexed
    # fields and named fields. Escaped braces (`{{` / `}}`) are not tokens.
    return re.findall(r'(?<!\{)\{(?:\d+|[A-Za-z_][\w]*)?(?::[^{}]*)?\}(?!\})', s)
