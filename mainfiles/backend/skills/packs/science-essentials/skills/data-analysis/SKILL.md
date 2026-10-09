---
id: data-analysis
name: Data Analysis
category: engineering
invocation: both
description: Rigorous data analysis workflow — understand, clean, explore, model, and report with reproducible code.
parameters:
  - name: dataset_description
    type: string
    description: What the data is, where it lives, and the question to answer
    required: true
tags: [data, science, statistics, python]
---

# Data Analysis

## Process
1. **Understand** — inspect shape, dtypes, missingness, and distributions
   before any modeling. State the question in one sentence and the metric
   that would answer it.
2. **Clean** — handle missing values, outliers, and duplicates explicitly;
   log every cleaning decision (it is part of the result).
3. **Explore** — plot the key relationships. Look for confounders before
   believing any pattern.
4. **Model** — start with the simplest method that could work; only add
   complexity with a measured gain. Report uncertainty (CIs, not just
   point estimates).
5. **Report** — findings first, methods second, caveats honestly. Every
   number gets its n and its uncertainty.

## Rules
- Write a reproducible script, not one-off commands. Seed all randomness.
- Never p-hack: pre-register the primary analysis before exploring.
- A null result is a result — report it cleanly.

Dataset and question: {{dataset_description}}
