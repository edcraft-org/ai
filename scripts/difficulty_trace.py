"""Bounded AST interpreter for the issue 86 rubric audit; no eval/exec or SDK calls."""

import argparse
import ast
import copy
import hashlib
import json
import operator
from collections import Counter
from pathlib import Path


class Returned(Exception):
    def __init__(self, value):
        self.value = value


# Explicit target relevance exclusions, not algebraic or invariant shortcuts.
# Every excluded event is retained with its reason in the output.
EXCLUSIONS = {
    "conditionals-boolean-01": {
        ("return", 5): "Return value cannot affect the number of evaluated conditions."
    },
    "functions-single-helper-01": {
        ("return", 2): "Arithmetic return value cannot affect the number of calls.",
        (
            "return",
            5,
        ): "Returning the helper result adds no call; the helper call is retained.",
    },
    "lists-endpoint-swap-02": {
        ("assignment", 2): "first is used only by the irrelevant final-element write.",
        (
            "assignment",
            4,
        ): "Writing index 2 cannot affect the return using only indices 0 and 1.",
    },
    "cruxeval-356": {
        ("assignment", 7): "l is never read.",
        ("call", 7): "len is used only by the unused assignment to l.",
    },
    "loops-iteration-count-01": {
        ("assignment", 2): "Accumulator does not affect loop bounds or termination.",
        (
            "augmented_assignment",
            4,
        ): "Accumulator does not affect loop bounds or termination.",
        ("return", 5): "Returned sum does not affect the number of iterations.",
    },
    "loops-guarded-sweep-01": {
        ("return", 10): "Returned state does not affect the number of entered loops."
    },
}


