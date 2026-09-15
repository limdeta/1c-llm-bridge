#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ssh_exec.py — запуск моста на машине с 1С по SSH из любой оболочки.

Основной путь для нас — `bridge/remote.ps1` (на обеих машинах есть PowerShell).
Этот помощник нужен там, где вызов идёт не из PowerShell: bash-оболочка харнеса,
пакетный скрипт на Linux/macOS, автоматизация без Windows-зависимостей. Зависимостей
у него нет — только стандартная библиотека Python и системный `ssh`.

Команда передаётся как `-EncodedCommand` (base64 UTF-16LE) — иначе кириллица в коде
и запросах ломается оболочкой Windows (грабля № 48 в PITFALLS.md).

Использование:

    # надёжный способ: строка соединения — в переменной окружения
    # (из PowerShell кавычки в аргументах доходят до чужих программ искажёнными — грабля № 47)
    $env:ONEC_CONNECTION_STRING = 'Srvr="srv";Ref="база";Usr="имя";Pwd=""'
    python3 tools/ssh_exec.py --target user@vm check
    python3 tools/ssh_exec.py --target user@vm query "ВЫБРАТЬ ПЕРВЫЕ 5 Наименование ИЗ Справочник.Товары"

    # посмотреть, что именно уйдёт по ssh, ничего не выполняя:
    python3 tools/ssh_exec.py --target user@vm --dry-run info

Возвращает stdout моста как есть; код возврата — код ssh (0 при успехе).
"""
from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys

DEFAULT_BRIDGE = "C:/1c-bridge/bridge/onec.ps1"
DEFAULT_CS_ENV = "ONEC_CONNECTION_STRING"


def build_inner(bridge: str, cs: str, command: str, arg: str | None) -> str:
    """Собирает команду для PowerShell на удалённой машине.

    Кавычки внутри значений экранируются удвоением — этого достаточно, потому что
    вся строка целиком передаётся через base64 и не проходит через оболочку.
    """
    parts = [f"& '{bridge.replace(chr(39), chr(39) * 2)}'"]
    if cs:
        parts.append(f"-ConnectionString '{cs.replace(chr(39), chr(39) * 2)}'")
    parts.append(command)
    if arg:
        parts.append(f"'{arg.replace(chr(39), chr(39) * 2)}'")
    return " ".join(parts)


def encode(inner: str) -> str:
    return base64.b64encode(inner.encode("utf-16-le")).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Запуск моста к 1С по SSH (кроссплатформенно)")
    parser.add_argument("command", help="команда моста: check | info | exec | query | meta")
    parser.add_argument("arg", nargs="?", help="аргумент команды (код 1С, текст запроса, вид метаданных)")
    parser.add_argument("--target", default=os.environ.get("ONEC_SSH", ""),
                        help="ssh-таргет вида user@host (или переменная ONEC_SSH)")
    parser.add_argument("--bridge", default=os.environ.get("ONEC_REMOTE_BRIDGE", DEFAULT_BRIDGE),
                        help="путь к onec.ps1 НА удалённой машине")
    parser.add_argument("--cs", default=os.environ.get(DEFAULT_CS_ENV, ""),
                        help=f"строка соединения 1С (или переменная {DEFAULT_CS_ENV})")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать команду и раскодированное содержимое, ничего не выполнять")
    parser.add_argument("--timeout", type=float, default=120.0, help="таймаут ssh, секунд")
    args = parser.parse_args(argv)

    if not args.target:
        print("Не задан ssh-таргет: укажите --target user@host или переменную ONEC_SSH", file=sys.stderr)
        return 2

    # PowerShell 5.1 искажает кавычки при передаче аргументов нативным программам
    # (грабля № 47): строка соединения приходит без них и подключение не сработает.
    if args.cs and "=" in args.cs and '"' not in args.cs:
        print("Внимание: в строке соединения нет кавычек. Если вызов идёт из PowerShell,\n"
              "они теряются при передаче аргументов (грабля № 47 в PITFALLS.md). Надёжнее\n"
              "передать строку через переменную окружения ONEC_CONNECTION_STRING.", file=sys.stderr)

    inner = build_inner(args.bridge, args.cs, args.command, args.arg)
    encoded = encode(inner)
    ssh_cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        args.target,
        f"powershell -NoProfile -EncodedCommand {encoded}",
    ]

    if args.dry_run:
        print("ssh-команда:")
        print("  " + " ".join(f'"{c}"' if " " in c else c for c in ssh_cmd[:3]) + f" <encoded:{len(encoded)} симв.>")
        print("\nчто будет выполнено на удалённой машине (после base64 → UTF-16LE):")
        print("  " + inner)
        return 0

    try:
        proc = subprocess.run(ssh_cmd, timeout=args.timeout, capture_output=True)
    except subprocess.TimeoutExpired:
        print(f"ssh не ответил за {args.timeout:g} с — операция прервана на нашей стороне. "
              "Внимание: серверный запрос 1С при этом может продолжаться (см. docs/core/DAY_ONE.md, §10).",
              file=sys.stderr)
        return 124
    except FileNotFoundError:
        print("Не найден исполняемый файл ssh. Установите клиент OpenSSH.", file=sys.stderr)
        return 127

    out = proc.stdout.decode("utf-8", errors="replace")
    err = proc.stderr.decode("utf-8", errors="replace")
    if out:
        sys.stdout.write(out)
    if err:
        sys.stderr.write(err)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
