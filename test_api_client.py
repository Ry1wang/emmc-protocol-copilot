import httpx
import json
import asyncio

async def test_chat_stream():
    url = "http://127.0.0.1:8000/chat_stream"
    payload = {
        "query": "How to use CMD6 to switch partition?",
        "top_k": 5,
        "stream": True
    }
    
    print(f"Sending request to {url}...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            print(f"Response status: {response.status_code}")
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        print("\n[Stream Complete]")
                        break
                    
                    try:
                        event = json.loads(data_str)
                        event_type = event.get("type")
                        content = event.get("data")
                        
                        if event_type == "text":
                            print(content, end="", flush=True)
                        elif event_type == "tool_start":
                            print(f"\n[Tool Call] Generating test case for: {content.get('test_name')}...")
                        elif event_type == "code_result":
                            print(f"\n[Code Generated]\n{content[1]}")
                            
                    except json.JSONDecodeError:
                        pass

if __name__ == "__main__":
    asyncio.run(test_chat_stream())
