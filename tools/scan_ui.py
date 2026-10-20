#!/usr/bin/env python3
from __future__ import annotations
import argparse, difflib, subprocess
from pathlib import Path
from loclib import *
from ui_scan import find_ui_candidates

def git_sha(root: Path):
    try: return subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    except Exception: return ''

def stable_scan_delta(previous_commit: str, current_commit: str, previous: dict, current: dict) -> dict:
    """Keep the last upstream-transition delta across a clean same-pin CI rescan."""
    kinds = ('added', 'changed', 'removed')
    if (re.fullmatch(r'[0-9a-f]{40}', current_commit) and current_commit == previous_commit
            and all(not current.get(k) for k in kinds)
            and all(isinstance(previous.get(k), list) and all(isinstance(v, str) for v in previous[k]) for k in kinds)):
        return {k: list(previous[k]) for k in kinds}
    return current

@dataclass
class ReconcileResult:
    catalog_entries: dict
    zh_entries: dict
    added: list[str]
    changed: list[tuple[str,str,str]]
    removed: list[str]
    missing: list[str]
    stale: list[str]


def load_translation_memory() -> dict:
    """Merge the general TM with reviewed DLSS-NR UI translations.

    The supplemental file is intentionally small and reviewable. It covers UI
    surfaces discovered by the extended scanner without forcing large rewrites
    of the long-lived general translation-memory file.
    """
    tm=load_json(LOC/'translation-memory.zh-CN.json',{})
    tm.update(load_json(LOC/'translation-memory.dlssnr.zh-CN.json',{}))
    for path in sorted(LOC.glob('translation-memory.f5-*.zh-CN.json')):
        tm.update(load_json(path, {}))
    for entry in load_json(LOC/'composed-templates.json', []):
        tm[entry['source']] = entry['text']
    return tm


