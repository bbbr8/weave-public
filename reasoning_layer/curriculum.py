"""Export reviewed development candidates; never starts or alters a training job."""
from .contracts import digest
from .core import validate_program
from .source_audit import audit_source

def qualify(task,program,result,approval,expected):
    if task.get('exposure')!='development':raise ValueError('Curriculum requires explicitly exposed development data, not a sealed test')
    check=validate_program(task,program)
    if not check['valid']:raise ValueError('Program validation failed')
    if result.get('review_status')!='accepted_by_model':raise ValueError('A recorded semantic review is required')
    if result.get('execution',{}).get('native') is not True:raise ValueError('A native execution receipt is required for curriculum qualification')
    if result.get('answer')!=expected:raise ValueError('Candidate does not match its development target')
    if result.get('program_digest')!=digest(program):raise ValueError('Result belongs to a different program')
    if not approval.get('reviewer') or approval.get('status')!='approved' or not all(approval.get(k) is True for k in ['source_fidelity','query_preserved','label_policy_reviewed']):raise ValueError('Explicit source/query/policy reviewer signoff is required; final-label match alone is insufficient')
    if 'source_ledger' in program:
        audit=result.get('source_audit') or {}
        if not audit.get('source_review') or not audit_source(task,program,audit['source_review'])['valid'] or audit.get('program_digest')!=digest(program) or audit.get('context_sha256')!=task['context_sha256'] or audit.get('question_sha256')!=task['question_sha256'] or audit.get('valid') is not True or audit.get('semantic_review_recorded') is not True:
            raise ValueError('Audited candidates require a matching whole-source review record')
    return dict(task=task,program=program,target=expected,source_digest=digest(task),program_digest=digest(program),qualification=approval,provenance='reviewed development candidate; model program and actual execution retained',training_status='exported_candidate_only')
