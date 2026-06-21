"""
policy_server.py — Hybrid Policy Server (Day 5: Spec-Driven Production Grade Dev).

Intercepts agent actions BEFORE they reach the user or any external system, in two layers:

  1. Structural gating ("traffic lights"): fast, deterministic, no LLM call. Binary
     role/action checks — e.g. only an explicit safety-relevant context may force the
     resources tool; a teacher's incident-report flow shouldn't leak student PII into a
     casual chat reply.

  2. Semantic gating ("intelligent referee"): a cheap secondary LLM call that inspects the
     *content* of an outgoing message against natural-language policies that a regex can't
     reliably express — e.g. "never assert a single emergency number (911, 988...) as if it
     works globally" or "never invent a hotline/website that wasn't returned by the
     get_support_resources tool."

This mirrors the course's point: structural rules catch "is this action allowed at all";
semantic rules catch "the action is allowed, but the *way* it's being used violates a
policy" — the case structural rules structurally cannot cover.

This module is deliberately self-contained (no import from app.py) so it can be unit
tested in isolation and reused by other agents/personas later.
"""

import re
import json
import logging

# ── Structural gating: deterministic rules, evaluated first, no LLM call ──

# Phone numbers / hotlines that are only valid in specific countries. If the *final* agent
# reply contains one of these without the get_support_resources tool having verified it for
# the user's actual country, that's a structural violation — the same bug that was fixed in
# the emergency panel (hardcoded US 988), but now checked at the message-gating layer instead
# of relying on a one-off fix in the UI.
_COUNTRY_LOCKED_NUMBERS = {
    "988": "US",       # US Suicide & Crisis Lifeline
    "111": "UK",        # NHS 111 (non-emergency)
    "106": "AR",        # Centro de Asistencia al Suicida (Argentina)
}


def structural_gate(role: str, action: str, payload: dict) -> dict:
    """
    Fast, binary checks with no model call. Returns {"allowed": bool, "reason": str | None}.

    `action` is a short string identifying what's being gated, e.g.:
      - "call_tool:get_support_resources"
      - "send_message"
    `payload` carries whatever's relevant to that action (tool args, or the outgoing text).
    """
    if action == "call_tool:get_support_resources":
        country = (payload.get("country") or "").strip()
        if not country:
            return {"allowed": False, "reason": "country argument missing"}
        return {"allowed": True, "reason": None}

    if action == "send_message":
        text = payload.get("text", "")
        verified_country = payload.get("verified_country")  # country the tool actually returned data for
        for number, locked_country in _COUNTRY_LOCKED_NUMBERS.items():
            if re.search(rf"\b{re.escape(number)}\b", text) and verified_country != locked_country:
                return {
                    "allowed": False,
                    "reason": (
                        f"message asserts country-locked number '{number}' "
                        f"({locked_country}-only) without verified resources for that country"
                    ),
                }
        return {"allowed": True, "reason": None}

    # Unknown action: default-allow but log loudly, so new actions don't silently bypass
    # gating just because nobody wrote a rule for them yet.
    logging.warning(f"[POLICY] structural_gate: no rule defined for action='{action}' — default-allow")
    return {"allowed": True, "reason": None}


# ── Semantic gating: a secondary, cheap LLM call as "intelligent referee" ──

_SEMANTIC_POLICY_PROMPT = """You are a safety/policy reviewer for BullyStop, an anti-bullying \
support chatbot. You will be shown ONE outgoing message that the main agent is about to send \
to a user. Check it ONLY against these policies:

1. It must NOT invent, guess, or state a specific phone number, hotline name, or website that \
   looks like a real-world resource UNLESS it is clearly inside a block that came from the \
   verified get_support_resources tool (such a block is usually introduced with phrasing like \
   "verified resources" or a list of named organizations).
2. It must NOT claim any single emergency number (e.g. 911, 988, 111, 106) works "everywhere" \
   or "in any country" — these are country-specific.
3. It must NOT reveal or repeat back another user's personal data (full name, address, school \
   name + grade combination) that could identify a specific child to a stranger.

Respond ONLY with raw JSON, no markdown:
{"allowed": true|false, "reason": "<short reason, or null if allowed>"}
"""


def semantic_gate(client, model_name: str, outgoing_text: str) -> dict:
    """
    Calls a cheap, temp=0 Gemini request to review `outgoing_text` against natural-language
    policies a regex can't express. Fails OPEN (allowed=True) on any error — a broken policy
    reviewer should degrade to "no semantic check this turn", not take the whole app down.
    This mirrors the structural/semantic split from the course: this layer exists for the
    cases structural_gate() above cannot catch (e.g. a plausible-sounding but fabricated
    hotline name, which has no fixed string to regex against).
    """
    if not outgoing_text or not outgoing_text.strip():
        return {"allowed": True, "reason": None}

    try:
        from google import genai  # local import: keeps this module importable without the SDK in unit tests that stub `client`

        response = client.models.generate_content(
            model=model_name,
            contents=[genai.types.Content(role="user", parts=[genai.types.Part(text=outgoing_text)])],
            config=genai.types.GenerateContentConfig(
                system_instruction=_SEMANTIC_POLICY_PROMPT,
                response_mime_type="application/json",
                max_output_tokens=120,
                temperature=0.0,
            ),
        )
        raw = (response.text or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        data = json.loads(raw)
        return {"allowed": bool(data.get("allowed", True)), "reason": data.get("reason")}
    except Exception as e:
        logging.warning(f"[POLICY] semantic_gate failed open: {e}")
        return {"allowed": True, "reason": f"semantic gate skipped (error: {e})"}


def gate_outgoing_message(client, model_name: str, text: str, verified_country: str = None,
                           run_semantic: bool = True) -> dict:
    """
    Convenience wrapper combining both layers for the common "about to send a message" case.
    Structural gate runs first (cheap); semantic gate only runs if structural passed, and only
    if `run_semantic=True` (callers may want to skip it on every streamed chunk and only gate
    the final assembled message, for latency reasons).
    """
    structural = structural_gate("send_message", "n/a", {"text": text, "verified_country": verified_country})
    if not structural["allowed"]:
        logging.warning(f"[POLICY] structural gate blocked outgoing message: {structural['reason']}")
        return structural

    if not run_semantic:
        return {"allowed": True, "reason": None}

    semantic = semantic_gate(client, model_name, text)
    if not semantic["allowed"]:
        logging.warning(f"[POLICY] semantic gate blocked outgoing message: {semantic['reason']}")
    return semantic