def reconcile(found: list[Candidate], old_entries: dict, zh: dict, tm: dict) -> ReconcileResult:
    """Reconcile one upstream channel using immutable source-derived keys.

    A changed English source receives a new key. This allows master and the
    current stable release to coexist in one shared zh-CN translation store
    even when the two branches use different wording for the same UI slot.
    """
    old_by_source={v.get('source'):k for k,v in old_entries.items() if not v.get('obsolete')}
    old_by_scope={}
    for k,v in old_entries.items():
        if v.get('obsolete'): continue
        for o in v.get('occurrences',[]):
            old_by_scope.setdefault((o.get('file'),o.get('callee')),[]).append((k,v))

    entries={k:{**v,'occurrences':[]} for k,v in old_entries.items()}
    used=set(); added=[]; changed=[]
    # Filesystem traversal order differs across fresh clones and OSes.
    # Stabilize both occurrence arrays and new source-key insertion order.
    for c in sorted(found, key=lambda c: (c.file, c.line, c.callee, c.arg_index, c.source)):
        key=old_by_source.get(c.source)
        previous_source=None
        if key is None:
            best=None; best_ratio=0.0
            for old_key,v in old_by_scope.get((c.file,c.callee),[]):
                if old_key in used: continue
                r=difflib.SequenceMatcher(None,v.get('source',''),c.source).ratio()
                if r>best_ratio: best_ratio=r; best=(old_key,v)
            if best and best_ratio>=0.84:
                previous_source=best[1].get('source','')
            key=key_for_source(c.source)
            suffix=1; base=key
            while key in entries and entries[key].get('source')!=c.source:
                suffix+=1; key=f'{base}.{suffix}'
            if key not in entries:
                entries[key]={'source':c.source,'source_hash':sha(c.source),'occurrences':[],
                              'obsolete':False,'previous_sources':[previous_source] if previous_source else []}
                added.append(key)
            if previous_source and previous_source != c.source:
                changed.append((key,previous_source,c.source))
        used.add(key)
        e=entries[key]; e['source']=c.source; e['source_hash']=sha(c.source); e['obsolete']=False
        occurrence={'file':c.file,'line':c.line,'callee':c.callee,'arg':c.arg_index}
        if occurrence not in e['occurrences']:
            e['occurrences'].append(occurrence)

    removed=[]
    for k,e in entries.items():
        if k not in used and not e.get('obsolete'):
            e['obsolete']=True; removed.append(k)

    current={k:e for k,e in entries.items() if not e.get('obsolete')}
    zentries={k:dict(v) for k,v in zh.get('entries',{}).items()}
    for k,e in current.items():
        z=zentries.get(k)
        if z is None and e['source'] in tm:
            zentries[k]={'text':tm[e['source']],'state':'machine_translated','source_hash':e['source_hash'],
                         'note':'AI translation or exact-source translation-memory reuse; not human reviewed'}

    missing=[]; stale=[]
    for k,e in current.items():
        z=zentries.get(k)
        if not z or not z.get('text'):
            missing.append(k)
        elif z.get('source_hash')!=e['source_hash']:
            stale.append(k)
    return ReconcileResult(entries,zentries,added,changed,removed,missing,stale)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source',required=True,type=Path)
    ap.add_argument('--channel',choices=CHANNELS,default='master')
    ap.add_argument('--upstream-ref',default=load_json(ROOT/'upstream.json',{}).get('upstream_version',''))
    ap.add_argument('--update',action='store_true')
    ap.add_argument('--report',type=Path,default=ROOT/'reports'/'localization-scan.md')
    args=ap.parse_args()
    rules=load_json(LOC/'scanner-rules.json',{})
    paths=localization_channel_paths(args.channel)
    old=load_json(paths['catalog'],{'schema':1,'channel':args.channel,'entries':{}})
    en=load_json(paths['en'],{'locale':'en-US','channel':args.channel,'entries':{}})
    zh=load_json(LOC/'zh-CN.json',{'locale':'zh-CN','entries':{}})
    tm=load_translation_memory()
    old_entries=old.get('entries',{})

    found=[]
    for p in iter_source_files(args.source,rules):
        rel=p.relative_to(args.source).as_posix()
        text,_=read_source_text(p)
        found.extend(find_ui_candidates(text,rel,rules))

    for entry in load_json(LOC/'composed-templates.json', []):
        found.append(Candidate(entry['file'], 'f5:composed-template', 0, entry['source'], -1, -1, 0, '', False))

    result=reconcile(found, old_entries, zh, tm)
    entries=result.catalog_entries
    zentries=result.zh_entries
    added=result.added
    changed=result.changed
    removed=result.removed
    missing=result.missing
    stale=result.stale
    current={k:e for k,e in entries.items() if not e.get('obsolete')}
    en_entries={k:{'text':e['source'],'source_hash':e['source_hash']} for k,e in current.items()}

    commit=git_sha(args.source)
    delta=stable_scan_delta(old.get('upstream_commit',''), commit,
        load_json(paths['pending'],{}).get('scan',{}),
        {'added':added,'changed':[k for k,_,_ in changed],'removed':removed})
    pending={
      'locale':'zh-CN',
      'scan':delta,
      'missing':[{'key':k,'source':current[k]['source'],'source_hash':current[k]['source_hash']} for k in missing],
      'changed':[{'key':k,'source':current[k]['source'],'source_hash':current[k]['source_hash'],'old_translation':zentries.get(k,{}).get('text',''),'state':zentries.get(k,{}).get('state','')} for k in stale]
    }
    catalog={'schema':1,'channel':args.channel,'upstream_commit':commit,'entries':entries}
    coverage=(len(current)-len(missing)-len(stale))/len(current)*100 if current else 100.0
    report=[
      '# Localization scan report','',f'- Channel: **{args.channel}**',f'- Upstream commit: `{commit or "unknown"}`',
      f'- Active UI strings: **{len(current)}**',f'- Added: **{len(added)}**',f'- Removed: **{len(removed)}**',
      f'- Source changed / translation stale: **{len(stale)}**',f'- Missing zh-CN: **{len(missing)}**',f'- Effective zh-CN coverage: **{coverage:.2f}%**',''
    ]
    if added: report += ['## Added','']+[f'- `{k}` — {current[k]["source"]!r}' for k in added[:100]]+['']
    if stale: report += ['## Changed / stale','']+[f'- `{k}` — {current[k]["source"]!r}' for k in stale[:100]]+['']
    if removed: report += ['## Removed','']+[f'- `{k}`' for k in removed[:100]]+['']
    args.report.parent.mkdir(parents=True,exist_ok=True); args.report.write_text('\n'.join(report).rstrip()+'\n',encoding='utf-8')
    if args.update:
        save_json(paths['catalog'],catalog)
        save_json(paths['en'],{'locale':'en-US','channel':args.channel,'entries':en_entries})
        save_json(LOC/'zh-CN.json',{'locale':'zh-CN','entries':zentries})
        save_json(paths['pending'],pending)
        save_json(paths['meta'],{'channel':args.channel,'upstream_ref':args.upstream_ref,'upstream_commit':commit})
        if args.channel == 'master':
            save_json(LOC/'catalog.json',catalog)
            save_json(LOC/'en-US.json',{'locale':'en-US','channel':'master','entries':en_entries})
            save_json(LOC/'pending.json',pending)
    print(f'active={len(current)} added={len(added)} removed={len(removed)} missing={len(missing)} stale={len(stale)} coverage={coverage:.2f}%')

if __name__=='__main__': main()
