"""Shared calculation capabilities and the general dispatcher; no asset type is known here.

Scenario sampling and the scenario set, the economic graph's propagation, attribution
(Shapley), distribution statistics, data resolution against a snapshot, the dispatcher of
positions to their models and the portfolio slices. Plugins reach the parts they may use
through ``msa.plugin_sdk.calc``; asset families live in ``msa.plugins``.
"""
