"""Code-owned arguments selected once with the initial checking plan."""

from pydantic import Field

from edcraft_validator.domains.code.code_types import CodeFeature
from edcraft_validator.llm.llm_contracts import RecommendedCheckArguments


class RequiredFeaturesArguments(RecommendedCheckArguments):
    required: list[CodeFeature] = Field(
        min_length=1,
        description=(
            "Select only features explicitly required by the educator. "
            "helper_function means a separate helper called from the entry function; "
            "list_aggregate means sum, min, max, all or any, not a manual loop. "
            "These requirements remain fixed across revisions."
        ),
    )


CODE_CHECK_ARGUMENT_MODELS = (("code_require_features", RequiredFeaturesArguments),)
