"""Task-local subprocess bridge to the installed Loom search component API."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime',type=Path);parser.add_argument('input',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();sys.path.insert(0,str(args.runtime.resolve().parent))
    from surd_search import SearchIndex,save
    data=json.loads(args.input.read_text());started=time.perf_counter()
    index=SearchIndex(data['rows'],{'analysis':'english'})
    save(index,args.output/'native-index.json')
    build_ms=(time.perf_counter()-started)*1000
    result=index.search(data['query'],{'k':data['top_k'],'mode':data['ranker']})
    started=time.perf_counter();documents=[index.document(hit['id']) for hit in result['hits']]
    read_ms=(time.perf_counter()-started)*1000
    for name,value in [('native-search.json',result),('native-read.json',documents),
                       ('native-timing.json',{'build_ms':build_ms,'read_ms':read_ms,'search_ms':result['elapsed_ms']})]:
        with (args.output/name).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2)
    print(json.dumps({'ok':True,'component':'surd_search.SearchIndex','documents_read':len(documents)}))


if __name__=='__main__':main()
