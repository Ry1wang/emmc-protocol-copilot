"""
Streamlit Frontend for eMMC RAG Agent

A ChatGPT-like interface for querying eMMC protocol documentation.
"""

import streamlit as st
import httpx
import json
import asyncio
from typing import Dict, Any, List
import os
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="eMMC RAG Agent",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better UI
st.markdown("""
<style>
    .stChatMessage {
        padding: 1rem;
        border-radius: 0.5rem;
        margin-bottom: 1rem;
    }
    .user-message {
        background-color: #e3f2fd;
    }
    .assistant-message {
        background-color: #f5f5f5;
    }
    .code-block {
        background-color: #1e1e1e;
        color: #d4d4d4;
        padding: 1rem;
        border-radius: 0.5rem;
        overflow-x: auto;
    }
    .source-tag {
        display: inline-block;
        background-color: #e0e0e0;
        padding: 0.2rem 0.5rem;
        border-radius: 0.3rem;
        margin: 0.2rem;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "api_url" not in st.session_state:
    st.session_state.api_url = "http://127.0.0.1:8000"

# Sidebar configuration
with st.sidebar:
    st.title("⚙️ 配置")
    
    # API Configuration
    st.subheader("API 设置")
    api_url = st.text_input(
        "API 地址",
        value=st.session_state.api_url,
        help="FastAPI 后端服务地址"
    )
    st.session_state.api_url = api_url
    
    # Retrieval Configuration
    st.subheader("检索参数")
    top_k = st.slider(
        "Top-K",
        min_value=1,
        max_value=20,
        value=8,
        help="检索的文档数量（推荐 8-10 以提高召回率）"
    )
    
    # Typing speed control
    st.subheader("显示效果")
    typing_speed = st.slider(
        "打字速度",
        min_value=0,
        max_value=200,
        value=50,
        step=10,
        help="控制文字显示速度（毫秒）。0 = 最快，200 = 最慢"
    )
    
    # Clear chat button
    if st.button("🗑️ 清空对话", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    
    # System status
    st.divider()
    st.subheader("📊 系统状态")
    
    # Health check
    try:
        response = httpx.get(f"{api_url}/health", timeout=2.0)
        if response.status_code == 200:
            st.success("✅ API 服务正常")
        else:
            st.error("❌ API 服务异常")
    except:
        st.error("❌ 无法连接到 API")
    
    st.caption(f"会话消息数: {len(st.session_state.messages)}")

# Main chat interface
st.title("🔍 eMMC RAG Agent")
st.caption("基于 RAG 的 eMMC 协议智能问答系统")

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
        # Display sources if available
        if "sources" in message and message["sources"]:
            with st.expander("📚 参考来源"):
                for source in message["sources"]:
                    st.markdown(f"""
                    - **Page {source['page_num']}** ({source['content_type']})
                    {f"  - *{source['metadata'].get('caption', '')}*" if source['metadata'].get('caption') else ''}
                    """)
        
        # Display generated code if available
        if "code" in message and message["code"]:
            with st.expander("💻 生成的代码"):
                st.code(message["code"], language="python")

# Chat input
if prompt := st.chat_input("请输入您的问题..."):
    # Add user message to chat
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # Display user message
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Get assistant response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        
        # Response data
        response_data = {
            "full_response": "",
            "sources": [],
            "generated_code": None
        }
        
        try:
            # Call streaming API
            async def stream_response():
                async with httpx.AsyncClient(timeout=60.0) as client:
                    payload = {
                        "query": prompt,
                        "top_k": top_k,
                        "stream": True
                    }
                    
                    # Buffer for smoother typing effect
                    char_buffer = ""
                    buffer_size = 3  # 每次显示3个字符
                    
                    async with client.stream(
                        "POST",
                        f"{st.session_state.api_url}/chat_stream",
                        json=payload
                    ) as response:
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                data_str = line[6:]
                                
                                if data_str.strip() == "[DONE]":
                                    # Flush remaining buffer
                                    if char_buffer:
                                        response_data["full_response"] += char_buffer
                                        message_placeholder.markdown(response_data["full_response"])
                                    break
                                
                                try:
                                    event = json.loads(data_str)
                                    event_type = event.get("type")
                                    content = event.get("data")
                                    
                                    if event_type == "text_chunk":
                                        # Add to buffer
                                        char_buffer += content
                                        
                                        # Display when buffer reaches threshold
                                        if len(char_buffer) >= buffer_size:
                                            response_data["full_response"] += char_buffer
                                            message_placeholder.markdown(response_data["full_response"] + "▌")
                                            char_buffer = ""
                                            # Small delay for typing effect (user-configurable)
                                            await asyncio.sleep(typing_speed / 1000.0)
                                    
                                    elif event_type == "text":
                                        # Fallback for non-streaming text
                                        response_data["full_response"] = content
                                        message_placeholder.markdown(response_data["full_response"] + "▌")
                                    
                                    elif event_type == "tool_start":
                                        message_placeholder.info(
                                            f"🔧 正在生成测试用例: {content.get('test_name')}..."
                                        )
                                    
                                    elif event_type == "code_result":
                                        test_name, code = content
                                        response_data["generated_code"] = code
                                        response_data["full_response"] += f"\n\n✅ 已生成测试用例: `{test_name}`"
                                        message_placeholder.markdown(response_data["full_response"])
                                
                                except json.JSONDecodeError:
                                    pass
                
                # Final update without cursor
                message_placeholder.markdown(response_data["full_response"])
            
            # Run async function
            asyncio.run(stream_response())
            
            # Add assistant message to history
            assistant_message = {
                "role": "assistant",
                "content": response_data["full_response"]
            }
            
            if response_data["sources"]:
                assistant_message["sources"] = response_data["sources"]
            
            if response_data["generated_code"]:
                assistant_message["code"] = response_data["generated_code"]
            
            st.session_state.messages.append(assistant_message)
            
        except Exception as e:
            st.error(f"❌ 错误: {str(e)}")
            st.exception(e)

# Footer
st.divider()
st.caption("💡 提示：您可以询问关于 eMMC 协议的任何问题，例如 'CMD6 如何使用？' 或 '生成 CMD24 的测试代码'")
