"""Persistent source-linked full-text search. Standard library, SQLite FTS5.

Search results are evidence candidates, not inferred facts or answer confidence.
Metadata filters constrain the ranked query before its result limit. Expansion
uses only query text and retrieved parents, never expected answers or gold labels.
"""
import argparse
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

STOP=set('a an the of to in on at by for with as and or is are was were be been this that these those from than which who what when where how do does did can could would should have has had'.split())


def canonical(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)
def sha(x):return hashlib.sha256(x.encode()).hexdigest()


def source_json(text):
    def unique(pairs):
        obj={}
        for key,value in pairs:
            if key in obj:raise ValueError('duplicate JSON key: '+key)
            obj[key]=value
        return obj
    def invalid(value):raise ValueError('nonfinite JSON value: '+value)
    return json.loads(text,object_pairs_hook=unique,parse_constant=invalid)


def terms(query):
    if not isinstance(query,str) or len(query)>8192:raise ValueError('query must be text, at most 8192 characters')
    words=list(dict.fromkeys(re.findall(r'[^\W_]+(?:[-.][^\W_]+)*',query.casefold())))
    words=[w for w in words if w not in STOP] or words
    if len(words)>64:raise ValueError('query exceeds 64 distinct terms')
    return words


def match_query(query):return ' OR '.join('"'+w.replace('"','""')+'"' for w in terms(query))


