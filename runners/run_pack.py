import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path

logging.getLogger("google_genai.models").setLevel(logging.ERROR)


ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config

from deepeval.metrics import AnswerRelevancyMetric, GEval
from deepeval.models import GeminiModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

from clients.registry import CLIENTS
from test_data.registry import TEST_PACKS


JUDGE_MODEL = GeminiModel(
    model=config.GEMINI_JUDGE_MODEL,
    api_key=config.GOOGLE_API_KEY,
)


def evaluate_with_retry(metric, test_case, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            metric.measure(test_case)
            return

        except Exception as error:
            message = str(error)

            retryable = (
                "429" in message
                or "503" in message
                or "RESOURCE_EXHAUSTED" in message
                or "UNAVAILABLE" in message
            )

            if not retryable or attempt == attempts:
                raise

            wait_seconds = 10 * attempt

            print(
                f"Judge unavailable. "
                f"Retrying evaluation in {wait_seconds}s..."
            )

            time.sleep(wait_seconds)


def build_metric(test_type, client_name, chatbot_name):
    if test_type == "relevancy":
        return AnswerRelevancyMetric(
            threshold=0.7,
            model=JUDGE_MODEL,
            include_reason=True,
            verbose_mode=False,
            async_mode=False,
        )

    if test_type == "out_of_scope":
        return GEval(
            name="Out of Scope Handling",
            criteria=(
                f"Evaluate whether {chatbot_name}, the assistant for "
                f"{client_name}, recognises that the request is outside its "
                "supported scope. It should avoid inventing an answer and "
                "should respond appropriately or redirect the user to its "
                "supported scope."
            ),
            evaluation_params=[
                SingleTurnParams.INPUT,
                SingleTurnParams.ACTUAL_OUTPUT,
            ],
            threshold=0.7,
            model=JUDGE_MODEL,
            async_mode=False,
        )

    raise ValueError(f"Unknown test type: {test_type}")


def write_html_report(results, client_name, report_path):
    totals = {
        "PASS": sum(result["status"] == "PASS" for result in results),
        "FAIL": sum(result["status"] == "FAIL" for result in results),
        "ERROR": sum(result["status"] == "ERROR" for result in results),
    }

    cards = []

    for result in results:
        score = (
            f" — {result['score']:.2f}"
            if result["score"] is not None
            else ""
        )
        cards.append(
            f"""
            <article class="case {result['status'].lower()}">
              <h2>{escape(result['name'])} <span>{result['status']}{score}</span></h2>
              <h3>Question</h3>
              <pre>{escape(result['question'])}</pre>
              <h3>Actual response</h3>
              <blockquote>{escape(result['response'] or 'No response captured.')}</blockquote>
              <h3>Reason</h3>
              <blockquote>{escape(result['reason'] or 'No reason provided.')}</blockquote>
            </article>
            """
        )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(client_name)} AI Chatbot Evaluation</title>
  <style>
    body {{ max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1f2937; background: #f8fafc; font: 16px/1.55 Arial, sans-serif; }}
    h1 {{ margin-bottom: 4px; }}
    .generated {{ margin-top: 0; color: #64748b; }}
    .summary {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 24px 0; }}
    .summary div {{ min-width: 100px; padding: 14px; background: white; border-radius: 8px; box-shadow: 0 1px 3px #cbd5e1; }}
    .case {{ margin: 20px 0; padding: 24px; background: white; border-left: 6px solid #64748b; border-radius: 8px; box-shadow: 0 1px 3px #cbd5e1; }}
    .case.pass {{ border-color: #16a34a; }} .case.fail {{ border-color: #dc2626; }} .case.error {{ border-color: #d97706; }}
    h2 {{ margin-top: 0; }} h2 span {{ font-size: .8em; color: #475569; }} h3 {{ margin-bottom: 4px; font-size: 1em; }}
    pre, blockquote {{ margin: 0; padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; background: #f1f5f9; border-radius: 4px; }}
    blockquote {{ border-left: 3px solid #94a3b8; }}
  </style>
</head>
<body>
  <h1>{escape(client_name)} AI Chatbot Evaluation</h1>
  <p class="generated">Generated {generated_at}</p>
  <section class="summary" aria-label="Summary">
    <div>Total: <strong>{len(results)}</strong></div>
    <div>Passed: <strong>{totals['PASS']}</strong></div>
    <div>Failed: <strong>{totals['FAIL']}</strong></div>
    <div>Errors: <strong>{totals['ERROR']}</strong></div>
  </section>
  {''.join(cards)}
</body>
</html>
"""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"\nHTML report written to: {report_path}")


def run_pack(client, test_cases, report_path):
    results = []
    ask_chatbot = client["ask"]
    client_name = client["name"]
    chatbot_name = client["chatbot"]

    for case in test_cases:
        print("\n" + "=" * 80)
        print(f"TEST: {case['name']}")
        print("=" * 80)

        question = case["question"]
        response = ""

        print(f"\nQUESTION:\n{question}")

        try:
            response = ask_chatbot(
                question,
                headless=False,
            )

            print(f"\nANSWER:\n{response}")

            test_case = LLMTestCase(
                input=question,
                actual_output=response,
            )

            metric = build_metric(
                case["type"],
                client_name,
                chatbot_name,
            )

            evaluate_with_retry(metric, test_case)

            score = metric.score
            reason = metric.reason
            passed = metric.is_successful()
            status = "PASS" if passed else "FAIL"

            print("\nRESULT:")
            print(f"Score:     {score:.2f}")
            print(f"Threshold: {metric.threshold}")
            print(f"Status:    {status}")
            print(f"Reason:    {reason}")

            results.append(
                {
                    "name": case["name"],
                    "question": question,
                    "response": response,
                    "reason": reason,
                    "score": score,
                    "status": status,
                }
            )

        except Exception as error:
            print("\nRESULT:")
            print("Status: ERROR")
            print(f"Reason: {error}")
            results.append(
                {
                    "name": case["name"],
                    "question": question,
                    "response": response,
                    "reason": str(error),
                    "score": None,
                    "status": "ERROR",
                }
            )

    write_html_report(results, client_name, report_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--client",
        required=True,
        choices=CLIENTS.keys(),
    )
    args = parser.parse_args()

    client = CLIENTS[args.client]
    test_cases = TEST_PACKS[args.client]
    report_path = ROOT / "reports" / f"{args.client}_report.html"

    run_pack(client, test_cases, report_path)
