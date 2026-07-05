import asyncio
import threading
import time
import traceback
from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
from queue import Queue

from langchain.agents import create_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import MemorySaver

from ian.config import GOOGLE_API_KEY
from ian.domain.injection import INJECTION_REJECTION_MSG, detect_prompt_injection
from ian.domain.urls import URL_PLACEHOLDER, validate_urls_in_response
from ian.services.agent.callbacks import (
    DiscordLogCallbackHandler,
    extract_text_from_output,
)
from ian.services.agent.logging import add_log, eprint, start_log_processor
from ian.services.agent.prompt import SYS_PROMPT
from ian.services.agent.sessions import (
    clear_session_if_timeout,
    get_session_agent_and_channel,
    reset_session_agent,
    sessions_lock,
    set_session_agent,
    upsert_session,
)
from ian.services.agent.usage import check_and_update_usage
from ian.services.member_store import lookup_member_by_platform


def _unwrap_exception(exc: BaseException) -> BaseException:
    """遞迴展開 ExceptionGroup，取得實際的子例外。"""
    if isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
        return _unwrap_exception(exc.exceptions[0])
    return exc


def _validate_agent_response_urls(response: str, tool_results: list[str]) -> str:
    return validate_urls_in_response(response, tool_results, prompt_text=SYS_PROMPT)


loop_agent = None
dispatcher_started = False
dispatcher_lock = threading.Lock()

"""
MCP tools with single agent executor
"""
request_queue: Queue[tuple[str, str, str, str, float, str, str, str, Future]] = Queue()


MCP_SERVER_URL = "http://localhost:5191/mcp"

mcp_config = {
    "Retriever": {
        "url": MCP_SERVER_URL,
        "transport": "streamable_http",
    },
}


