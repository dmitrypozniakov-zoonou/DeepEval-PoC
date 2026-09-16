import argparse
import time

from playwright.sync_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


DEBRA_URL = "https://www.debra.org.uk/"


def get_bot_reply_after_question(event, question):
    if not isinstance(event, dict):
        return None

    if event.get("type") != "onMessagesChange":
        return None

    messages = (event.get("props") or {}).get("value") or []

    if not isinstance(messages, list):
        return None

    question = question.strip()

    # Find our user message in conversation history
    user_index = None

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue

        message_type = message.get("type") or message.get("role")
        text = message.get("text")

        if (
            message_type == "user"
            and isinstance(text, str)
            and text.strip() == question
        ):
            user_index = index

    if user_index is None:
        return None

    # Find the latest bot message after our question
    reply = None

    for message in messages[user_index + 1:]:
        if not isinstance(message, dict):
            continue

        message_type = message.get("type") or message.get("role")
        text = message.get("text")

        if (
            message_type in ("bot", "assistant")
            and isinstance(text, str)
            and text.strip()
        ):
            reply = text.strip()

    return reply


def ask_debra(
    question: str,
    *,
    headless: bool = False,
    timeout_seconds: int = 90,
) -> str:

    events = []

    def capture_event(data):
        events.append(data)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)

        try:
            context = browser.new_context()
            page = context.new_page()

            # Useful diagnostic:
            # if DEBRA navigates, we will actually see it.
            page.on(
                "framenavigated",
                lambda frame: (
                    print(f"NAVIGATION: {frame.url}")
                    if frame == page.main_frame
                    else None
                ),
            )

            # Python callback available to browser JS.
            page.expose_function(
                "__captureChatbotEvent",
                capture_event,
            )

            # This listener is installed again after every navigation.
            page.add_init_script(
                """
                window.addEventListener("message", (event) => {
                    if (
                        event.origin === "https://static.chatbotkit.com"
                        && window.__captureChatbotEvent
                    ) {
                        window.__captureChatbotEvent(event.data);
                    }
                });
                """
            )

            print("Opening DEBRA...")

            page.goto(
                DEBRA_URL,
                wait_until="load",
                timeout=60_000,
            )

            try:
                page.get_by_role(
                    "button",
                    name="Reject",
                    exact=True,
                ).click(timeout=5_000)
            except PlaywrightTimeoutError:
                pass

            # Give cookie handling / page scripts time to settle.
            page.wait_for_timeout(2000)

            # Wait until ChatBotKit SDK is genuinely ready.
            page.wait_for_function(
                """
                () => {
                    const widget =
                        document.querySelector("chatbotkit-widget");

                    return Boolean(
                        widget &&
                        widget.ready &&
                        typeof widget.sendMessage === "function"
                    );
                }
                """,
                timeout=45_000,
            )

            print("ChatBotKit ready.")
            print(f"Sending: {question}")

            # IMPORTANT:
            # This evaluate does NOT wait for the chatbot response.
            # It only sends the message and finishes immediately.
            for attempt in range(3):
                try:
                    page.evaluate(
                        """
                        (question) => {
                            const widget =
                                document.querySelector(
                                    "chatbotkit-widget"
                                );

                            widget.open = true;

                            widget.sendMessage({
                                text: question,
                                hidden: false,
                                respond: true
                            });
                        }
                        """,
                        question.strip(),
                    )

                    break

                except PlaywrightError as error:
                    if (
                        "Execution context was destroyed"
                        not in str(error)
                        or attempt == 2
                    ):
                        raise

                    print(
                        "Page navigated while sending. "
                        "Waiting and retrying..."
                    )

                    page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=30_000,
                    )

                    page.wait_for_timeout(1500)

                    page.wait_for_function(
                        """
                        () => {
                            const widget =
                                document.querySelector(
                                    "chatbotkit-widget"
                                );

                            return Boolean(
                                widget &&
                                widget.ready &&
                                typeof widget.sendMessage === "function"
                            );
                        }
                        """,
                        timeout=45_000,
                    )

            print("Question sent. Waiting for response...")

            deadline = time.time() + timeout_seconds

            latest_reply = None
            last_change = None

            while time.time() < deadline:

                # This also lets Playwright process browser events.
                page.wait_for_timeout(250)

                for event in events:
                    reply = get_bot_reply_after_question(
                        event,
                        question,
                    )

                    if reply and reply != latest_reply:
                        latest_reply = reply
                        last_change = time.time()

                # ChatBotKit may stream/update the message.
                # Treat it as finished after text stops changing.
                if (
                    latest_reply
                    and last_change
                    and time.time() - last_change >= 2.5
                ):
                    return latest_reply

            print("\nLAST CHATBOT EVENTS:")

            for event in events[-5:]:
                print(event)

            raise TimeoutError(
                "Chatbot response was not captured "
                f"within {timeout_seconds} seconds."
            )

        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "question",
        nargs="?",
        default="What causes EB?",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
    )

    args = parser.parse_args()

    response = ask_debra(
        args.question,
        headless=args.headless,
    )

    print("\n--- DEBRA RESPONSE ---")
    print(response)