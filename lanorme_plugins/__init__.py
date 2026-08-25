"""Harness-specific lanorme checks.

Registered via `plugins = [...]` in lanorme.toml, so `lanorme check .` runs the
harness's own rules alongside the built-in ones — one command, one config, one
exit code.

Deliberately NOT here: research-tree and research-log validation. That is the
research-integrity gate and lives in `scripts/validate_research.py` as a
zero-dependency script, because a project that never installs lanorme must still
have every integrity guarantee.
"""