async def run_agentic_workflow():
    """Main event loop: dequeue requests and invoke the LangGraph agent."""
    client = MultiServerMCPClient(mcp_config)
    google_api_key = GOOGLE_API_KEY
    if not google_api_key:
        print("Error: GOOGLE_API_KEY not found in environment variables.")
    primary_llm = ChatGoogleGenerativeAI(
        model="gemini-3-flash-preview",
        google_api_key=google_api_key,
    )
    fallback_llm = ChatGoogleGenerativeAI(
        model="gemini-3.1-flash-lite-preview",
        google_api_key=google_api_key,
    )
    llm = primary_llm.with_fallbacks([fallback_llm])
    tools = await client.get_tools()
    try:
        while True:
            session_id, user_name, question, user_role, timestamp, channel_id, platform, account_id, fut = (
                await asyncio.to_thread(request_queue.get)
            )
            if session_id is None:
                break

            # Log 使用者訊息
            add_log("USER_MESSAGE",
                    user_name=user_name,
                    user_role=str(user_role),
                    message=question,
                    session_id=session_id,
                    platform=platform)

            # 動態產生時間資訊
            tz_taipei = timezone(timedelta(hours=8))
            dt_object = datetime.fromtimestamp(timestamp, tz=tz_taipei)
            nowdatetime = dt_object.strftime("%Y-%m-%d %H:%M:%S")
            nowday = dt_object.strftime("%A")

            current_timestamp = time.time()  # Get current time for timeout logic

            with sessions_lock:
                clear_session_if_timeout(
                    session_id, current_timestamp
                )  # Check before processing

                session, was_created = upsert_session(
                    session_id,
                    user_name,
                    user_role,
                    channel_id,
                    current_timestamp,
                )
                if was_created:
                    add_log("SESSION", action="Created", user_name=user_name, session_id=session_id)

                # Initialize or re-initialize agent if needed
                if session.get("agent") is None:
                    memory = MemorySaver()
                    agent = create_agent(
                        model=llm,
                        tools=tools,
                        system_prompt=SYS_PROMPT,
                        checkpointer=memory,
                    )
                    set_session_agent(session_id, agent, memory)
                    print(
                        f"Created agent for {session_id} ({user_name}) session in {nowdatetime}"
                    )

            # Agent invocation (outside the lock for long-running I/O)
            try:
                # Safely get agent_obj after ensuring session exists and agent is initialized
                with sessions_lock:
                    agent_obj, channel_id = get_session_agent_and_channel(session_id)

                user_message = (
                    f"[Name:{user_name} Role:{user_role}] Message: {question}"
                )

                # 查找社員資料，注入 personal_prompt / note / subscribe
                member_info = lookup_member_by_platform(platform, account_id)
                personal_prompt = str(member_info.get("personal_prompt", "")).strip() if member_info else ""
                member_note = str(member_info.get("note", "")).strip() if member_info else ""
                subscribe_info = str(member_info.get("subscribe", "")).strip() if member_info else ""

                sys_content = f"Current time in Taiwan：{nowdatetime}, {nowday}。User name：{user_name}, User role：{user_role}, Channel ID: {channel_id}, Platform: {platform}, Account ID: {account_id}"
                if personal_prompt:
                    sys_content += f"\nUser personality：{personal_prompt}"
                if member_note:
                    sys_content += f"\nUser note：{member_note}"
                if subscribe_info:
                    sys_content += f"\nUser subscribe：{subscribe_info}"

                # 使用 callback handler 追蹤工具呼叫
                log_callback = DiscordLogCallbackHandler()

                MAX_URL_RETRIES = 2  # 最多嘗試次數（含首次）
                MAX_INVOKE_RETRIES = 3  # ainvoke 失敗時最多重試次數（含首次）
                FAKE_URL_PLACEHOLDER = URL_PLACEHOLDER

                agent_msg = None
                last_invoke_error = None

                for invoke_attempt in range(MAX_INVOKE_RETRIES):
                    if invoke_attempt > 0:
                        # 重建 agent 並重新取得 MCP 工具，以清除損壞的連線/對話歷史
                        root_cause = _unwrap_exception(last_invoke_error) if last_invoke_error else last_invoke_error
                        add_log("RETRY", user_name=user_name, reason=f"Tool 執行錯誤，重試中 ({type(root_cause).__name__}: {root_cause})", attempt=invoke_attempt + 1)
                        print(f"🔄 Tool 執行錯誤，第 {invoke_attempt + 1} 次重試 ({user_name})")
                        try:
                            tools = await client.get_tools()
                        except Exception as mcp_err:
                            print(f"⚠️ MCP 工具重新取得失敗: {mcp_err}，嘗試重建 client")
                            client = MultiServerMCPClient(mcp_config)
                            tools = await client.get_tools()
                        memory = MemorySaver()
                        new_agent = create_agent(
                            model=llm,
                            tools=tools,
                            system_prompt=SYS_PROMPT,
                            checkpointer=memory,
                        )
                        with sessions_lock:
                            set_session_agent(session_id, new_agent, memory)
                        agent_obj = new_agent
                        log_callback = DiscordLogCallbackHandler()

                    try:
                        for attempt in range(MAX_URL_RETRIES):
                            if attempt > 0:
                                prev_results = log_callback.tool_results
                                log_callback = DiscordLogCallbackHandler()
                                log_callback.tool_results = prev_results  # 保留上次 tool 回傳的 URL
                                add_log("RETRY", user_name=user_name, reason="URL 驗證失敗，重試中", attempt=attempt + 1)
                                print(f"🔄 URL 驗證失敗，第 {attempt + 1} 次重試 ({user_name})")

                            invoke_sys_content = sys_content
                            if attempt > 0:
                                invoke_sys_content += "\n⚠️ 重要提醒：請勿自行編造或猜測任何網址連結。只使用工具回傳的連結或系統提示中已有的連結。如果沒有確切的連結，請告訴使用者你目前沒有該連結，建議他們聯繫幹部。"

                            agent_msg = await agent_obj.ainvoke(
                                {
                                    "messages": [
                                        {"role": "user", "content": user_message},
                                        {
                                            "role": "system",
                                            "content": invoke_sys_content,
                                        },
                                    ]
                                },
                                config={"configurable": {"thread_id": session_id}, "callbacks": [log_callback]},
                            )
                            messages = agent_msg.get("messages", "⚠️ 回覆解析失敗")
                            raw_content = messages[-1].content  # last response from agent

                            # 處理複雜的回應結構 (Gemini 可能返回 list of dict)
                            if isinstance(raw_content, list):
                                text_parts = []
                                for item in raw_content:
                                    if isinstance(item, dict) and 'text' in item:
                                        text_parts.append(item['text'])
                                    elif isinstance(item, str):
                                        text_parts.append(item)
                                parsed_agent_response = ''.join(text_parts)
                            elif isinstance(raw_content, dict) and 'text' in raw_content:
                                parsed_agent_response = raw_content['text']
                            else:
                                parsed_agent_response = str(raw_content)

                            # 驗證回覆中的 URL 是否來自合法來源，移除 LLM 捏造的連結
                            # 同一 session 內的後續訊息可能不會重新呼叫 tool，
                            # 因此也要從 session history 中的 ToolMessage 提取合法 URL
                            all_tool_texts = list(log_callback.tool_results)
                            for msg in messages:
                                if hasattr(msg, 'type') and msg.type == 'tool':
                                    all_tool_texts.append(extract_text_from_output(msg))
                            parsed_agent_response = _validate_agent_response_urls(
                                parsed_agent_response, all_tool_texts
                            )

                            # 如果沒有捏造的 URL，跳出重試迴圈
                            if FAKE_URL_PLACEHOLDER not in parsed_agent_response:
                                break

                        # ainvoke 成功，跳出外層重試迴圈
                        break

                    except BaseException as invoke_error:
                        if isinstance(invoke_error, (KeyboardInterrupt, SystemExit)):
                            raise
                        last_invoke_error = invoke_error
                        root_cause = _unwrap_exception(invoke_error)
                        add_log("ERROR", error=f"{type(root_cause).__name__}: {root_cause}", context=f"Tool execution for {user_name}")
                        print(f"⚠️ ainvoke 錯誤 (attempt {invoke_attempt + 1}/{MAX_INVOKE_RETRIES}): {type(root_cause).__name__}: {root_cause}")
                        traceback.print_exception(root_cause)
                        if invoke_attempt >= MAX_INVOKE_RETRIES - 1:
                            # 所有重試都失敗，拋出讓外層處理
                            raise

                fut.set_result(parsed_agent_response)

                # Log Agent 回應
                add_log("AGENT_RESPONSE", user_name=user_name, response=parsed_agent_response)

                print(
                    f"✅ Agent 回應給 {user_name} ({user_role}): {parsed_agent_response}..."
                )
            except BaseException as error_msg:
                if isinstance(error_msg, (KeyboardInterrupt, SystemExit)):
                    raise
                # Log 錯誤（展開 ExceptionGroup 以顯示真正的根因）
                root_cause = _unwrap_exception(error_msg)
                add_log("ERROR", error=f"{type(root_cause).__name__}: {root_cause}", context=f"LLM invoke for {user_name}")
                print(f"Error happened on llm invoke: {type(root_cause).__name__}: {root_cause}")
                traceback.print_exception(root_cause)
                # 重置 session，避免殘留的 AIMessage（帶 tool_calls 但無 ToolMessage）
                # 導致後續請求因 INVALID_CHAT_HISTORY 持續失敗
                with sessions_lock:
                    reset_session_agent(session_id, user_name)
                fut.set_result("⚠️ 發生錯誤，請稍後再試。\nError occurred, please try again later.")
    finally:
        if hasattr(client, 'aclose'):
            await client.aclose()


