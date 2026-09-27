# src/agent/graph.py

from typing import TypedDict, Annotated, Sequence, Literal, Optional, List, Dict
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
from langchain_mistralai import ChatMistralAI
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from src.config.settings import MISTRAL_API_KEY, LLM_MODEL
from src.tools.faq_tool import search_knowledge_base
from src.agent.prompts_en import SYSTEM_PROMPT_EN
from src.agent.prompts_ar import SYSTEM_PROMPT_AR
from src.utils.logger import get_logger

logger = get_logger("AgentGraph")


class AgentState(TypedDict):
    """LangGraph state schema representing conversation messages and metadata."""
    messages: Annotated[Sequence[BaseMessage], add_messages]
    language: str  # 'en' or 'ar'


class ItCybxAgent:
    """
    Orchestrates the LangGraph agent for IT Cybx with tool calling,
    multi-turn memory checkpointing, and bilingual support.
    """

    def __init__(self):
        logger.info(f"Initializing ChatMistralAI (model: '{LLM_MODEL}')...")
        self.llm = ChatMistralAI(
            model=LLM_MODEL,
            api_key=MISTRAL_API_KEY,
            temperature=0.1,  # Low temperature for factual precision
            # max_retries=0: retries are handled entirely by the explicit,
            # bounded loop in _call_model below. Stacking the SDK's own
            # retry layer on top of that loop made the worst-case duration
            # of a single call unbounded and able to run well past the
            # API-level request deadline (src/api/main.py) in the
            # background, since a blocking thread can't be cancelled once
            # started. One retry mechanism, with a known worst-case time.
            max_retries=0,
            timeout=12,
        )

        # Single registered tool: FAQ knowledge-base search
        self.tools = [search_knowledge_base]
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # Build and compile graph. No checkpointer: SessionStore (see
        # src/memory/session_store.py) is the single source of truth for
        # multi-turn history, replayed into `messages` on every call. A
        # LangGraph checkpointer here would be redundant, in-process-only
        # state that (a) doesn't survive restarts or multiple workers and
        # (b) accumulates one orphaned checkpoint thread per turn forever.
        self.graph = self._build_graph()
        logger.info("LangGraph IT Cybx Agent compiled successfully.")

    def _call_model(self, state: AgentState) -> dict:
        """Invokes Mistral LLM with system prompt and message history."""
        import time
        messages = list(state["messages"])
        language = state.get("language", "en")

        # Select matching system prompt
        system_prompt = SYSTEM_PROMPT_AR if language == "ar" else SYSTEM_PROMPT_EN

        # Ensure SystemMessage is at the top of context
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=system_prompt)] + messages
        else:
            # Update system prompt if language changed
            messages[0] = SystemMessage(content=system_prompt)

        # Bounded retry with backoff on 429 rate limits. Worst case here is
        # ~3 * 12s (timeout per attempt) + ~3s (backoff sleeps) = ~39s, kept
        # deliberately under the API layer's 45s request deadline
        # (src/api/main.py CHAT_REQUEST_DEADLINE_SECONDS) so a call that's
        # genuinely going to fail finishes failing before that deadline
        # fires, instead of continuing to retry in an orphaned background
        # thread after the client has already been told it timed out.
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = self.llm_with_tools.invoke(messages)
                return {"messages": [response]}
            except Exception as e:
                err_str = str(e).lower()
                is_last_attempt = attempt == max_attempts - 1
                if not is_last_attempt and ("429" in err_str or "rate limit" in err_str):
                    wait_time = (attempt + 1) * 1.5
                    logger.warning(f"Mistral 429 rate limit hit. Retrying in {wait_time}s (attempt {attempt + 1}/{max_attempts})...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Error invoking LLM (attempt {attempt + 1}/{max_attempts}): {e}")
                    raise

    def _should_continue(self, state: AgentState) -> Literal["tools", "__end__"]:
        """Determines whether to call a tool or finish the turn."""
        last_message = state["messages"][-1]

        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            logger.info(f"LLM decided to call {len(last_message.tool_calls)} tool(s): {[tc['name'] for tc in last_message.tool_calls]}")
            return "tools"
        return END

    def _build_graph(self):
        """Constructs the state machine graph nodes and edges."""
        workflow = StateGraph(AgentState)

        # 1. Define Nodes
        workflow.add_node("agent", self._call_model)
        workflow.add_node("tools", ToolNode(self.tools))

        # 2. Define Edges
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "tools": "tools",
                END: END,
            }
        )
        workflow.add_edge("tools", "agent")

        # 3. Compile stateless: each invoke() call is self-contained,
        # given a full message list by chat() below.
        return workflow.compile()

    @staticmethod
    def _clean_closing_filler(text: str) -> str:
        """Strips out repetitive closing sales pitches, CTAs, and markdown divider dashes."""
        import re
        # 1. Strip trailing sales pitch/CTAs (English and Arabic)
        patterns = [
            r"(?:\n+|^)(?:[-*—_]{2,}\s*)?\s*(?:Would you like to explore|Let me know if you(?:'re|’re| are) interested|How would you like to proceed|How can I assist you further|Feel free to reach out).*$",
            r"(?:\n+|^)(?:[-*—_]{2,}\s*)?\s*(?:هل ترغب في استكشاف|أخبرني إذا كنت مهتماً|كيف يمكنني مساعدتك أكثر|هل تود).*$",
        ]
        cleaned = text
        for p in patterns:
            cleaned = re.sub(p, "", cleaned, flags=re.DOTALL | re.IGNORECASE)

        # 2. Strip standalone horizontal divider lines (e.g. ---, ___, *** on their own line)
        cleaned = re.sub(r'^[ \t]*(?:-[ \t]*){3,}$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'^[ \t]*(?:_[ \t]*){3,}$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'^[ \t]*(?:\*[ \t]*){3,}$', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'^[ \t]*(?:---|\*\*\*|___)(?:[ \t]+(?:---|\*\*\*|___))*[ \t]*$', '', cleaned, flags=re.MULTILINE)

        # 3. Collapse excess consecutive blank lines
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)

        return cleaned.strip()

    def chat(
        self,
        user_message: str,
        thread_id: str = "default_session",
        language: str = "auto",
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Processes a user turn and returns the final assistant response string.
        Automatically detects Arabic script if language is 'auto'.

        `history` (prior turns as {"role", "content"} dicts, e.g. loaded from
        the durable SessionStore) is replayed into the message list on every
        call, since the graph itself is stateless. `thread_id` is used only
        for logging \u2014 it has no effect on model context.
        """
        # Auto-detect language if requested or if Arabic characters exist
        if language == "auto":
            has_arabic = any('\u0600' <= char <= '\u06FF' or '\u0750' <= char <= '\u077F' for char in user_message)
            detected_lang = "ar" if has_arabic else "en"
        else:
            detected_lang = language.lower()

        messages: List[BaseMessage] = []
        for turn in (history or []):
            role = turn.get("role")
            content = turn.get("content", "")
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=user_message))
        inputs = {"messages": messages, "language": detected_lang}

        logger.info(f"Processing chat turn for thread '{thread_id}' [lang={detected_lang}, len={len(user_message)} chars]")
        output = self.graph.invoke(inputs)
        
        last_msg = output["messages"][-1]
        raw_content = last_msg.content
        return self._clean_closing_filler(raw_content) if isinstance(raw_content, str) else raw_content


# Reusable singleton instance
_agent_instance: ItCybxAgent = None


def get_agent() -> ItCybxAgent:
    """Returns or creates the singleton ItCybxAgent instance."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = ItCybxAgent()
    return _agent_instance


if __name__ == "__main__":
    agent = get_agent()
    print("\n=======================================================")
    print("             LANGGRAPH AGENT TEST RUN                  ")
    print("=======================================================")
    
    response = agent.chat("Hi! Can you tell me what the Growth Audit is and how much it costs?", thread_id="test_run_1", language="en")
    print("\n[BOT RESPONSE]:\n" + response + "\n")
