"""Portable contracts. Task policies belong to callers, never to program writers."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

STATES = ("supported", "refuted", "undetermined", "inconsistent")
ABSTAIN = "ABSTAIN"

def digest(value):
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def runtime_recipe():
    """Bind reusable run artifacts to exact package source, not a label."""
    return digest({p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(Path(__file__).parent.glob('*.py'))})

def signature(text):
    """Conservative lexical features, not a general semantic parser."""
    lower = text.lower()
    modality = "required" if re.search(r"\b(must|required|obliged|mandatory)\b", lower) else "permitted" if re.search(r"\b(may|allowed|permitted|can)\b", lower) else "factual"
    quantifier = "all" if re.search(r"\b(all|every|each)\b", lower) else "some" if re.search(r"\b(some|at least one|any)\b", lower) else "unspecified"
    polarity = "negative" if re.search(r"\b(not|never|lacks|neither)\b", lower) else "positive"
    return dict(modality=modality, quantifier=quantifier, polarity=polarity)

def policy_for(labels, *, negative_semantics="refutation"):
    labels = list(labels)
    if set(labels) == {"True", "False", "Unknown"}:
        return dict(mode="truth", supported="True", refuted="False", undetermined="Unknown", inconsistent=ABSTAIN, negative_semantics="refutation", basis="Caller-declared open-world three-way inference")
    if set(labels) == {"Entailment", "Contradiction", "NotMentioned"}:
        return dict(mode="truth", supported="Entailment", refuted="Contradiction", undetermined="NotMentioned", inconsistent=ABSTAIN, negative_semantics="refutation", basis="Caller-declared three-way contract inference")
    if set(labels) == {"Entailment", "Contradiction"}:
        return dict(mode="truth", supported="Entailment", refuted="Contradiction", undetermined="Contradiction" if negative_semantics == "non_entailment" else ABSTAIN, inconsistent=ABSTAIN, negative_semantics=negative_semantics, basis="Caller explicitly declares binary task semantics: " + negative_semantics)
    if set(labels) in ({"yes", "no"}, {"Yes", "No"}):
        positive = "yes" if "yes" in labels else "Yes"
        negative = "no" if "no" in labels else "No"
        return dict(mode="truth", supported=positive, refuted=negative, undetermined=ABSTAIN, inconsistent=ABSTAIN, negative_semantics="refutation", basis="Binary decision: absent support remains abstention")
    return dict(mode="choice", unresolved=ABSTAIN, conflicting=ABSTAIN, negative_semantics="not_applicable", basis="Exactly one declared choice goal must be derived")

def make_task(ident, context, question, labels, *, policy=None, data_class="public", operation="rules"):
    return dict(id=ident, context=context, question=question, question_sha256=digest(question), context_sha256=digest(context), labels=list(labels), policy=policy or policy_for(labels), query_signature=signature(question), signature_origin="lexical_or_caller_annotation", data_class=data_class, operation=operation)

def validate_task(task):
    errors = []
    for key in ["id", "context", "question", "question_sha256", "context_sha256", "labels", "policy", "query_signature", "data_class", "operation"]:
        if key not in task: errors.append("missing task field: " + key)
    if errors: return errors
    if not isinstance(task["question"], str) or not isinstance(task["context"], str): return ["question and context must be strings"]
    if task["question_sha256"] != digest(task["question"]): errors.append("question hash differs")
    if task["context_sha256"] != digest(task["context"]): errors.append("context hash differs")
    labels = task["labels"]
    if not isinstance(labels, list) or any(not isinstance(x, str) for x in labels) or len(labels) != len(set(labels)): return errors+["invalid task labels"]
    p = task["policy"]
    if not isinstance(p, dict): return errors + ["policy must be an object"]
    if not isinstance(p.get('basis'),str) or not p['basis']:errors.append('policy requires an explicit semantic basis')
    sig=task['query_signature']
    if not isinstance(sig,dict) or set(sig)!={'modality','quantifier','polarity'} or sig.get('modality') not in ['factual','permitted','required'] or sig.get('quantifier') not in ['all','some','unspecified'] or sig.get('polarity') not in ['positive','negative']:errors.append('invalid query signature')
    if p.get("mode") == "truth":
        for state in STATES:
            if state not in p: errors.append("policy omits state: " + state)
            elif p[state] not in labels + [ABSTAIN]: errors.append("policy emits unsupported label: " + state)
        if p.get("undetermined") == p.get("refuted") and p.get("negative_semantics") != "non_entailment": errors.append("undetermined conflated with refuted without explicit non-entailment task semantics")
        if p.get('supported')==p.get('refuted'):errors.append('support and refutation must have distinct labels')
        if p.get('undetermined')==p.get('supported'):errors.append('undetermined cannot be mapped to positive support')
        if p.get('inconsistent') in [p.get('supported'),p.get('refuted')]:errors.append('inconsistent support cannot silently choose one side')
        covered = {p.get(s) for s in STATES}
        if not set(labels) <= covered: errors.append("policy has unreachable task labels")
    elif p.get("mode") == "choice":
        if p.get("unresolved") != ABSTAIN or p.get("conflicting") != ABSTAIN: errors.append("choice policy must explicitly abstain on unresolved/conflicting results")
    elif p.get("mode") == "numeric":
        if p.get("unit") not in ["number", "money"]: errors.append("numeric policy unit must be number or money")
    else: errors.append("unknown policy mode")
    if task["data_class"] not in ["public", "synthetic", "case_private"]: errors.append("unknown data class")
    if task["operation"] not in ["rules", "arithmetic", "direct", "auto"]: errors.append("unknown operation")
    return errors

def route(task):
    """Observable task features only; no answer labels, keys or outcome oracle."""
    requested = task["operation"]
    if requested != "auto": return dict(operation=requested, basis="explicit caller operation")
    if task["policy"]["mode"] == "numeric": return dict(operation="arithmetic", basis="caller declares numeric output")
    if re.search(r"\b(if|then|rule|must|may|constraint)\b", task["context"], re.I): return dict(operation="rules", basis="visible rules or constraints in source")
    return dict(operation="direct", basis="source interpretation without declared computational structure")

