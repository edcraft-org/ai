"""Code-domain boundary examples for property checking."""

import json

from edcraft_validator.domains.code.code_schemas import CodeTemplateCandidate


def boundary_examples(candidate: CodeTemplateCandidate) -> list[dict]:
    """A few axis boundaries, not a Cartesian product or a coverage claim."""
    ordered = {}
    for p in candidate.parameters:
        values = p.values
        if p.kind in {"integer", "boolean"}:
            values = sorted(values)
        elif p.kind == "integer_list":
            values = sorted(values, key=lambda x: (len(x), x))
        ordered[p.name] = values

    base = {name: values[0] for name, values in ordered.items()}
    examples = [base, {name: values[-1] for name, values in ordered.items()}]

    for p in candidate.parameters:
        examples.append(base | {p.name: ordered[p.name][-1]})
        if p.kind == "integer" and 0 in p.values:
            examples.append(base | {p.name: 0})
    unique = {json.dumps(x, sort_keys=True): x for x in examples}

    return list(unique.values())
