#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys
from loclib import *


def analyze(cat: dict, en: dict, zh: dict) -> dict:
    """Validate structural safety and report fallback states separately.

    Missing/stale translations remain safe at runtime because they fall back to
    the canonical English source. Release/CI callers can additionally use
    --strict to require complete, current zh-CN coverage.
    """
    errors=[]; warnings=[]
    active={k:v for k,v in cat.get('entries',{}).items() if not v.get('obsolete')}
    if en.get('locale')!='en-US': errors.append('en-US.json locale must be en-US')
    if zh.get('locale')!='zh-CN': errors.append('zh-CN.json locale must be zh-CN')
    zentries=zh.get('entries',{})
    reviewed=machine=missing=stale=0
    for k,e in active.items():
        src=e.get('source',''); h=e.get('source_hash')
        if sha(src)!=h: errors.append(f'{k}: catalog source_hash mismatch')
        en_entry=en.get('entries',{}).get(k,{})
        if en_entry.get('text')!=src: errors.append(f'{k}: en-US mismatch')
        if en_entry.get('source_hash') not in (None,h): errors.append(f'{k}: en-US source_hash mismatch')
        z=zentries.get(k)
        if not z or not z.get('text'):
            missing+=1
            continue
        if z.get('source_hash')!=h:
            stale+=1
            warnings.append(f'{k}: zh-CN is stale and will fall back to English')
            continue
        state=z.get('state')
        if state not in ('reviewed','machine_translated'):
            errors.append(f'{k}: invalid translation state {state!r}')
            continue
        reviewed += state=='reviewed'; machine += state=='machine_translated'
        if printf_tokens(src)!=printf_tokens(z['text']): errors.append(f'{k}: printf placeholders differ')
        if format_tokens(src)!=format_tokens(z['text']): errors.append(f'{k}: std::format placeholders differ')
        if '##' in src:
            if '##' not in z['text'] or src.split('##',1)[1] != z['text'].split('##',1)[1]:
                errors.append(f'{k}: ImGui ## id suffix changed or missing')
    total=len(active); effective=reviewed+machine
    stats={'total':total,'reviewed':reviewed,'machine':machine,'missing':missing,'stale':stale,
           'coverage':100.0*effective/total if total else 100.0}
    return {'errors':errors,'warnings':warnings,'stats':stats}


def should_fail(result: dict, strict: bool = False) -> bool:
    if result.get('errors'):
        return True
    if strict:
        stats=result.get('stats',{})
        return bool(stats.get('missing',0) or stats.get('stale',0))
    return False


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--strict',action='store_true',help='also require zero missing/stale zh-CN translations')
    ap.add_argument('--channel',choices=(*CHANNELS,'all'),default='all')
    args=ap.parse_args()
    zh=load_json(LOC/'zh-CN.json',{})
    channels=CHANNELS if args.channel=='all' else (args.channel,)
    failed=False
    for channel in channels:
        paths=localization_channel_paths(channel)
        cat=load_json(paths['catalog'],{'entries':{}})
        en=load_json(paths['en'],{'locale':'en-US','entries':{}})
        result=analyze(cat,en,zh); st=result['stats']
        print(f"[{channel}] total={st['total']} reviewed={st['reviewed']} machine={st['machine']} missing={st['missing']} stale={st['stale']} coverage={st['coverage']:.2f}%")
        for w in result['warnings'][:50]: print(f'WARN [{channel}]:',w)
        for e in result['errors']:
            print(f'ERROR [{channel}]: {e}',file=sys.stderr)
        if args.strict and (st['missing'] or st['stale']):
            print(f"ERROR [{channel}]: strict mode requires complete zh-CN coverage (missing={st['missing']}, stale={st['stale']})",file=sys.stderr)
        if should_fail(result,args.strict):
            failed=True
    return 1 if failed else 0

if __name__=='__main__': raise SystemExit(main())
