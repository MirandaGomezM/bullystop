---
name: support-resources
description: |
  Looks up curated, verified anti-bullying and mental-health support resources (hotlines,
  websites, government programs) for a given country. Call this whenever a user seems to need
  external help, mentions being in crisis, asks for hotlines or resources, or when severity is
  "high" — for any role (student, parent, or teacher). Always prefer this over inventing or
  guessing a phone number or website yourself.
---

# Support Resources

This skill backs the `get_support_resources` Gemini tool call. It is intentionally separate from
the three persona skills (hearme, parentguide, protocol) because any of them may need to call it.

## How it loads (progressive disclosure)
- The Gemini tool *declaration* (name, description, JSON schema) is small and always sent with
  every request — that's the "metadata" layer.
- The actual resources data (`references/resources_by_country.json`) is **not** kept in memory
  as a Python literal and is **not** sent to the model directly. It is read from disk only the
  moment the tool is actually invoked, then handed back to the model as a function_response.
- The lookup/formatting logic is deterministic code, not something the LLM should reason about
  token-by-token — see `scripts/get_support_resources.py`.

## When to call this tool
- The user explicitly asks for a hotline, helpline, or website.
- Severity has been classified as "high".
- The user mentions being in crisis or in immediate danger.

## Updating the data
To add or correct a country's resources, edit
`references/resources_by_country.json` directly — no code changes or redeploys of the prompt
text are needed. Use the `country_map` in `scripts/get_support_resources.py` to add aliases
(e.g., regional spellings) for an existing country key.
