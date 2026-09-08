---
id: web-search
name: Web Search
category: knowledge
invocation: both
description: >-
  Searches the live web for up-to-date information on any topic and returns
  sourced results (title, URL, snippet). Use it whenever the user needs
  current facts, recent news, documentation, or anything a static model
  wouldn't reliably know.
parameters:
  - name: query
    type: string
    description: The search query to run against the web.
    required: true
tags:
  - search
  - web
  - research
  - live
source_repo: web-search
version: 1.0.0
---
You are a web research assistant. Use the following web search results for the
query "{query}" to answer the user's question accurately and concisely. Cite
the source URL whenever you base a claim on a result. If the results are
insufficient, say so plainly rather than guessing.

Search query: {query}
