# -*- coding: utf-8 -*-
"""Проверка MCP-сервера: список инструментов и базовые вызовы.

Запуск (из корня репозитория, в venv проекта):
    .venv\Scripts\python -X utf8 tools\mcp_test.py

Строка соединения берётся из ONEC_CONNECTION_STRING (или ONEC_FILE/ONEC_USR/ONEC_PWD).
Проверяются только инструменты уровня моста; прикладные операции — в sandbox/.
"""
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
    # MCP-клиент не наследует окружение родителя: передаём его явно
    env = dict(os.environ)
    params = StdioServerParameters(command=sys.executable, args=[SERVER], env=env)
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
                    return json.loads(text)
                except Exception:
                    return text

            print("\ninfo:", await call("info", {}))
            print("execute:", await call("execute", {"code": "Результат = 40 + 2;"}))
            print("query:", json.dumps(
                await call("query", {"query_text": 'ВЫБРАТЬ 1 КАК А, "MCP" КАК Б'}),
                ensure_ascii=False)[:300])
            print("metadata:", json.dumps(await call("metadata", {"kind": "catalogs"}),
                                          ensure_ascii=False)[:200])


if __name__ == "__main__":
    asyncio.run(main())