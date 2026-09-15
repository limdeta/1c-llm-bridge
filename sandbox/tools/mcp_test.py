# -*- coding: utf-8 -*-
"""Тест MCP-сервера: список инструментов и вызовы."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER = os.path.join(ROOT, "bridge", "mcp_server.py")


async def main():
    params = StdioServerParameters(command=sys.executable, args=[SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Инструменты (%d):" % len(tools.tools))
            for t in tools.tools:
                print(f"  - {t.name}: {t.description.splitlines()[0][:80]}")

            async def call(name, args):
                r = await session.call_tool(name, args)
                text = r.content[0].text if r.content else str(r)
                try:
                    obj = json.loads(text)
                    return obj
                except Exception:
                    return text

            print("\ninfo:", await call("info", {}))
            print("query:", json.dumps(await call("query", {"query_text": "ВЫБРАТЬ 1 КАК А, \"MCP\" КАК Б"}), ensure_ascii=False)[:300])
            print("execute:", await call("execute", {"code": "Результат = 40 + 2;"}))
            print("catalog (2):", json.dumps((await call("catalog", {}))["items"][:2], ensure_ascii=False)[:400])
            print("finance:", await call("finance", {}))
            r = await call("sale", {"customer": "Гарри Поттер", "items": [{"товар": "Метла «Нимбус-2001»", "количество": 1}]})
            print("sale:", r)
            print("sales (1):", json.dumps((await call("sales", {}))["items"][0], ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
