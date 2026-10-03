"""Wires the six steps into a LangGraph graph, and a terminal chat to try it.

    python -m app.graph.build --cli
    python -m app.graph.build --cli --language ar

One graph run = one visitor message. The conversation state is passed in
and returned each time; saving it between messages is the API's job.
"""

import argparse
import asyncio
import uuid
from typing import AsyncIterator

from langgraph.graph import END, START, StateGraph

from app.graph import nodes
from app.graph.state import ChatState, new_state

GREETING = {
    "en": "Hi! I'm the IT Cybx assistant. What's your name?",
    "ar": "أهلًا! أنا مساعد IT Cybx. ما اسمك؟",
}


def build():
    graph = StateGraph(ChatState)
    graph.add_node("router", nodes.router)
    graph.add_node("greet", nodes.greet)
    graph.add_node("qualify", nodes.qualify)
    graph.add_node("capture_lead", nodes.capture_lead)
    graph.add_node("contact", nodes.contact)
    graph.add_node("answer", nodes.answer)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router", nodes.next_step,
        ["greet", "qualify", "capture_lead", "contact", "answer"],
    )
    for step in ("qualify", "capture_lead", "contact"):
        graph.add_edge(step, "answer")
    graph.add_edge("greet", END)
    graph.add_edge("answer", END)
    return graph.compile()


chat_graph = build()


async def run_turn(state: ChatState, message: str) -> AsyncIterator[dict]:
    """Process one visitor message.

    Yields events as they happen: {"type": "token", "text"}, {"type": "error", ...},
    then finally {"type": "state", "state": <the updated ChatState>}.
    """
    final = None
    async for mode, chunk in chat_graph.astream(
        {**state, "user_message": message}, stream_mode=["custom", "values"]
    ):
        if mode == "custom":
            yield chunk
        else:
            final = chunk
    yield {"type": "state", "state": final}


async def _cli(language: str) -> None:
    state = new_state(str(uuid.uuid4()), language)
    print(f"Bot: {GREETING[language]}   (type 'quit' to stop)\n")
    while True:
        message = await asyncio.to_thread(input, "You: ")
        if message.strip().lower() in ("quit", "exit"):
            break
        if not message.strip():
            continue
        print("Bot: ", end="", flush=True)
        async for event in run_turn(state, message):
            if event["type"] == "token":
                print(event["text"], end="", flush=True)
            elif event["type"] == "error":
                print(event["message"], end="")
            elif event["type"] == "state":
                state = event["state"]
        print()
        for button in state.get("actions") or []:
            print(f"   [{button['label']}] {button['url']}")
        lead = {k: v for k, v in state["lead"].items() if v}
        print(f"   (name: {state.get('name') or '-'} | lead: {lead or '-'} | status: {state['lead_status']})\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the bot in the terminal.")
    parser.add_argument("--cli", action="store_true", required=True)
    parser.add_argument("--language", default="en", choices=["en", "ar"])
    args = parser.parse_args()
    asyncio.run(_cli(args.language))


if __name__ == "__main__":
    main()
