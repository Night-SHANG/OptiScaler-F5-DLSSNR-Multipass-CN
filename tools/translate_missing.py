#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, sys, urllib.request
from loclib import *

def call_api(url,key,model,items,glossary):
    prompt=("Translate only these OptiScaler UI strings to Simplified Chinese. Preserve product/API names, printf/std::format placeholders, "
            "newlines and ImGui ## suffixes exactly. Follow the glossary. Return ONLY a JSON object mapping each key to its Chinese text.\n"
            f"Glossary: {json.dumps(glossary,ensure_ascii=False)}\nItems: {json.dumps(items,ensure_ascii=False)}")
    body=json.dumps({'model':model,'messages':[{'role':'system','content':'You are a software UI localization engine.'},{'role':'user','content':prompt}], 'temperature':0.1}).encode()
    req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json','Authorization':f'Bearer {key}'})
    with urllib.request.urlopen(req,timeout=120) as r: data=json.load(r)
    content=data['choices'][0]['message']['content'].strip()
    if content.startswith('```'): content=content.split('\n',1)[1].rsplit('```',1)[0]
    return json.loads(content)


def apply_translation(entries: dict, kind: str, item: dict, text: str, model: str):
    """Apply one machine result without ever overwriting human-reviewed text."""
    old=entries.get(item['key'])
    candidate={'text':text,'source_hash':item['source_hash'],'state':'machine_translated','model':model}
    if old and old.get('state')=='reviewed':
        old['candidate']=candidate
        return
    entries[item['key']]=candidate

def collect_pending(channels: tuple[str, ...]) -> list[tuple[str, dict]]:
    unique={}
    for channel in channels:
        pending=load_json(localization_channel_paths(channel)['pending'],{'missing':[],'changed':[]})
        for kind in ('missing','changed'):
            for item in pending.get(kind,[]):
                token=(item.get('key'),item.get('source_hash'))
                if not token[0] or token in unique: continue
                unique[token]=(kind,item)
    return list(unique.values())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--batch-size',type=int,default=40)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--channel',choices=(*CHANNELS,'all'),default='all')
    args=ap.parse_args()
    url=os.getenv('TRANSLATION_API_URL','').strip(); key=os.getenv('TRANSLATION_API_KEY','').strip(); model=os.getenv('TRANSLATION_MODEL','').strip()
    channels=CHANNELS if args.channel=='all' else (args.channel,)
    zh=load_json(LOC/'zh-CN.json',{'locale':'zh-CN','entries':{}}); glossary=load_json(LOC/'glossary.json',{})
    work=collect_pending(channels)
    if not work: print('nothing to translate'); return 0
    if not (url and key and model):
        print(f'API not configured; {len(work)} unique strings remain pending and will use English fallback')
        return 0
    z=zh.setdefault('entries',{})
    for n in range(0,len(work),args.batch_size):
        batch=work[n:n+args.batch_size]
        payload={item['key']:item['source'] for _,item in batch}
        translated=call_api(url,key,model,payload,glossary)
        for kind,item in batch:
            text=translated.get(item['key'])
            if not text: continue
            apply_translation(z,kind,item,text,model)
    if not args.dry_run: save_json(LOC/'zh-CN.json',zh)
    print(f'processed {len(work)} unique pending strings from {", ".join(channels)}')
    return 0
if __name__=='__main__': raise SystemExit(main())