class EvidenceIndex:
    def __init__(self,path,create=False):
        self.path=Path(path).resolve()
        if create:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.db=sqlite3.connect(self.path)
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS records(id TEXT UNIQUE NOT NULL,parent_id TEXT NOT NULL,
                    text TEXT NOT NULL,locator TEXT NOT NULL,metadata TEXT NOT NULL,
                    text_sha256 TEXT NOT NULL,record_sha256 TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS records_parent ON records(parent_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(id UNINDEXED,text,tokenize='porter unicode61');
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
                INSERT OR IGNORE INTO state VALUES('revision',0);
                CREATE TRIGGER IF NOT EXISTS insert_fts AFTER INSERT ON records BEGIN
                    INSERT INTO evidence_fts(rowid,id,text) VALUES(new.rowid,new.id,new.text); END;
                CREATE TRIGGER IF NOT EXISTS delete_fts AFTER DELETE ON records BEGIN
                    DELETE FROM evidence_fts WHERE rowid=old.rowid; END;
                CREATE TRIGGER IF NOT EXISTS update_fts AFTER UPDATE ON records BEGIN
                    DELETE FROM evidence_fts WHERE rowid=old.rowid;
                    INSERT INTO evidence_fts(rowid,id,text) VALUES(new.rowid,new.id,new.text); END;
            ''')
        else:
            self.db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
        self.db.row_factory=sqlite3.Row

    def close(self):self.db.close()

    def stats(self):
        return dict(records=self.db.execute('SELECT count(*) FROM records').fetchone()[0],
                    parents=self.db.execute('SELECT count(DISTINCT parent_id) FROM records').fetchone()[0],
                    revision=self.db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0])

    def ingest(self,rows,replace_files=None):
        counts=dict(inserted=0,updated=0,unchanged=0,removed=0);seen={};by_file={p:set() for p in replace_files or []}
        with self.db:
            for row in rows:
                if not isinstance(row,dict):raise ValueError('each record must be an object')
                ident=row.get('id');text=row.get('text');locator=row.get('locator')
                if not all(isinstance(v,str) and v.strip() for v in [ident,text,locator]):raise ValueError('record needs nonempty id, text and locator')
                if len(text.encode())>1024*1024:raise ValueError('record exceeds one MiB; split with source offsets')
                parent=row.get('parent_id',ident);meta=row.get('metadata',{})
                if not isinstance(parent,str) or not parent or not isinstance(meta,dict):raise ValueError('parent_id must be text; metadata must be object')
                if any(not isinstance(k,str) for k in meta):raise ValueError('metadata keys must be text')
                deps=meta.get('depends_on',[])
                if not isinstance(deps,list) or any(not isinstance(x,str) or not x for x in deps):raise ValueError('depends_on must be a list of record ids')
                packed=canonical(dict(id=ident,parent_id=parent,text=text,locator=locator,metadata=meta))
                digest=sha(packed)
                if ident in seen and seen[ident]!=digest:raise ValueError('conflicting duplicate id within import: '+ident)
                seen[ident]=digest
                if meta.get('_index_input') in by_file:by_file[meta['_index_input']].add(ident)
                old=self.db.execute('SELECT record_sha256 FROM records WHERE id=?',(ident,)).fetchone()
                if old and old[0]==digest:counts['unchanged']+=1;continue
                self.db.execute('''INSERT INTO records VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id,text=excluded.text,
                    locator=excluded.locator,metadata=excluded.metadata,text_sha256=excluded.text_sha256,
                    record_sha256=excluded.record_sha256''',(ident,parent,text,locator,canonical(meta),sha(text),digest))
                counts['updated' if old else 'inserted']+=1
            for path,retained in by_file.items():
                old_ids=self.db.execute("SELECT id FROM records WHERE json_extract(metadata,'$._index_input')=?",(path,)).fetchall()
                for row in old_ids:
                    if row[0] not in retained:counts['removed']+=self.db.execute('DELETE FROM records WHERE id=?',(row[0],)).rowcount
            if counts['inserted']+counts['updated']+counts['removed']:
                self.db.execute("UPDATE state SET value=value+1 WHERE key='revision'")
        return dict(counts,**self.stats())

    def index_files(self,paths):
        files=[]
        for supplied in paths:
            path=Path(supplied).expanduser().resolve()
            if not path.exists():raise ValueError('input does not exist: '+str(path))
            files.extend(p for p in (sorted(path.rglob('*')) if path.is_dir() else [path])
                         if p.is_file() and p.suffix.lower() in ['.jsonl','.ndjson','.json','.csv','.txt','.md'])
        files=list(dict.fromkeys(files))
        def records():
            for path in files:
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                for row in file_records([str(path)]):
                    row=dict(row);row['metadata']=dict(row.get('metadata',{}),_index_input=str(path),_import_sha256=digest)
                    yield row
        return self.ingest(records(),replace_files=[str(p) for p in files])

    def remove(self,ids):
        removed=0
        with self.db:
            for ident in ids:removed+=self.db.execute('DELETE FROM records WHERE id=?',(ident,)).rowcount
            if removed:self.db.execute("UPDATE state SET value=value+1 WHERE key='revision'")
        return dict(removed=removed,**self.stats())

    def filters(self,where=None,before=None):
        clauses=[];args=[]
        for field,values in (where or {}).items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',field):raise ValueError('invalid metadata key')
            values=values if isinstance(values,list) else [values]
            if not values or any(type(v) not in [str,int,float,bool] for v in values):raise ValueError('filters need nonempty scalar values')
            col='r.parent_id' if field=='parent_id' else 'json_extract(r.metadata, ?)'
            if field!='parent_id':args.append('$.'+field)
            clauses.append(col+' IN ('+','.join('?' for _ in values)+')');args.extend(values)
        for field,value in (before or {}).items():
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',field):raise ValueError('invalid before metadata key')
            # ISO dates sort correctly; missing values do not satisfy the filter.
            if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('before values need ISO dates')
            date.fromisoformat(value)
            clauses.append('json_extract(r.metadata, ?) <= ?');args.extend(['$.'+field,value])
        return clauses,args

    def result(self,row,query=''):
        r=dict(row);r['metadata']=json.loads(r['metadata']);r.pop('rowid',None)
        txt=r['text'];positions=[]
        for w in terms(query):
            m=re.search(re.escape(w),txt,re.I)
            if m:positions.append(m.start())
        start=max(0,min(positions,default=0)-70);end=min(len(txt),start+450)
        r['snippet']=dict(start=start,end=end,text=txt[start:end])
        return r

    def search(self,query,k=10,where=None,before=None):
        if type(k) is not int or not 1<=k<=1000:raise ValueError('k must be 1..1000')
        q=match_query(query);clauses,args=self.filters(where,before)
        scope=' AND '.join(clauses) or '1'
        scoped=self.db.execute('SELECT count(*) FROM records r WHERE '+scope,args).fetchone()[0]
        hits=[];truncated=False
        if q and scoped:
            rows=self.db.execute('''SELECT r.*,bm25(evidence_fts) AS lexical_score FROM evidence_fts
                JOIN records r ON r.rowid=evidence_fts.rowid WHERE evidence_fts MATCH ? AND '''+scope+
                ' ORDER BY lexical_score,r.id LIMIT ?',[q]+args+[k+1]).fetchall()
            truncated=len(rows)>k;hits=[self.result(r,query) for r in rows[:k]]
        return dict(query=query,status='results' if hits else 'empty_scope' if not scoped else 'empty_query' if not q else 'no_match',
                    hits=hits,scoped_records=scoped,result_limit_reached=truncated,
                    index_revision=self.db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0],filters=dict(where=where or {},before=before or {}))

    def expand(self,query,max_records=64,max_chars=64000,parents=2,where=None,before=None,max_depth=3):
        if type(max_records) is not int or not 1<=max_records<=1000:raise ValueError('max_records must be 1..1000')
        if type(max_chars) is not int or not 1<=max_chars<=2000000:raise ValueError('max_chars must be 1..2000000')
        if type(parents) is not int or not 1<=parents<=10:raise ValueError('parents must be 1..10')
        if type(max_depth) is not int or not 0<=max_depth<=10:raise ValueError('max_depth must be 0..10')
        seed=self.search(query,min(10,max_records),where,before);chosen=[];seen=set();chars=0;blocked=0;trace=[]
        def admit(hit,stage):
            nonlocal chars,blocked
            if hit['id'] in seen:return
            if len(chosen)>=max_records or chars+len(hit['text'])>max_chars:blocked+=1;return
            hit=dict(hit,retrieval_stage=stage);chosen.append(hit);seen.add(hit['id']);chars+=len(hit['text'])
        scores={}
        for i,hit in enumerate(seed['hits']):
            admit(hit,'seed');scores[hit['parent_id']]=scores.get(hit['parent_id'],0)+1/(i+2)
        selected=sorted(scores,key=lambda p:(-scores[p],p))[:parents]
        trace.append(dict(stage='seed',query=query,returned=len(seed['hits']),selected_parents=selected))
        followups=[];lower=query.casefold()
        if re.search(r'percent|ratio|share|proportion',lower):followups.append('total')
        if re.search(r'change|increase|decrease|balance',lower):followups.append('balance beginning ending previous')
        for parent in selected:
            scoped=dict(where or {},parent_id=parent)
            for followup in followups:
                found=self.search(followup,12,scoped,before)
                trace.append(dict(stage='followup',parent_id=parent,query=followup,returned=len(found['hits'])))
                for hit in found['hits']:admit(hit,'followup')
        queues=[]
        for parent in selected:
            clauses,args=self.filters(dict(where or {},parent_id=parent),before)
            rs=self.db.execute('SELECT r.* FROM records r WHERE '+' AND '.join(clauses)+
                " ORDER BY coalesce(json_extract(r.metadata,'$.order'),0),r.id LIMIT 1001",args).fetchall()
            if len(rs)>1000:blocked+=len(rs)-1000
            queues.append([self.result(row,query) for row in rs[:1000]])
        for i in range(max(map(len,queues),default=0)):
            for queue in queues:
                if i<len(queue):admit(queue[i],'parent_context')
        trace.append(dict(stage='parent_context',parents=selected,context_candidates=sum(map(len,queues))))
        unresolved=[];visited=set();front=[(h,0) for h in list(chosen)]
        while front:
            hit,depth=front.pop(0)
            if hit['id'] in visited:continue
            visited.add(hit['id'])
            for ident in hit['metadata'].get('depends_on',[]):
                if ident in seen:continue
                issue=dict(from_id=hit['id'],required_id=ident)
                if depth>=max_depth:unresolved.append(dict(issue,reason='depth_limit'));continue
                clauses,args=self.filters(where,before)
                raw=self.db.execute('SELECT r.* FROM records r WHERE r.id=?'+(' AND '+' AND '.join(clauses) if clauses else ''),[ident]+args).fetchone()
                if raw is None:
                    exists=self.db.execute('SELECT 1 FROM records WHERE id=?',(ident,)).fetchone()
                    unresolved.append(dict(issue,reason='excluded_by_scope' if exists else 'missing_from_index'));continue
                candidate=self.result(raw,query);admit(candidate,'declared_dependency')
                if ident in seen:front.append((candidate,depth+1))
                else:unresolved.append(dict(issue,reason='budget_limit'))
        unresolved=[u for u in unresolved if u['required_id'] not in seen]
        trace.append(dict(stage='declared_dependencies',max_depth=max_depth,visited=len(visited),unresolved=unresolved))
        return dict(query=query,hits=chosen,status='results' if chosen else seed['status'],
                    index_revision=seed['index_revision'],trace=trace,unresolved_dependencies=unresolved,budget=dict(max_records=max_records,max_chars=max_chars,
                    used_records=len(chosen),used_chars=chars,limit_reached=blocked>0),filters=seed['filters'])

    def validate_citation(self,citation):
        row=self.db.execute('SELECT record_sha256,text_sha256 FROM records WHERE id=?',(citation.get('id'),)).fetchone()
        if not row:return dict(valid=False,reason='record_missing')
        if row['record_sha256']!=citation.get('record_sha256'):return dict(valid=False,reason='record_changed')
        return dict(valid=True,reason='matches_current_index_record')


def file_records(paths):
    for supplied in paths:
        root=Path(supplied).expanduser().resolve()
        files=sorted(root.rglob('*')) if root.is_dir() else [root]
        for path in files:
            if not path.is_file() or path.suffix.lower() not in ['.jsonl','.ndjson','.json','.csv','.txt','.md']:continue
            ext=path.suffix.lower()
            if ext in ['.jsonl','.ndjson']:
                with path.open(encoding='utf-8-sig') as f:
                    for line in f:
                        if line.strip():yield source_json(line)
            elif ext=='.json':
                obj=source_json(path.read_text(encoding='utf-8-sig'));rows=obj if isinstance(obj,list) else obj.get('records')
                if not isinstance(rows,list):raise ValueError('JSON file needs records array')
                yield from rows
            elif ext=='.csv':
                with path.open(encoding='utf-8-sig',newline='') as f:
                    reader=csv.DictReader(f)
                    if not reader.fieldnames or any(not h.strip() for h in reader.fieldnames) or len(reader.fieldnames)!=len(set(reader.fieldnames)):
                        raise ValueError('CSV needs nonempty unique field names')
                    for i,row in enumerate(reader,2):
                        if None in row or any(v is None for v in row.values()):raise ValueError('CSV row does not match header width')
                        yield dict(id=sha(str(path))+':'+str(i),parent_id=str(path),locator=str(path)+':'+str(i),
                                   text='; '.join(k+': '+str(v) for k,v in row.items()),metadata=dict(source_file=str(path),line=i,order=i))
            else:
                with path.open(encoding='utf-8-sig',newline='') as f:text=f.read()
                source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
                for start in range(0,len(text),1600):
                    chunk=text[start:start+1800]
                    if chunk.strip():yield dict(id=sha(str(path))+':'+str(start),parent_id=str(path),text=chunk,
                        locator=str(path)+'#chars='+str(start)+':'+str(start+len(chunk)),
                        metadata=dict(source_file=str(path),source_sha256=source_hash,start=start,end=start+len(chunk),order=start))


def parse_filters(values):
    out={}
    for value in values:
        key,sep,val=value.partition('=')
        if not sep:raise ValueError('filter must be key=value')
        out[key]=val
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True);sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('index');b.add_argument('--input',action='append',required=True)
    sub.add_parser('stats')
    d=sub.add_parser('remove');d.add_argument('--id',action='append',required=True)
    for name in ['search','expand']:
        q=sub.add_parser(name);q.add_argument('query');q.add_argument('--where',action='append',default=[]);q.add_argument('--before',action='append',default=[])
        if name=='search':q.add_argument('--k',type=int,default=10)
        else:q.add_argument('--max-records',type=int,default=64);q.add_argument('--max-chars',type=int,default=64000);q.add_argument('--parents',type=int,default=2);q.add_argument('--max-depth',type=int,default=3)
    a=p.parse_args();ix=EvidenceIndex(a.db,create=a.command in ['index','remove'])
    try:
        if a.command=='index':result=ix.index_files(a.input)
        elif a.command=='stats':result=ix.stats()
        elif a.command=='remove':result=ix.remove(a.id)
        elif a.command=='search':result=ix.search(a.query,a.k,parse_filters(a.where),parse_filters(a.before))
        else:result=ix.expand(a.query,a.max_records,a.max_chars,a.parents,parse_filters(a.where),parse_filters(a.before),a.max_depth)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:ix.close()


if __name__=='__main__':main()
