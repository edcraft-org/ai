"""Property-based template qualification without recipe authoring or enumeration."""

from edcraft_validator.application.math_correctness_sampling import (
    qualify_math_template,
)
from edcraft_validator.domains.math.engine.sampling import (
    CorrectnessTemplate,
    SamplingSettings,
    qualify_in_process,
)


def template(wrong=False):
    return CorrectnessTemplate.model_validate(
        {
            "request": {
                "problem": {
                    "operation": "differentiate",
                    "symbols": [{"name": "x"}],
                    "variable": "x",
                    "expression": {
                        "op": "mul",
                        "args": [
                            {"param": "a"},
                            {"op": "pow", "args": [{"sym": "x"}, {"num": "2"}]},
                        ],
                    },
                },
                "answer": {
                    "expression": {
                        "op": "mul",
                        "args": [
                            {"num": "3" if wrong else "2"},
                            {"param": "a"},
                            {"sym": "x"},
                        ],
                    }
                },
            },
            "parameters": [{"name": "a", "minimum": -1000000, "maximum": 1000000}],
        }
    )


def test_large_parameter_domain_is_sampled_and_replayable():
    settings = SamplingSettings(max_examples=12, seed=42)
    first = qualify_in_process(
        template().model_dump(mode="json"), settings.model_dump()
    )
    second = qualify_in_process(
        template().model_dump(mode="json"), settings.model_dump()
    )
    assert first == second
    assert first["status"] == "passed"
    # Hypothesis may schedule extra or duplicate trials; the property is that
    # at least the requested number of distinct assignments was checked, and
    # every replay reports identical observations.
    assert first["cases_checked"] >= settings.max_examples
    assert first["counts"]["correct"] == first["cases_checked"]
    assert second["counts"] == first["counts"]
    assert first["checking_mode"] == "property_based"
    assert first["domain_size"] == 2000001


def test_incorrect_template_reports_replayable_counterexample():
    report = qualify_in_process(
        template(True).model_dump(mode="json"),
        SamplingSettings(max_examples=15, seed=7).model_dump(),
    )
    assert report["status"] == "failed"
    assert report["counts"]["incorrect"] > 0
    assert report["counterexample"]["parameters"]["a"] != "0"


def test_public_qualification_is_isolated_and_bounded():
    result = qualify_math_template(
        template(),
        settings=SamplingSettings(max_examples=5, seed=13),
        timeout_seconds=15,
    )
    assert result["status"] == "passed"
    assert result["cases_checked"] == 5
    timed = qualify_math_template(template(), timeout_seconds=0.000001)
    assert timed["status"] == "timeout"


def test_missing_parameter_reference_is_not_silently_bound():
    data = template().model_dump(mode="json")
    data["parameters"][0]["name"] = "other"
    report = qualify_math_template(data)
    assert report["status"] == "error"
