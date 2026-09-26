"""Helpers of the report a plugin's sections and projections may use.

A report section writes numbers only through ``ReportContext.cite`` (validator V9 checks
each against the metric tree). These are the platform's own helpers for the text around
them: ``pointer_token`` (a key as one JSON Pointer token of a metric path),
``extract_numbers`` (the numbers a phrase carries: free text with digits must not reach the
report uncited) and ``sentence`` (a phrase as a sentence).
"""

from msa.reporting.context import sentence
from msa.reporting.numbers import extract_numbers, pointer_token

__all__ = ["extract_numbers", "pointer_token", "sentence"]
