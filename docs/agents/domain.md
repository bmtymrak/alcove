# Domain Docs

How the engineering skills consume this repo's domain documentation.

## Layout

This repo uses a single-context layout:

- `GLOSSARY.md` at the repo root defines domain terms.
- `docs/adr/` holds architecture decision records, named `NNNN-<decision-slug>.md`.

## Before exploring

Read the root `GLOSSARY.md` and ADRs in `docs/adr/` that touch the area you're about to work in.

If these files don't exist, proceed silently. The `/domain-modeling` skill creates them lazily when terms or decisions get resolved.

## Use the glossary's vocabulary

When naming a domain concept in an issue title, refactor proposal, hypothesis, or test name, use the term defined in `GLOSSARY.md`.

If the concept isn't in the glossary, reconsider whether the project uses it. Note real gaps for `/domain-modeling`.

## Flag ADR conflicts

If a proposal contradicts an existing ADR, identify the ADR and explain why the decision should be reopened.