class Trace:
    BINOPS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
    }
    CMPOPS = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
    }

    def __init__(self, question):
        self.question = question
        self.source = question["code"]
        tree = ast.parse(self.source)
        if not all(isinstance(n, ast.FunctionDef) for n in tree.body):
            raise ValueError("Only function definitions are supported")
        self.functions = {n.name: n for n in tree.body}
        self.events = []
        self.stack = []
        self.call_count = 0
        self.loop_invocations = 0
        self.loop_iterations = 0
        self.conditions = 0

    def event(self, kind, node, env, **extra):
        if len(self.events) >= 10000:
            raise ValueError("Event limit exceeded")
        reason = EXCLUSIONS.get(self.question["question_id"], {}).get(
            (kind, node.lineno)
        )
        self.events.append(
            {
                "event": len(self.events) + 1,
                "kind": kind,
                "line": node.lineno,
                "function": self.stack[-1],
                "depth": len(self.stack),
                "relevant": reason is None,
                "exclusion_reason": reason,
                "source": ast.get_source_segment(self.source, node),
                "locals": copy.deepcopy(env),
                **extra,
            }
        )

    def expression(self, node, env):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return env[node.id]
        if isinstance(node, ast.List):
            return [self.expression(n, env) for n in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self.expression(n, env) for n in node.elts)
        if isinstance(node, ast.BinOp):
            return self.BINOPS[type(node.op)](
                self.expression(node.left, env), self.expression(node.right, env)
            )
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -self.expression(node.operand, env)
        if isinstance(node, ast.BoolOp):
            result = self.expression(node.values[0], env)
            for value in node.values[1:]:
                if isinstance(node.op, ast.And) and not result:
                    return result
                if isinstance(node.op, ast.Or) and result:
                    return result
                result = self.expression(value, env)
            return result
        if isinstance(node, ast.Compare):
            left = self.expression(node.left, env)
            for op, right_node in zip(node.ops, node.comparators, strict=True):
                right = self.expression(right_node, env)
                if not self.CMPOPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Slice):
            return slice(
                *(
                    self.expression(n, env) if n is not None else None
                    for n in (node.lower, node.upper, node.step)
                )
            )
        if isinstance(node, ast.Subscript):
            return self.expression(node.value, env)[self.expression(node.slice, env)]
        if isinstance(node, ast.JoinedStr):
            return "".join(str(self.expression(n, env)) for n in node.values)
        if isinstance(node, ast.FormattedValue):
            if node.conversion != -1 or node.format_spec is not None:
                raise ValueError("Unsupported formatted value")
            return str(self.expression(node.value, env))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise ValueError(
                    "Only positional calls to named functions are supported"
                )
            name = node.func.id
            args = [self.expression(n, env) for n in node.args]
            self.event("call", node, env, called_function=name)
            self.call_count += 1
            if name == "len":
                return len(*args)
            if name == "range":
                result = range(*args)
                if len(result) > 10000:
                    raise ValueError("Range limit exceeded")
                return result
            return self.function(name, args)
        raise ValueError(f"Unsupported expression: {type(node).__name__}")

    def assign(self, target, value, env):
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            if len(target.elts) != len(value):
                raise ValueError("Unpacking mismatch")
            for t, v in zip(target.elts, value, strict=True):
                self.assign(t, v, env)
        elif isinstance(target, ast.Subscript):
            self.expression(target.value, env)[self.expression(target.slice, env)] = (
                value
            )
        else:
            raise ValueError("Unsupported assignment target")

    def statements(self, statements, env):
        for node in statements:
            if isinstance(node, ast.Assign):
                value = self.expression(node.value, env)
                for target in node.targets:
                    self.assign(target, value, env)
                self.event("assignment", node, env)
            elif isinstance(node, ast.AugAssign):
                value = self.BINOPS[type(node.op)](
                    self.expression(node.target, env), self.expression(node.value, env)
                )
                self.assign(node.target, value, env)
                self.event("augmented_assignment", node, env)
            elif isinstance(node, ast.If):
                condition = bool(self.expression(node.test, env))
                self.conditions += 1
                self.event("condition", node.test, env, result=condition)
                self.statements(node.body if condition else node.orelse, env)
            elif isinstance(node, ast.For):
                values = self.expression(node.iter, env)
                self.loop_invocations += 1
                if len(values) > 10000 or node.orelse:
                    raise ValueError("Unsupported loop")
                for value in values:
                    self.loop_iterations += 1
                    self.assign(node.target, value, env)
                    self.event("for_binding", node.target, env)
                    self.statements(node.body, env)
            elif isinstance(node, ast.Return):
                value = self.expression(node.value, env)
                self.event("return", node, env, result=copy.deepcopy(value))
                raise Returned(value)
            else:
                raise ValueError(f"Unsupported statement: {type(node).__name__}")

    def function(self, name, args):
        if len(self.stack) >= 100:
            raise ValueError("Call depth limit exceeded")
        function = self.functions[name]
        if len(function.args.args) != len(args):
            raise ValueError("Argument count mismatch")
        env = dict(zip((a.arg for a in function.args.args), args, strict=True))
        self.stack.append(name)
        try:
            self.statements(function.body, env)
        except Returned as result:
            return result.value
        finally:
            self.stack.pop()
        return None

    def run(self):
        name = self.question["entry_function"]
        self.call_count = 1  # The answer's function-call convention includes entry.
        inputs = copy.deepcopy(self.question["inputs"])
        value = self.function(
            name, [inputs[a.arg] for a in self.functions[name].args.args]
        )
        answer = {
            "return_value": value,
            "branch_executions": self.conditions,
            "function_calls": self.call_count,
            "loop_iterations": self.loop_iterations,
            "loop_executions": self.loop_invocations,
        }[self.question["answer_target"]]
        expected = next(
            o["value"]
            for o in self.question["options"]
            if o["id"] == self.question["correct_option"]
        )
        if type(answer) is not type(expected) or answer != expected:
            raise ValueError(
                f"Answer mismatch for {self.question['question_id']}: {answer!r}"
            )
        relevant = [e for e in self.events if e["relevant"]]
        return {
            "question_id": self.question["question_id"],
            "verified_answer": answer,
            "event_count": len(relevant),
            "full_event_count": len(self.events),
            "event_counts": dict(Counter(e["kind"] for e in relevant)),
            "execution_burden": "low"
            if len(relevant) <= 5
            else "moderate"
            if len(relevant) <= 20
            else "high",
            "events": self.events,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    dataset = json.loads(raw)
    records = [Trace(q).run() for q in dataset["questions"]]
    # Reconcile the prior worked examples and check every unit was retained.
    lookup = {r["question_id"]: r for r in records}
    expected_counts = {
        "arithmetic-coupled-arithmetic-01": 22,
        "lists-adjacent-differences-02": 12,
        "cruxeval-274": 23,
        "cruxeval-783": 18,
        "conditionals-boolean-01": 1,
    }
    for key, count in expected_counts.items():
        assert lookup[key]["event_count"] == count, (key, lookup[key]["event_count"])
    assert len(records) == 30
    for record in records:
        assert sum(record["event_counts"].values()) == record["event_count"]
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "trace-records.jsonl").open("x") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    (args.output / "dataset-snapshot.json").write_bytes(raw)
    print("dataset_sha256", hashlib.sha256(raw).hexdigest())
    for record in records:
        print(
            record["question_id"],
            record["event_count"],
            record["execution_burden"],
            record["event_counts"],
        )


if __name__ == "__main__":
    main()
