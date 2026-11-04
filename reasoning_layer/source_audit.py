"""Whole-source accounting and execution traces; semantic judgments stay explicit.

Units are positional text spans, not a linguistic parser. A valid ledger means
every supplied span has a disposition and checked references. It never certifies
that a model's interpretation or irrelevance judgment is correct.
"""
from __future__ import annotations

import ast
import re
from .contracts import digest
from .core import closure

FACETS = ('actors', 'predicate', 'modality', 'quantifiers', 'polarity', 'time_scope', 'exceptions_conditions')
CUES = {
    'exception': r'\b(?:except|unless|notwithstanding|however|subject to|provided that)\b',
    'condition': r'\b(?:if|only if|when|until|provided|condition)\b',
    'time': r'\b(?:before|after|effective|expires|during|prior|subsequent)\b|\b\d{4}-\d{2}-\d{2}\b',
    'negation': r'\b(?:not|never|neither|prohibited|without)\b',
    'modality': r'\b(?:may|must|shall|permitted|required)\b',
    'money': r'\$\s*\d|\b(?:credit|payment|paid|refund|balance)\b',
}


def source_units(task, max_chars=1000):
    """Partition all non-whitespace text, preserving exact character offsets."""
    if not isinstance(max_chars, int) or max_chars < 40:
        raise ValueError('max_chars must be an integer >= 40')
    context = task['context']
    boundaries = [0] + [m.end() for m in re.finditer(r'\n+|(?<=[.!?;])\s+', context)] + [len(context)]
    units = []
    for lo, hi in zip(boundaries, boundaries[1:]):
        while lo < hi:
            while lo < hi and context[lo].isspace():
                lo += 1
            if lo == hi:
                break
            end = min(hi, lo + max_chars)
            if end < hi:
                split = context.rfind(' ', lo, end)
                if split > lo:
                    end = split
            stop = end
            while stop > lo and context[stop - 1].isspace():
                stop -= 1
            if stop > lo:
                text = context[lo:stop]
                unit_id = 'u-' + digest([task['context_sha256'], lo, stop])[:20]
                units.append(dict(id=unit_id, start=lo, end=stop, text=text,
                                  source_sha256=task['context_sha256'],
                                  cues=[name for name, pattern in CUES.items() if re.search(pattern, text, re.I)]))
            lo = end
    return units


def _quoted_units(quote, context, units):
    """All occurrences count; repeated identical quotations are ambiguous."""
    if not isinstance(quote, str) or not quote:
        return set()
    hits = set()
    start = 0
    while True:
        start = context.find(quote, start)
        if start < 0:
            return hits
        end = start + len(quote)
        hits.update(u['id'] for u in units if u['start'] < end and start < u['end'])
        start += 1


def targets_for(program):
    targets = {'node:' + n['id']: n for n in program.get('nodes', [])}
    targets.update({'rule:' + str(i): r for i, r in enumerate(program.get('rules', []))})
    calc = program.get('calculation')
    if calc:
        targets.update({'operand:' + o['name']: o for o in calc.get('operands', [])})
        targets['calculation:formula'] = calc
    return targets


