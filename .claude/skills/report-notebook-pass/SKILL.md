---
name: report-notebook-pass
description: Run the human-understanding pass on a report notebook - figures that grade themselves, plain-first narrative, verifiable-by-a-cold-reader standard. Use when creating or auditing any report notebook.
---

# Report-notebook pass

Bring one report notebook to the standard where **a teammate who did not run
the experiment can verify it cold**: say what was measured and how, what each
figure claims, where the numbers come from, and what would change their mind,
without asking the author. That acceptance test governs every item below.

## The checklist

Work section by section; a notebook passes only when every item holds.

### Figures
1. **Question-form title stating its own answer**, with the headline value
   computed at runtime, never typed ("Can any combination detect the implied
   emotion? No: best cell 6 of 12, pass bar 8"). If a slider changes the
   verdict, the slider step must retitle with its own layer's verdict -
   frozen titles over moving data are a defect.
2. **A subtitle line defining the atomic mark**: what one bar / dot / cell is,
   and the chance level.
3. **Grading scale in the plot**: labeled anchors for failure (chance, zero,
   measured noise floor) and strength (the registered bar where one exists,
   else a meaningful comparator), as reference lines/bands. The reader judges
   magnitudes from the figure alone.
4. **Complete labeling**: axis titles with units, legends for every color and
   dash encoding (naming the ROLE, e.g. "probes built from DeepSeek-written
   stories", not just "deepseek" - bank vs substrate confusion is the classic
   failure), titled colorbars, layer slider on per-layer measures.
5. **Render and look**: rasterize every figure (kaleido) at the default state
   AND at least one non-default slider position; fix every overlap,
   collision, and truncation you see. Never assume a figure renders well.

### Narrative
6. **Plain words first**: define every term in common words before its
   registry code, which appears only in parentheses ("the identity read
   (registry name: gate read G)"). Header carries a Key concepts block and an
   Index.
7. **How-to-read block after every figure** (collapsible details): axes named
   before referenced, one idea per sentence, valid AND invalid readings, "a
   good result here would look like X, a bad one Y, observed sits at Z".
8. **Every section ends with meaning**: what the result establishes, the live
   hypotheses labeled as hypotheses each paired with the experiment that
   would decide it, and open questions. If an explanation is good enough for
   a collaborator in chat, it belongs in the notebook.
9. **No number in markdown that is not computed by an adjacent cell** (or
   cited to a named evidence file). No em dashes in prose.

### Code and data
10. **No machine-local absolute paths**; loading goes through the project's
    artifact resolver. Notebook runs unchanged on any clone.
11. **Analysis/figure code lives in importable package functions**; cells are
    load-call-show. Test figures by importing the function and rendering.
12. **Hyperlink every referenced artifact at first mention** (datasets,
    papers, model cards, repos). HTML in markdown wherever clearer.

## Process

- Re-execute the notebook end to end after the pass; zero error outputs.
  Check the exit code and the outputs, not the log tail.
- If delegated to a subagent: the orchestrator independently diffs the
  changes, renders figures at multiple states, and spot-checks verification
  claims before presenting or committing. Reports are claims, not evidence.
- Report any prose-vs-evidence mismatch found; fix prose to match evidence,
  never the reverse.
