# -*- coding: utf-8 -*-
"""
MCP-сервер доступа к 1С — «прослойка» для LLM-агентов.

Оборачивает bridge/onec.py (COM-мост к информационной базе) в четыре MCP-инструмента:
info, execute, query, metadata. Никаких бизнес-операций: состав инструментов под
конкретную задачу определяется отдельно, а узкие операции с ограничениями — в `docs/core/TOOLS.md`.

Транспорт: stdio. Подключение к любому MCP-клиенту (Claude Code, Cursor, DSH и т.п.).

Запуск:
    .venv\\Scripts\\python bridge\\mcp_server.py

Конфигурация (env, опционально):
    ONEC_CONNECTION_STRING = File="...";Usr="...";Pwd="..."   (или Srvr="...";Ref="...")
    ONEC_FILE / ONEC_USR / ONEC_PWD                          (альтернатива по частям)
    ONEC_EXECUTOR_EXT = имя обработки-исполнителя в расширении (по умолчанию ИИМост_ИсполнительКода)

Пример для .mcp.json (Claude Code):
    "1c-mcp": { "command": "C:\\<путь к репозиторию>\\.venv\\Scripts\\python.exe",
                "args": ["C:\\<путь к репозиторию>\\bridge\\mcp_server.py"] }
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from onec import OneC, OneCError, _BASE_PATH

# ── конфигурация ────────────────────────────────────────────────────────────

def _connection_string() -> str:
    raw = os.environ.get("ONEC_CONNECTION_STRING")
    if raw:
        return raw
    parts = []
    if os.environ.get("ONEC_FILE"):
        parts.append(f'File="{os.environ["ONEC_FILE"]}"')
    else:
        parts.append(f'File="{_BASE_PATH}"')
    # Пользователь по умолчанию — Администратор (пустой пароль), как в onec.BASE
    parts.append(f'Usr="{os.environ.get("ONEC_USR", "Администратор")}"')
    parts.append(f'Pwd="{os.environ.get("ONEC_PWD", "")}"')
    return ";".join(parts)


CONN = _connection_string()
EXECUTOR_EXT = os.environ.get("ONEC_EXECUTOR_EXT", "ИИМост_ИсполнительКода")

# Единый мост: все COM-операции через один поток (см. onec.OneC)
onec = OneC(connection_string=CONN, executor_ext=EXECUTOR_EXT)

mcp = FastMCP(
    "1c-mcp",
    instructions=(
        "Доступ к информационной базе 1С:Предприятие через COM-мост. "
        "Инструменты: query — язык запросов 1С (ВЫБРАТЬ/ИЗ/ГДЕ, русские ключевые слова), "
        "execute — произвольный код 1С (результат пишется в переменную Результат), "
        "metadata — объекты конфигурации. Ссылочные поля возвращаются как UUID — "
        "для читаемого вида добавляйте ПРЕДСТАВЛЕНИЕ(Поле) КАК ПолеПредставление. "
        "Даты в параметрах: 'YYYY-MM-DD' или 'YYYY-MM-DDTHH:MM:SS'."
    ),
)


def _err(exc: Exception) -> str:
    if isinstance(exc, (OneCError, ValueError)):
        return f"ОШИБКА: {exc}"
    return f"ОШИБКА ({type(exc).__name__}): {exc}"


# ── базовые инструменты ─────────────────────────────────────────────────────

@mcp.tool()
def info() -> dict:
    """Информация о подключении: версия платформы, конфигурация, строка соединения."""
    try:
        return onec.info()
    except Exception as exc:  # noqa: BLE001
        return {"error": _err(exc)}


@mcp.tool()
def execute(code: str) -> str:
    """Выполнить произвольный код на встроенном языке 1С.

    Код исполняется в контексте внешнего соединения (обработка-исполнитель из
    расширения). Результат записывается в переменную Результат и возвращается.
    Доступны конструкторы Новый/Справочники/Документы/Запрос и т.д.

    Args:
        code: Фрагмент кода 1С, например:
            'Т = Справочники.Товары.НайтиПоНаименованию("Палочка"); Результат = Т.ЦенаПродажи;'
            'Результат = 40 + 2;'

    Returns:
        Значение Результат (число/строка/булево/дата) или текст ошибки.
    """
    try:
        v = onec.execute(code)
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@mcp.tool()
def query(query_text: str, params: dict | None = None, limit: int = 1000) -> dict:
    """Выполнить запрос на языке запросов 1С.

    Args:
        query_text: Текст запроса (ВЫБРАТЬ ... ИЗ ... ГДЕ ...).
        params: Параметры {Имя: значение}; строки-даты конвертируются в даты 1С.
        limit: Максимум строк (по умолчанию 1000; -1 — без ограничения).

    Returns:
        {columns, rows, row_count, total_rows, truncated}.
    """
    try:
        return onec.query(query_text, params or {}, limit)
    except Exception as exc:  # noqa: BLE001
        return {"error": _err(exc)}


@mcp.tool()
def metadata(kind: str | None = None) -> dict:
    """Список объектов метаданных конфигурации.

    Args:
        kind: Один из: catalogs, documents, enums, constants, informationregisters,
            accumulationregisters, accountingregisters, chartsofaccounts, reports,
            dataprocessors, ... Если не задан — все виды.

    Returns:
        {metadata: {вид: [имена объектов]}}.
    """
    try:
        return onec.metadata(kind)
    except Exception as exc:  # noqa: BLE001
        return {"error": _err(exc)}


if __name__ == "__main__":
    mcp.run()
