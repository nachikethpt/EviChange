"""
LESSON 7: Prompt Engineering for Structured Claims (Student 2's core deliverable)
=============================================================
Write and test this in VS Code (the JSON parsing/validation logic
needs no GPU and runs anywhere). The model-loading and generation
parts are marked clearly -- copy those into Colab to actually run
against Qwen2-VL.
"""

import json
import re


# ============================================================
# PART 1: Why "just ask nicely" doesn't work
# ============================================================
print("=" * 60)
print("PART 1: The Problem With Asking an LLM for JSON")
print("=" * 60)

print("""
If you just say "respond in JSON," you'll often get back something
like this (a REAL, common failure pattern):

    Sure! Here's the analysis in JSON format:

    ```json
    {
      "claim_type": "mining_expansion",
      "confidence": "high"
    }
    ```

    Let me know if you need anything else!

That's not valid JSON on its own -- it's JSON wrapped in explanation
text and markdown code-fence characters. If you try to json.loads()
that raw string, it crashes. This happens because the model is doing
what it was trained to do: be a helpful chat assistant, which means
explaining itself. You have to explicitly override that instinct.

Three things fix most of this:
  1. A strict system-level instruction: "Output ONLY valid JSON, no
     other text, no markdown formatting, no explanation."
  2. A few-shot example: show the model exactly one correct
     input/output pair before asking your real question.
  3. Low temperature (near 0): reduces randomness, makes the model
     stick closer to the pattern you showed it instead of improvising.
""")


# ============================================================
# PART 2: The Prompt Template
# ============================================================
print("=" * 60)
print("PART 2: Building the Prompt Template")
print("=" * 60)

SYSTEM_INSTRUCTION = """You are analyzing two satellite images of the same location, taken at different times, to identify signs of mining-related land change.

Output ONLY a single valid JSON object. No explanation, no markdown code fences, no text before or after the JSON.

The JSON object must have exactly these fields:
{
  "claim_type": one of ["mining_expansion", "vegetation_loss", "no_significant_change", "other"],
  "location_description": a short phrase describing WHERE in the image (e.g. "northeast corner", "along the river"),
  "estimated_change_direction": one of ["increase", "decrease", "none"],
  "confidence": one of ["high", "medium", "low"],
  "reasoning": one short sentence describing the visual evidence that led to this claim
}

Do not invent precise numbers, percentages, or areas. Use only the categorical values listed above."""

FEW_SHOT_EXAMPLE_OUTPUT = """{"claim_type": "mining_expansion", "location_description": "southeast section, near the existing quarry edge", "estimated_change_direction": "increase", "confidence": "high", "reasoning": "bare, disturbed ground visibly extends beyond the quarry boundary seen in the earlier image"}"""

print("System instruction defined.")
print("Few-shot example output defined.")
print("""
Notice what's deliberately EXCLUDED from the schema: no square-meter
figures, no percentages, no exact coordinates. That's Lesson 6's point
in code form -- the model doesn't have reliable access to those
numbers, so asking for them just invites confident-sounding fabrication.
Categorical claims (increase/decrease/none, high/medium/low) are
things a model can actually judge from what it visually perceives.
""")


# ============================================================
# PART 3: Parsing the Model's Output Safely
# ============================================================
print("=" * 60)
print("PART 3: Parsing Output Safely (this part needs no GPU)")
print("=" * 60)

print("""
Even with a good prompt, the model will occasionally still wrap its
answer in markdown fences or add a stray sentence. Don't just crash --
extract the JSON defensively, then validate it against the schema you
actually need.
""")


def extract_json(raw_text: str) -> dict:
    """
    Pull a JSON object out of a model's raw text output, even if it's
    wrapped in markdown code fences or has stray text around it.
    Raises ValueError if nothing parseable is found.
    """
    # Strip markdown code fences if present (```json ... ``` or ``` ... ```)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        # Fall back to finding the first { ... } block in the text
        brace_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not brace_match:
            raise ValueError(f"No JSON object found in output: {raw_text!r}")
        candidate = brace_match.group(0)

    return json.loads(candidate)  # raises json.JSONDecodeError if still malformed


