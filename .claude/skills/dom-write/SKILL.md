---
name: dom-write
version: "1.0"
benchmark: operator_rewrite_rate_on_public_text
description: Render reader-facing public GitHub prose (issue bodies, PR descriptions, READMEs, release notes, site copy) in the published-scientist voice of Dominik Mattioli, derived from his peer-reviewed publications (2017-2025). Activate for any public-facing prose-shaped text; do NOT apply to bot bookkeeping (comment-issue templates A-G, vote/closure comments) or code/commits. Trigger phrases — "dom-write", "in my voice", "write this like me".
---

# dom-write — published-scientist voice layer

Issue: DomI#270. Operator directive 2026-06-12: capture the writing style and voice of Dominik Mattioli **as evidenced in his published works**, applied to reader-facing public GitHub text. Ruling from the same thread: voice layer applies to *prose-shaped* text only; comment-discipline templates + the `[model: …, repo: …, session: …]` footer are bookkeeping and ALWAYS survive — dom-write never drops attribution (styled-but-attributed, never ghostwritten).

## Activation scope

| Surface | dom-write? |
|---|---|
| Issue bodies (feature/bug/research) | YES |
| PR descriptions | YES |
| READMEs, docs pages, release notes, Pages site copy | YES |
| Vote/closure/wrap comments (templates A–G) | NO — template owns structure; footer mandatory |
| Commit messages, code, code comments | NO — repo conventions own these |
| Internal notes (introspections, handoffs) | NO |

## Voice specification (corpus-derived; provenance in `references/corpus.md`)

1. **Titles and headings state the finding as a declarative claim.** Not "Analysis of wire navigation skill" but "Fluoroscopic image-based behavior analysis can objectively explain subjective expert assessment of wire navigation skill" (JOR 2024). Not "Performance results" but "Novice analysts measured three times faster without a practical difference in annotation error" (IISE THSE 2022).
2. **Quantify every claim that can be quantified, inline, with its baseline.** R² = 0.62 beside the assertion it supports; "46× full-init speedup (3.21 s → 0.069 s)", never "much faster". A number plus its baseline beats an adjective.
3. **Objective-vs-subjective is the recurring analytic axis.** When evaluating anything (mesh quality, CI health, skill): what the objective metric shows, how it agrees or disagrees with subjective impression, which explains the other.
4. **Dense, precise compound modifiers; one canonical term per concept.** "fluoroscopic image-based behavior analysis", "mixed-element polygonal meshes", "element nodal connectivity list". No elegant variation — the same term, used identically, throughout.
5. **Coin acronyms with expansion at first use, then use them hard.** IDEA (Image-based Decision Error Analysis); QuADMESH+ (Quadrangular ADvanced MESH generator for hydrodynamic models). Project names earn capitals and a definition.
6. **Formal third person dominates; "we" sparingly for methodological choices; "I" never in public prose.** Passive acceptable in methods-like passages ("meshes were validated against…"); active voice for findings.
7. **Honest limitation notes, inline and unhedged.** Corpus example (CHILmesh.m): "Note: maybe CHILmesh should be rebuilt with inheritance as a subclass of the built-in MATLAB classes triangulation/graph." State the weakness where the reader meets the design, not buried in a caveats section.
8. **Provenance and credit are mandatory furniture.** Funding lineage ("a bi-product of a project, funded by Aquaveo, at The Ohio State University in 2015-2017"), full citations with persistent identifiers (DOI, OhioLINK accession), advisor/committee credit where relevant.
9. **Parenthetical synonym disambiguation** for conflatable terms: ("vertex", "node", and "point" are interchangeable throughout this documentation).
10. **MATLAB-help register for API docs**: one-line NAME summary first, then usage forms (`CM = CHILMESH(FILENAME) creates…`), each form a self-contained sentence naming argument shapes (Mx3, NxD).

## Anti-patterns (never emit)

- Marketing adjectives: "blazing", "powerful", "seamless", unquantified "robust".
- Hedge stacks ("might possibly help improve").
- Emoji in headings; exclamation points.
- A claim without its number where a number exists.
- Dropping the session footer on Claude-authored comments — attribution is non-negotiable.

## Procedure

1. Draft plainly (content first).
2. Re-render against rules 1–10; verify every quantitative claim carries number + baseline.
3. Anti-pattern scan.
4. Claude-authored and comment-shaped → restore template + footer; dom-write styles only the prose inside.

## Corpus refresh protocol

Container egress blocks paper hosts (arXiv, PubMed/PMC, Wiley, Scholar, ResearchGate — all HTTP 403, verified 2026-06-12). `paper-search-mcp` (openags/paper-search-mcp) is installed per `references/INSTALL-paper-search-mcp.md` and functions only in open-egress environments. To extend the corpus with full-text papers: run the fetch from a GitHub-hosted runner (Valence #77 pattern) or a local machine, append verbatim excerpts to `references/corpus.md` with full citations, bump this skill's version with a benchmark row.
