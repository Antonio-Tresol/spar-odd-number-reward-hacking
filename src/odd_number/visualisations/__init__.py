"""Everything that turns results into something a person looks at.

The split is by output, not by subject. A module belongs here when what it
returns is a figure or a page: `figures`, `branch_curves`, `deliberation`,
`tags` and `variants` build matplotlib figures for the report notebooks, and
`explainers` builds the self-contained HTML page under `explainers/`, from the
template beside it.

Everything these modules read is defined one level up, and the dependency runs
one way: `visualisations` imports from `odd_number`, never the reverse. The one
module that reaches down into this package is `cli.py`, which composes every
subcommand and is allowed to see everything. So no module that measures anything
can import a module that draws, which is what stops a change to a figure from
moving a number.

That direction is the property to preserve when adding a module here. If
something in this package starts wanting to be imported by `grades` or
`branches`, it is not a visualisation and belongs one level up.
"""
