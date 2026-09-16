import re
import time

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


GWR_URL = "https://www.gwr.com/help-and-support/contact-us/chat"


def extract_gwr_response(chat_text: str, question: str) -> str:
    # Everything before the user's last question is not part of the answer
    question_pos = chat_text.rfind(question)

    if question_pos != -1:
        response = chat_text[
            question_pos + len(question):
        ].strip()
    else:
        response = chat_text.strip()

    # Remove chatbot UI/footer text
    footer_markers = [
        "ebcss-user hidden Input",
        "Powered by",
        "Why didn't you like the message?",
        "Send feedback",
        "Skip",
    ]

    for marker in footer_markers:
        marker_pos = response.find(marker)

        if marker_pos != -1:
            response = response[:marker_pos].strip()

    return response


def ask_gwr(
    question: str,
    *,
    headless: bool = False,
    timeout_seconds: int = 60,
) -> str:

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)

        try:
            context = browser.new_context()
            page = context.new_page()

            print("Opening GWR...")

            page.goto(
                GWR_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )

            # Main website cookies
            try:
                page.get_by_role(
                    "button",
                    name=re.compile("Accept all", re.I),
                ).click(timeout=5_000)
            except PlaywrightTimeoutError:
                pass

            # Close any popup/modal on the page
            try:
                page.get_by_role(
                    "button",
                    name="Close",
                    exact=True,
                ).click(timeout=3_000)
            except PlaywrightTimeoutError:
                pass

            # Open chatbot
            page.get_by_role(
                "button",
                name="Chat Button",
            ).click(timeout=15_000)

            chat_iframe = page.locator(
                'iframe[title="Chatbot Window"]'
            )
            chat_iframe.wait_for(state="visible", timeout=15_000)

            chat = page.frame_locator(
                'iframe[title="Chatbot Window"]'
            )

            # Chatbot privacy/terms
            try:
                chat.get_by_role(
                    "button",
                    name="Accept",
                    exact=True,
                ).click(timeout=10_000)
            except PlaywrightTimeoutError:
                pass

            textbox = chat.get_by_role(
                "textbox",
                name=re.compile("Type or speak using the", re.I),
            )

            # The iframe may be attached before the expanded chat panel is
            # ready. Wait for an interactable input before sending anything.
            textbox.wait_for(state="visible", timeout=15_000)
            textbox.click(timeout=15_000)

            # Izzy sends an onboarding sequence after the panel opens. Do not
            # submit a real question until the chat explicitly invites it.
            print("Waiting for Izzy to finish the welcome message...")
            ready_deadline = time.time() + 30

            while time.time() < ready_deadline:
                chat_text = chat.locator("body").inner_text()

                if "How can I help you today?" in chat_text:
                    break

                page.wait_for_timeout(500)
            else:
                raise TimeoutError(
                    "GWR chatbot did not finish its welcome message in time."
                )

            # Capture chat content BEFORE question
            before = chat.locator("body").inner_text()

            print(f"Sending: {question}")

            textbox.fill(question)
            textbox.press("Enter")

            print("Question sent. Waiting for response...")

            # First wait until the submitted question appears in the chat
            page.wait_for_timeout(2000)

            after_question = chat.locator("body").inner_text()

            # Now wait for ANOTHER meaningful change,
            # which should be Izzy's response
            deadline = time.time() + timeout_seconds

            latest_text = after_question
            last_change = None
            response_started = False

            while time.time() < deadline:
                page.wait_for_timeout(500)

                current = chat.locator("body").inner_text()

                if current != latest_text:
                    latest_text = current
                    last_change = time.time()
                    response_started = True

                # Once the response has started,
                # wait until streaming/text changes stop
                if (
                    response_started
                    and last_change is not None
                    and time.time() - last_change >= 4
                ):
                    break
            else:
                raise TimeoutError(
                    "GWR chatbot response did not complete in time."
                )

            response = extract_gwr_response(
                latest_text,
                question,
            )

            if not response:
                raise RuntimeError(
                    "No chatbot response text was captured."
                )

            return response

        finally:
            browser.close()


if __name__ == "__main__":
    response = ask_gwr(
        "How do I claim Delay Repay?"
    )

    print("\n--- GWR RESPONSE ---")
    print(response)