VALID_SCHEMA = {
    "claim_type": {"mining_expansion", "vegetation_loss", "no_significant_change", "other"},
    "estimated_change_direction": {"increase", "decrease", "none"},
    "confidence": {"high", "medium", "low"},
}
REQUIRED_FIELDS = {"claim_type", "location_description", "estimated_change_direction", "confidence", "reasoning"}


def validate_claim(claim: dict) -> tuple[bool, str]:
    """
    Check a parsed claim against the schema Student 3's gate will expect.
    Returns (is_valid, error_message).
    """
    missing = REQUIRED_FIELDS - claim.keys()
    if missing:
        return False, f"Missing required fields: {missing}"

    for field, allowed_values in VALID_SCHEMA.items():
        if claim[field] not in allowed_values:
            return False, f"Field '{field}' has invalid value '{claim[field]}', expected one of {allowed_values}"

    if not isinstance(claim["location_description"], str) or not claim["location_description"].strip():
        return False, "location_description must be a non-empty string"

    if not isinstance(claim["reasoning"], str) or not claim["reasoning"].strip():
        return False, "reasoning must be a non-empty string"

    return True, ""


# ============================================================
# PART 4: Test the Parsing Logic Against Realistic Failures
# ============================================================
print("=" * 60)
print("PART 4: Testing Against Realistic Model Output")
print("=" * 60)

test_cases = [
    # Clean, correct output
    '{"claim_type": "mining_expansion", "location_description": "east edge", "estimated_change_direction": "increase", "confidence": "high", "reasoning": "bare ground extends past prior boundary"}',

    # Wrapped in markdown fences with chatty text -- the common failure
    'Sure! Here is the analysis:\n\n```json\n{"claim_type": "no_significant_change", "location_description": "whole patch", "estimated_change_direction": "none", "confidence": "medium", "reasoning": "no visible disturbance between the two dates"}\n```\n\nLet me know if you need more detail!',

    # Invalid enum value (model didn't follow the schema exactly)
    '{"claim_type": "possible_mining", "location_description": "center", "estimated_change_direction": "increase", "confidence": "high", "reasoning": "looks disturbed"}',

    # Missing a required field entirely
    '{"claim_type": "vegetation_loss", "estimated_change_direction": "decrease", "confidence": "low", "reasoning": "some browning visible"}',

    # Complete garbage -- model failed entirely
    "I'm not able to determine a clear answer from these images.",
]

for i, raw_output in enumerate(test_cases, 1):
    print(f"\n--- Test case {i} ---")
    print(f"Raw model output: {raw_output[:80]}{'...' if len(raw_output) > 80 else ''}")
    try:
        parsed = extract_json(raw_output)
        is_valid, error = validate_claim(parsed)
        if is_valid:
            print(f"  RESULT: Valid claim -> {parsed['claim_type']} / {parsed['confidence']} confidence")
        else:
            print(f"  RESULT: Parsed but INVALID -> {error}")
    except (ValueError, json.JSONDecodeError) as e:
        print(f"  RESULT: Failed to parse -> {e}")


# ============================================================
# PART 5: What to Do on Failure -- Retry Logic
# ============================================================
print("\n" + "=" * 60)
print("PART 5: Retry Strategy")
print("=" * 60)

