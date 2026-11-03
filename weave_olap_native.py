"""Call the installed OLAP Library API against an isolated synthetic catalog."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('runtime',type=Path)
    parser.add_argument('program',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args()
    p=args.output;program=json.loads(args.program.read_text())
    library_root=p/'library';(library_root/'objects').mkdir(parents=True)
    run=library_root/'runs/synthetic';run.mkdir(parents=True)
    database=library_root/'objects/pending.sqlite';con=sqlite3.connect(database)
    con.execute('CREATE TABLE entries (entry_id TEXT PRIMARY KEY, bucket TEXT, amount_units INTEGER, source_id TEXT, origin_id TEXT)')
    con.executemany('INSERT INTO entries VALUES (?,?,?,?,?)',[(r['entry_id'],r['bucket'],r['amount_units'],r['source_id'],r['origin_id']) for r in program['records']])
    con.commit();con.close();sha=hashlib.sha256(database.read_bytes()).hexdigest()
    snapshot=database.with_name(sha+'.sqlite');database.rename(snapshot);snapshot.chmod(0o444)
    entry={'cube_id':'weave_synthetic','selected_sha256':sha,'current_path':str(snapshot.resolve()),
           'selected_source_host':'synthetic','selected_source_path':'synthetic:program.json'}
    (run/'catalog.json').write_text(json.dumps({'cubes':[entry]}));(library_root/'ACTIVE_RUN').symlink_to(run.resolve(),target_is_directory=True)
    spec=importlib.util.spec_from_file_location('weave_native_olap',args.runtime)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    library=module.Library(library_root)
    # Keep the installed global two-slot guard; only the catalog is task-local.
    guard=module.Library();library.child=guard.child
    schema=library.olap_schema('weave_synthetic',table='entries')
    rows=library.olap_query('weave_synthetic','SELECT entry_id, bucket, amount_units, source_id, origin_id FROM entries ORDER BY entry_id',
                            max_rows=128,expected_sha256=sha)
    measures=[{'op':op,'column':'*' if op=='count' else 'amount_units','alias':alias} for op,alias in [('count','row_count'),('sum','amount_sum'),('min','amount_min'),('max','amount_max')]]
    result=library.olap_rollup('weave_synthetic','entries',dimensions=program['dimensions'],measures=measures,
                              filters=program['filters'],max_rows=program['max_rows'],version_sha256=sha)
    for name,value in [('native-schema.json',schema),('native-source-rows.json',rows),('native-rollup.json',result),
                       ('native-snapshot.json',{'path':str(snapshot.relative_to(p)),'sha256':sha,'shared_guard_root':str(guard.root),'runtime_version':module.VERSION})]:
        with (p/name).open('x') as stream:json.dump(value,stream,indent=2)
    print(json.dumps({'status':result.get('status'),'truncated':result.get('truncated')}))


if __name__=='__main__':main()
