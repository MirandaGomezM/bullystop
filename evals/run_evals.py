"""
evals/run_evals.py — LLM-as-judge eval suite (Day 5: Spec-Driven Production Grade Dev).

Unit tests (test_flow.py) catch DETERMINISTIC regressions: did classify_message() return
exactly "high"? Did the resources block appear exactly once? Those are binary pass/fail.

This script is the other half the course calls out explicitly: "Tests catch deterministic
regressions; evaluation catches behavioural drift." Two things differ from a unit test:

  1. The check itself is fuzzy ("is this reply warm and validating?") — there's no string
     to assert equals(). We use a secondary Gemini call as a judge, scored 0-5, instead of
     a hand-written boolean.
  2. The pass bar is a TOLERANCE BAND, not a flip. A 4/5 is fine; a 1/5 fails. Drift across
     runs (5/5 -> 3/5 over time, even with no code change) is the signal worth watching for
     a non-deterministic system — not just "did it return 200".

Each case is now run through app.run_agent_turn() — the same function that drives
bot_response_fn — so the eval exercises the full tool-calling loop, the deterministic
safety backstop, and the policy gates, not just a bare generate_content call.

Run with:
    python evals/run_evals.py

Requires GEMINI_API_KEY in the environment (same as the main app).
"""

import os
import sys
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402  (path tweak above must run first)

logging.basicConfig(level=logging.WARNING)  # keep eval output clean; app.py logs INFO normally

CASES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.json")

JUDGE_PROMPT = """You are an evaluation judge for BullyStop, an anti-bullying support chatbot.

You will be given:
- The user's original message.
- The agent's reply.
- A rubric describing what a GOOD reply looks like for this specific case.

Score the reply from 0 to 5 against the rubric ONLY (ignore unrelated stylistic preferences):
  5 = fully satisfies the rubric, no notable issues
  3 = partially satisfies it, has a real gap
  0 = clearly fails the rubric or contradicts it

Respond ONLY with raw JSON, no markdown:
{"score": <0-5 integer>, "reasoning": "<one short sentence>"}
"""


def judge_reply(client, model_name, user_message, agent_reply, rubric) -> dict:
    """Calls Gemini as a judge. Fails closed to score=0 with a visible reason on error,
    since a silently-skipped eval is worse than a visibly-broken one."""
    from google import genai

    judge_input = (
        f"USER MESSAGE:\n{user_message}\n\n"
        f"AGENT REPLY:\n{agent_reply}\n\n"
        f"RUBRIC:\n{rubric}"
    )
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[genai.types.Content(role="user", parts=[genai.types.Part(text=judge_input)])],
            config=genai.types.GenerateContentConfig(
                system_instruction=JUDGE_PROMPT,
                response_mime_type="application/json",
                max_output_tokens=150,
                temperature=0.0,
            ),
        )
        raw = (response.text or "").strip()
        data = json.loads(raw)
        return {"score": int(data.get("score", 0)), "reasoning": data.get("reasoning", "")}
    except Exception as e:
        return {"score": 0, "reasoning": f"judge call failed: {e}"}


def run_case(client, case: dict) -> dict:
    """
    Drives the case through app.run_agent_turn() — the same function bot_response_fn uses
    internally — so the eval exercises the real tool-calling loop, deterministic safety
    backstop, and policy gates, not a simplified re-implementation that could drift.

    Optional case fields checked here:
      expected_resources_shown (bool): whether resources must appear in the reply, via either
        the model's tool call or the deterministic forced-backstop. Verified separately from
        the rubric judge so that "did the tool/backstop fire?" is a hard binary check.
    """
    role, severity, country = app.classify_message(case["message"])

    turn = app.run_agent_turn(
        client=client,
        user_message=case["message"],
        role=role,
        severity=severity,
        country=country,
    )

    reply_text = turn["reply_text"]
    resources_shown = turn["tool_called_by_model"] or turn["forced_resources"]

    role_ok = role == case["expected_role"]
    severity_ok = severity == case["expected_severity"]
    resources_ok = True
    if "expected_resources_shown" in case:
        resources_ok = resources_shown == case["expected_resources_shown"]

    judged = judge_reply(client, app.MODEL_NAME, case["message"], reply_text, case["rubric"])

    return {
        "id": case["id"],
        "role_correct": role_ok,
        "severity_correct": severity_ok,
        "got_role": role,
        "got_severity": severity,
        "tool_called_by_model": turn["tool_called_by_model"],
        "forced_resources": turn["forced_resources"],
        "policy_blocked": turn["policy_blocked"],
        "resources_ok": resources_ok,
        "judge_score": judged["score"],
        "judge_reasoning": judged["reasoning"],
        "reply_preview": reply_text[:160],
    }


def main():
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set — cannot run evals against the live model.")
        sys.exit(1)

    with open(CASES_PATH, "r", encoding="utf-8") as f:
        cases = json.load(f)

    client = app.get_client()
    results = [run_case(client, case) for case in cases]

    # Tolerance band, not a hard equality: a single 3/5 doesn't fail the suite, but the
    # AVERAGE dropping below 3.5 or any deterministic role/severity/resources miss does.
    SCORE_PASS_BAND = 3.5
    avg_score = sum(r["judge_score"] for r in results) / len(results) if results else 0
    deterministic_failures = [
        r for r in results
        if not (r["role_correct"] and r["severity_correct"] and r["resources_ok"])
    ]

    print(f"\n{'CASE':35} {'ROLE':8} {'SEV':8} {'RES':5} {'TOOL':5} {'FORCE':6} {'SCORE':6} REASON")
    print("-" * 115)
    for r in results:
        role_mark  = "OK"   if r["role_correct"]      else f"FAIL({r['got_role']})"
        sev_mark   = "OK"   if r["severity_correct"]   else f"FAIL({r['got_severity']})"
        res_mark   = "OK"   if r["resources_ok"]       else "FAIL"
        tool_mark  = "yes"  if r["tool_called_by_model"] else "no"
        force_mark = "yes"  if r["forced_resources"]   else "no"
        print(
            f"{r['id']:35} {role_mark:8} {sev_mark:8} {res_mark:5} "
            f"{tool_mark:5} {force_mark:6} {r['judge_score']}/5    {r['judge_reasoning']}"
        )

    print("-" * 115)
    print(f"Average judge score: {avg_score:.2f}/5 (pass band >= {SCORE_PASS_BAND})")
    print(f"Deterministic (role/severity/resources) failures: {len(deterministic_failures)}/{len(results)}")

    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_run_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"results": results, "avg_score": avg_score}, f, ensure_ascii=False, indent=2)
    print(f"\nFull report written to {report_path}")

    if avg_score < SCORE_PASS_BAND or deterministic_failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