def audit_source(task, program, review=None):
    units = source_units(task)
    by_id = {u['id']: u for u in units}
    errors, warnings = [], []
    ledger = program.get('source_ledger')
    result = dict(context_sha256=task['context_sha256'], question_sha256=task['question_sha256'],
                  program_digest=digest(program), units=units, ledger=ledger, source_review=review,
                  interpretation='Model judgments; structural coverage is not semantic certification')
    def error(code, detail):
        errors.append(dict(code=code, detail=detail))
    if ledger is None:
        error('source_ledger_missing', 'Every source unit needs a represented, irrelevant or unresolved disposition')
        result.update(valid=False, status='legacy_untracked', diagnostics=errors, warnings=warnings)
        return result
    targets = targets_for(program)
    seen, linked = set(), set()
    if not isinstance(ledger, list):
        error('source_ledger_shape', 'source_ledger must be a list')
        ledger = []
    for row in ledger:
        if not isinstance(row, dict) or set(row) != {'unit_id', 'disposition', 'reason', 'targets'}:
            error('source_ledger_shape', 'Each row requires unit_id, disposition, reason and targets')
            continue
        uid = row['unit_id']
        if not isinstance(uid, str) or uid not in by_id or uid in seen:
            error('source_unit_identity', str(uid))
            continue
        seen.add(uid)
        if row['disposition'] not in ['represented', 'irrelevant', 'unresolved']:
            error('source_disposition', uid)
        if not isinstance(row['reason'], str) or not row['reason'].strip():
            error('source_reason_missing', uid)
        refs = row['targets']
        if not isinstance(refs, list) or any(not isinstance(x, str) for x in refs):
            error('source_targets_shape', uid)
            continue
        if len(refs) != len(set(refs)) or any(x not in targets for x in refs):
            error('source_target_unknown_or_duplicate', uid)
            continue
        if row['disposition'] == 'represented' and not refs:
            error('represented_without_target', uid)
        if row['disposition'] != 'represented' and refs:
            error('unused_source_has_targets', uid)
        if row['disposition'] == 'unresolved':
            error('source_interpretation_unresolved', uid)
        if row['disposition'] == 'irrelevant' and by_id[uid]['cues']:
            warnings.append(dict(code='risk_cue_marked_irrelevant', unit_id=uid,
                                 cues=by_id[uid]['cues'], reason=row['reason']))
        for ref in refs:
            obj = targets[ref]
            quotes = obj.get('quotes', []) if ref.startswith('node:') else [obj] if ref.startswith('operand:') else []
            if quotes and not any(uid in _quoted_units(q.get('quote'), task['context'], units) for q in quotes):
                error('source_target_span_mismatch', uid + ' -> ' + ref)
            else:
                linked.add(ref)
    missing = set(by_id) - seen
    if missing:
        error('source_units_unaccounted', ', '.join(sorted(missing)))
    for fact in program.get('facts', []):
        if 'node:' + fact not in linked:
            error('fact_unlinked_to_source_ledger', fact)
    for i, rule in enumerate(program.get('rules', [])):
        if 'rule:' + str(i) not in linked:
            if re.match(r'^External\b', rule.get('basis', ''), re.I):
                warnings.append(dict(code='external_rule', rule=i, basis=rule['basis']))
            else:
                error('rule_unlinked_to_source_ledger', str(i))
    for ref in targets:
        if (ref.startswith('operand:') or ref == 'calculation:formula') and ref not in linked:
            error('calculation_unlinked_to_source_ledger', ref)
    calc = program.get('calculation')
    if calc:
        used = {n.id for n in ast.walk(ast.parse(calc['formula'], mode='eval')) if isinstance(n, ast.Name)}
        for operand in calc['operands']:
            if operand['name'] not in used:
                warnings.append(dict(code='operand_unused_in_formula', operand=operand['name']))
    if review is not None:
        if not isinstance(review, dict) or set(review) != {'unit_reviews', 'query_checks'}:
            error('source_review_shape', 'Review requires unit_reviews and query_checks')
        else:
            reviewed = set()
            for row in review['unit_reviews'] if isinstance(review['unit_reviews'], list) else []:
                if not isinstance(row, dict) or set(row) != {'unit_id', 'agrees', 'reason'}:
                    error('unit_review_shape', 'Review row requires unit_id, agrees, reason')
                    continue
                uid = row['unit_id']
                if not isinstance(uid, str) or uid not in by_id or uid in reviewed:
                    error('unit_review_identity', str(uid))
                    continue
                reviewed.add(uid)
                if row['agrees'] is not True or not isinstance(row['reason'], str) or not row['reason'].strip():
                    error('unit_review_unresolved', uid)
            if reviewed != set(by_id):
                error('unit_reviews_incomplete', ', '.join(sorted(set(by_id) - reviewed)))
            facets = set()
            for row in review['query_checks'] if isinstance(review['query_checks'], list) else []:
                if not isinstance(row, dict) or set(row) != {'facet', 'preserved', 'reason'}:
                    error('query_check_shape', 'Query check requires facet, preserved, reason')
                    continue
                facet = row['facet']
                if not isinstance(facet, str) or facet not in FACETS or facet in facets:
                    error('query_check_identity', str(facet))
                    continue
                facets.add(facet)
                if row['preserved'] is not True or not isinstance(row['reason'], str) or not row['reason'].strip():
                    error('query_facet_unresolved', facet)
            if facets != set(FACETS):
                error('query_checks_incomplete', ', '.join(sorted(set(FACETS) - facets)))
    result.update(valid=not errors, status='ledger_checked' if not errors else 'source_review_required',
                  diagnostics=errors, warnings=warnings,
                  accounted_units=len(seen), total_units=len(units), linked_targets=sorted(linked),
                  semantic_review_recorded=review is not None)
    return result


def reasoning_trace(task, program):
    """Record actual derivations and their linked source units, including cycles."""
    links = {}
    for row in program.get('source_ledger', []) or []:
        if isinstance(row, dict) and row.get('disposition') == 'represented':
            for target in row.get('targets', []):
                links.setdefault(target, []).append(row['unit_id'])
    if program['operation'] == 'arithmetic':
        calc = program['calculation']
        used = sorted({n.id for n in ast.walk(ast.parse(calc['formula'], mode='eval')) if isinstance(n, ast.Name)})
        return dict(operation='arithmetic', formula=calc['formula'], used_operands=used,
                    operands=[dict(o, used=o['name'] in used, source_units=links.get('operand:' + o['name'], [])) for o in calc['operands']],
                    source_units=links.get('calculation:formula', []))
    known, witnesses = closure(program)
    # A DAG of references avoids exponential expansion when proofs share premises.
    steps = []
    for node in sorted(known):
        witness = witnesses[node]
        target = 'node:' + node if witness['kind'] == 'source_fact' else 'rule:' + str(witness['index'])
        steps.append(dict(node=node, **witness, source_units=links.get(target, [])))
    return dict(operation='rules', known=sorted(known), steps=steps,
                goals=[dict(g, reached=g['node'] in known, derivation_node=g['node']) for g in program['goals']])
