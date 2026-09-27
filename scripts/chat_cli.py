# scripts/chat_cli.py

import sys
from pathlib import Path
import uuid

# Fix Python path to resolve src modules from any working directory
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.agent.graph import get_agent
from src.utils.logger import get_logger

# Ensure Windows stdout supports UTF-8 and Arabic/emojis
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

logger = get_logger("ChatCLI")


def run_chat_cli():
    """
    Launches an interactive multi-turn chat session with the IT Cybx Live Agent.
    """
    print("\n" + "=" * 60)
    print("       🤖  IT CYBX LIVE BOT - INTERACTIVE CHAT CLI          ")
    print("=" * 60)
    print("Commands:")
    print("  • Type your question in English or Arabic to chat.")
    print("  • '/lang en' or '/lang ar' to switch conversation language.")
    print("  • '/clear' to reset conversation memory.")
    print("  • '/exit' or 'quit' to end the session.")
    print("=" * 60 + "\n")

    agent = get_agent()
    thread_id = f"cli_{uuid.uuid4().hex[:8]}"
    current_lang = "en"
    history = []  # local {"role", "content"} turns; the graph itself is stateless

    print(f"Session started! [Thread ID: {thread_id}] [Auto Language Detection: ON]\n")

    while True:
        try:
            user_input = input("You > ").strip()

            if not user_input:
                continue

            # Command handling
            if user_input.lower() in ["/exit", "exit", "quit", "q"]:
                print("\n👋 Goodbye! Ending IT Cybx chat session.\n")
                break

            if user_input.lower() == "/clear":
                thread_id = f"cli_{uuid.uuid4().hex[:8]}"
                history = []
                print(f"\n🔄 Conversation memory cleared. [New Thread ID: {thread_id}]\n")
                continue

            if user_input.lower().startswith("/lang"):
                parts = user_input.split()
                if len(parts) > 1 and parts[1].lower() in ["en", "ar", "auto"]:
                    current_lang = parts[1].lower()
                    print(f"\n🌐 Language preference set to: {current_lang.upper()}\n")
                else:
                    print("\n⚠️ Usage: '/lang en', '/lang ar', or '/lang auto'\n")
                continue

            # Send turn to LangGraph agent with auto language detection
            print("\n🤖 IT Cybx Bot is thinking...\n")
            response = agent.chat(
                user_message=user_input,
                thread_id=thread_id,
                language=current_lang,
                history=history,
            )
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})

            print(f"[IT Cybx Bot]:\n{response}\n")
            print("-" * 60 + "\n")

        except (KeyboardInterrupt, EOFError):
            print("\n👋 Session interrupted. Goodbye!\n")
            break
        except Exception as e:
            logger.error(f"Error during chat turn: {e}")
            print(f"\n❌ An error occurred: {e}\n")


if __name__ == "__main__":
    run_chat_cli()
