"""The platform SDK used by the fixed capability template.

Generated analytical code (compute and interpret) does not call the SDK: the template's fixed
execute(context) does. Capabilities may import only agrimon.sdk, NumPy and math.
"""

from agrimon.sdk.core import (  # noqa: F401
    analysis_output,
    build_result,
    class_summary,
    evidence,
    fmt,
    interpretation,
    load_bands,
    matrix_metrics,
    now,
    to_matrix,
    zones_from_masks,
)

__all__ = [
    "load_bands",
    "analysis_output",
    "to_matrix",
    "matrix_metrics",
    "zones_from_masks",
    "class_summary",
    "evidence",
    "interpretation",
    "build_result",
    "fmt",
    "now",
]
