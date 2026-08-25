---
name: research
description: Search, retrieve, and analyse academic papers. Use when surveying literature, looking up specific papers, tracing citations, or building a research summary.
---

# Research

MCP servers + one HTTP endpoint for academic literature research. Use the right tool for the job. Which MCP servers are configured varies by project — check `.mcp.json`; every workflow below has a fallback that needs no MCP (AlphaXiv HTTP + WebSearch).

## When to use what

| Need | Tool | Why |
|------|------|-----|
| Broad topic search (many sources) | `paper-search` MCP | Searches 18+ sources simultaneously (arXiv, Semantic Scholar, OpenAlex, PubMed, DBLP, etc.) |
| ArXiv-specific search or download | `arxiv` MCP | Direct arXiv API -- search, list, read, download papers |
| Citation graph traversal | `semantic-scholar` MCP (optional — often not configured) | Follow who-cites-whom, find related work, author profiles. If absent: `paper-search`'s Semantic Scholar source, or the Semantic Scholar API via curl/WebSearch |
| Structured paper overview | AlphaXiv HTTP | AI-generated analysis of any arXiv paper, optimised for LLM consumption |
| Full paper text | AlphaXiv HTTP (fallback) | Complete extracted text when overview lacks detail |

## Workflows

### Survey a topic (e.g., "refusal taxonomies in LLMs")
1. `paper-search` MCP -- broad search across all sources, get top 20-30 results
2. Triage -- read abstracts, pick the 5-10 most relevant
3. For each: AlphaXiv overview (`curl -s "https://alphaxiv.org/overview/{ID}.md"`)
4. Synthesize findings into a research summary

### Trace a citation chain (e.g., "what builds on Arditi et al. 2024?")
1. `semantic-scholar` MCP if configured (else `paper-search`'s Semantic Scholar source, or the public Semantic Scholar API) -- find the paper, get its citations and references
2. Filter citing papers by relevance (read abstracts)
3. Deep-read the most relevant via AlphaXiv or arxiv MCP

### Look up a specific paper
1. If you have the arXiv ID: AlphaXiv overview first (fastest)
2. If you have title/author: `arxiv` or `paper-search` MCP to find the ID
3. If you need the full text: `curl -s "https://alphaxiv.org/abs/{ID}.md"`
4. Last resort (not on AlphaXiv): `arxiv` MCP download or PDF at `https://arxiv.org/pdf/{ID}`

### Build a bibliography
1. `paper-search` MCP -- search, collect paper metadata
2. `semantic-scholar` MCP if configured (else Crossref/OpenAlex via `paper-search`) -- verify citations, get DOIs
3. Save BibTeX entries to the project's references location (e.g. `references/` or `data/papers/`)

## AlphaXiv HTTP endpoints

```bash
# Structured overview (try first)
curl -s "https://alphaxiv.org/overview/{PAPER_ID}.md"

# Full paper text (fallback)
curl -s "https://alphaxiv.org/abs/{PAPER_ID}.md"
```

Paper ID extraction:

| Input | ID |
|-------|-----|
| `https://arxiv.org/abs/2401.12345` | `2401.12345` |
| `https://arxiv.org/pdf/2401.12345` | `2401.12345` |
| `2401.12345v2` | `2401.12345v2` |

## Error handling

- AlphaXiv 404: paper not yet processed, use arxiv MCP or PDF
- MCP server unavailable: fall back to AlphaXiv HTTP + WebSearch
- Rate limits on Semantic Scholar: slow down, or add API key to `.env` as `SEMANTIC_SCHOLAR_API_KEY`

## Environment variables (optional)

| Variable | Get it at | Effect |
|----------|-----------|--------|
| `SEMANTIC_SCHOLAR_API_KEY` | https://www.semanticscholar.org/product/api#api-key-form | 1 req/sec instead of shared pool |