print("""
When extract_json() or validate_claim() fails, you have three options,
in order of preference:

1. RETRY WITH A CORRECTIVE MESSAGE (best)
   Send the model's bad output back to it with: "Your previous
   response was not valid JSON matching the required schema. Here is
   what you sent: [bad output]. Respond again with ONLY the corrected
   JSON object." This works surprisingly well -- models are often
   good at fixing their own formatting mistakes when shown the error.

2. RETRY WITH THE ORIGINAL PROMPT, LOWER TEMPERATURE
   If corrective retry isn't set up yet, just re-run the original
   prompt with temperature even closer to 0. Sometimes it was just a
   one-off sampling fluke.

3. GIVE UP AND MARK AS "parse_failed"
   After 2-3 retries, stop. Record it as a distinct outcome (not the
   same as the verification gate's "abstain") -- Student 3's gate
   should treat "the VLM never produced a checkable claim at all" as
   its own category in your metrics, separate from "the VLM made a
   claim and the gate rejected it." These mean different things for
   your hallucination-rate analysis.

Cap retries at 2-3. Looping forever on a model that won't cooperate
wastes your limited Colab GPU time for no benefit.
""")


# ============================================================
# PART 6: The Actual Model Call (COLAB ONLY -- needs GPU)
# ============================================================
print("=" * 60)
print("PART 6: Putting It Together With the Real Model")
print("=" * 60)

print("""
This is the part that needs the GPU -- copy this into your Colab
session (after loading the model the way Lesson 6 showed):

    def get_claim(image_before, image_after, max_retries=2):
        prompt_messages = [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": [
                {"type": "text", "text": "Example of the expected output format:"},
                {"type": "text", "text": FEW_SHOT_EXAMPLE_OUTPUT},
                {"type": "text", "text": "Now analyze these two real images:"},
                {"type": "image", "image": image_before},
                {"type": "image", "image": image_after},
            ]},
        ]

        for attempt in range(max_retries + 1):
            text = processor.apply_chat_template(prompt_messages, tokenize=False,
                                                    add_generation_prompt=True)
            image_inputs, _ = process_vision_info(prompt_messages)
            inputs = processor(text=[text], images=image_inputs,
                                padding=True, return_tensors="pt").to(model.device)

            output_ids = model.generate(**inputs, max_new_tokens=256,
                                          temperature=0.1, do_sample=False)
            raw_output = processor.batch_decode(output_ids, skip_special_tokens=True)[0]

            try:
                claim = extract_json(raw_output)
                is_valid, error = validate_claim(claim)
                if is_valid:
                    return {"status": "ok", "claim": claim, "attempts": attempt + 1}
                else:
                    # Corrective retry: tell the model what was wrong
                    prompt_messages.append({"role": "assistant", "content": raw_output})
                    prompt_messages.append({"role": "user", "content":
                        f"That was invalid: {error}. Respond again with ONLY the corrected JSON."})
            except (ValueError, json.JSONDecodeError) as e:
                prompt_messages.append({"role": "assistant", "content": raw_output})
                prompt_messages.append({"role": "user", "content":
                    f"That was not valid JSON ({e}). Respond again with ONLY the JSON object."})

        return {"status": "parse_failed", "raw_output": raw_output, "attempts": max_retries + 1}
""")


# ============================================================
# SUMMARY
# ============================================================
print("=" * 60)
print("LESSON 7 SUMMARY")
print("=" * 60)
print("""
What you built (all tested above, no GPU needed):
  1. A system prompt that forbids explanation text and defines the
     exact schema, with a few-shot example
  2. extract_json() -- pulls JSON out of messy model output
     (markdown fences, stray text) defensively
  3. validate_claim() -- checks the parsed claim against the schema
     Student 3's gate will expect
  4. A retry strategy: corrective retry -> plain retry -> give up and
     record as parse_failed (a distinct, trackable outcome)
  5. The actual model-calling function (get_claim) to run in Colab

What ships to Student 3: the `claim` dict from a "status": "ok"
result -- five categorical fields, no invented precision, ready for
the gate to check against Student 1's Evidence Card.

Next lesson (Lesson 8, whenever ready): Student 3's side of this --
the actual deterministic verification gate logic that checks a claim
like this against real Evidence Card numbers, plus how to compute the
hallucination-rate and risk-coverage metrics for your report.
""")