def start_dispatcher(user_name: str, current_time):
    """啟動事件循環線程（event-loop thread），首次呼叫時建立。"""
    global loop_agent, dispatcher_started

    # 確保 log processor 已啟動
    start_log_processor()

    with dispatcher_lock:
        if dispatcher_started:
            return loop_agent
        try:
            loop = asyncio.new_event_loop()
            loop_agent = loop
            t = threading.Thread(target=lambda: loop.run_forever(), daemon=True)
            t.start()
            asyncio.run_coroutine_threadsafe(run_agentic_workflow(), loop)
            print(f"事件循環線程已啟動 (由 {user_name} 觸發)")
            dispatcher_started = True
            return loop_agent
        except Exception as error:
            print(f"Error starting dispatcher: {error}")


async def chat_with_agent(
    session_id: str, user_name: str, question: str, user_role: str,
    timestamp: float, channel_id: str, platform: str = "Discord",
    account_id: str = "",
):
    """公開非同步介面：檢查安全性與用量後，將請求放入佇列。"""
    # 若使用者是社員，用 member_db 中的本名取代平台暱稱
    member = lookup_member_by_platform(platform, account_id)
    if member and member.get("id"):
        user_name = member["id"]

    # Prompt injection guardrail — check before anything else
    if detect_prompt_injection(question):
        add_log("ERROR", error="Prompt injection blocked", context=f"{user_name} ({platform}): {question[:200]}")
        eprint(f"🛡️ Prompt injection blocked from {user_name} ({platform})")
        return INJECTION_REJECTION_MSG

    # Check usage limit before processing
    if not check_and_update_usage(session_id):
        return "😌 已達今日使用上限，明天再來和我聊天吧！\nYou have reached the usage limit for today. Please come back and chat with me tomorrow!"

    fut = Future()
    request_queue.put((session_id, user_name, question, user_role, timestamp, channel_id, platform, account_id, fut))
    return await asyncio.wrap_future(fut)
