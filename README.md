# Bain-AC — Strategy Panel

A multi-agent strategy panel. Give it a market research report; it returns a fact-checked, multi-lens review and one defensible recommendation.

Built as ten agents modelled on an MBB engagement team: a Research & Data Services desk that owns the verified fact base, seven practice lenses that read the report independently, a red team that attacks their work, and a Partner who decides.

## Run a round

```
/panel inbox/some-market-report.pdf
```

Or drop the report in `inbox/` and run `/panel` with no argument.

Output lands in `reports/YYYY-MM-DD-<slug>/`. The deliverable is `04-partner-synthesis.md`; everything else is the audit trail behind it.

## First-time setup

1. **Fill in `context/00-core-brief.md`.** Every agent reads it every round. Two pages, replacing the template.
2. **Add context files** under `context/*/` and register each one in `context/INDEX.md`. Start with whatever you have — the panel works with a thin context pack and gets sharper as it fills.
3. **Read `docs/HOUSE-STANDARD.md`.** It is the evidence contract the agents work to, and it is what you should hold their output against.

## How it works

```
report → fact base → 7 blind parallel lenses → red team → Partner synthesis
```

The design turns on three choices:

- **The fact base blocks everything.** No lens runs until claims are verified and graded, so no lens has to invent a number to fill a gap.
- **The lenses are blind to each other.** Dispatched in parallel, so none can read another's conclusion and anchor on it. Their disagreements are the product.
- **Challenge is separate from decision.** The red team attacks; the Partner decides. An agent that has just attacked the work is badly placed to then stand behind it.

Full reasoning in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## The evidence rule

No bare numbers. Every quantified claim carries a tag showing where it came from:

| Tag | Means |
|---|---|
| `[F-012]` | Verified — source, URL, access date, verbatim quote in the fact base |
| `[R-p14]` | The report says so on p.14. **Not verified.** |
| `[C-finance/unit-econ.md]` | From our internal context pack |
| `[EST: method]` | An estimate, with a reproducible derivation |
| `[ASSUMPTION]` | A knowingly unevidenced premise |

`[F-]` versus `[R-]` is the distinction that matters. One means someone checked; the other means the report asserted it. A recommendation resting on `[R-]` is flagged, not hidden.

## Layout

```
.claude/agents/       ten agent definitions — edit these to change the roster
.claude/skills/panel/ the /panel orchestrator (Engagement Manager)
context/              your offline context pack; INDEX.md is the manifest
docs/                 HOUSE-STANDARD.md (evidence contract), ARCHITECTURE.md
inbox/                drop new reports here
reports/              round outputs
```

## Cost

A full round is roughly **$7**; a quiet-week delta review about **$1.50**. Lens agents run on Sonnet 5, the Research Desk / Red Team / Partner on Opus 5 — change the `model:` line in any `.claude/agents/*.md` to shift the balance. Cost model and the reasoning behind the model split are in `docs/ARCHITECTURE.md`.

## Weekly rounds

With no new report, `/panel` runs a **delta review**: it checks only whether any trigger from the last synthesis has fired, and reports that nothing changed if nothing did. A recurring panel that manufactures findings to justify its schedule stops being read — the quiet weeks have to actually be quiet.
