"""Summarize checked Weave feedback without reading source contents."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def summarize(path):
    path=Path(path)
    if path.stat().st_size>16*1024*1024:raise ValueError('Feedback exceeds 16 MiB summary bound')
    totals=Counter();failures=Counter();blockers=Counter();kinds=Counter();requests=set();reports=set()
    with path.open(encoding='utf-8') as f:
        for line in f:
            if not line.strip():continue
            try:
                row=json.loads(line)
                if not isinstance(row,dict) or row.get('version')!='weave.feedback.v1' or type(row.get('passed')) is not bool:raise ValueError('Row contract')
                stage=row.get('stage','results')
                if stage not in ('preflight','results'):raise ValueError('Stage contract')
                digest=row['report_sha256']
                if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('Report hash')
                codes=row['issue_codes']
                if not isinstance(codes,list) or any(not isinstance(c,str) or not re.fullmatch('[A-Z_]+',c) for c in codes):raise ValueError('Issue codes')
                fk=row.get('failure_kinds',[])
                if not isinstance(fk,list) or any(not isinstance(x,str) or not re.fullmatch('[a-z_]+',x) for x in fk):raise ValueError('Failure kinds')
                if digest in reports:totals['duplicate_reports']+=1;continue
                reports.add(digest);totals['valid_rows']+=1
                key=stage+('_passed' if row['passed'] else '_failed');totals[key]+=1
                req=row.get('request_sha256')
                if isinstance(req,str) and re.fullmatch('[0-9a-f]{64}',req):requests.add(req)
                if not row['passed']:
                    (blockers if stage=='preflight' else failures).update(set(codes))
                    if stage=='results':kinds.update(set(fk))
            except (ValueError,KeyError,TypeError):totals['invalid_rows']+=1
    candidates=[{'kind':kind,'checked_reports':count,'status':'candidate','root_cause':'UNASSIGNED',
                 'instruction':'Review checked '+kind+' failures against their receipts before retaining training examples.'} for kind,count in sorted(kinds.items())]
    return {'version':'weave.feedback.summary.v1','counts':dict(totals),'unique_requests':len(requests),
            'preflight_blockers':dict(sorted(blockers.items())),'result_failures':dict(sorted(failures.items())),
            'training_candidates':candidates,'active_training_started':False,
            'scope':'Deduplicated recorded outcomes; model attribution and training adoption require their own checks.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('memory',type=Path);parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    try:
        result=summarize(args.memory)
        if args.out:
            with args.out.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
        else:print(json.dumps(result,indent=2))
    except (ValueError,OSError) as exc:parser.exit(2,str(exc)+'\n')


if __name__=='__main__':main()
