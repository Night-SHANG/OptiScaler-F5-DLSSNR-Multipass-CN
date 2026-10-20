#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path
from loclib import LOC, CHANNELS, localization_channel_paths, load_json, save_json


def merged_memory(existing: dict, catalog: dict, zh: dict) -> dict:
    result=dict(existing)
    zentries=zh.get('entries',{})
    for key,entry in catalog.get('entries',{}).items():
        if entry.get('obsolete'): continue
        tr=zentries.get(key,{})
        if tr.get('state')!='reviewed' or not tr.get('text'): continue
        if tr.get('source_hash')!=entry.get('source_hash'): continue
        result[entry.get('source','')]=tr['text']
    result.pop('',None)
    return dict(sorted(result.items(),key=lambda kv: kv[0].casefold()))


def merged_memory_many(existing: dict, catalogs: list[dict], zh: dict) -> dict:
    result=dict(existing)
    for catalog in catalogs:
        result=merged_memory(result,catalog,zh)
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--check',action='store_true',help='fail if translation memory is not synchronized')
    args=ap.parse_args()
    path=LOC/'translation-memory.zh-CN.json'
    current=load_json(path,{})
    catalogs=[load_json(localization_channel_paths(channel)['catalog'],{}) for channel in CHANNELS]
    zh=load_json(LOC/'zh-CN.json',{})
    merged=merged_memory_many(current,catalogs,zh)
    if args.check:
        if merged!=current:
            print('translation memory is out of date; run tools/update_translation_memory.py')
            return 1
        print(f'translation memory synchronized: {len(current)} reviewed sources')
        return 0
    save_json(path,merged)
    print(f'translation memory updated: {len(merged)} reviewed sources')
    return 0

if __name__=='__main__': raise SystemExit(main())
