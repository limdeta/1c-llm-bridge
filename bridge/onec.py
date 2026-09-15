# -*- coding: utf-8 -*-
"""
Ядро прослойки к 1С:Предприятие через COM (V83.COMConnector).

Возможности:
  * connect()        — внешнее соединение с информационной базой
  * info()           — версии платформы/конфигурации, строка соединения
  * execute(code)    — выполнить произвольный код 1С (через обработку-исполнитель
                       mcpExecutor.epf; результат пишется в переменную Результат)
  * eval(expr)       — вычислить выражение (оператор Вычислить)
  * query(text, params, limit) — язык запросов 1С, результат в виде таблицы
  * metadata(kind)   — список объектов метаданных (справочники, документы, ...)

Критично: COM-объекты 1С привязаны к апартаменту создавшего их потока, поэтому
ВСЕ операции выполняются в одном выделенном потоке (CoInitialize + пул из 1
рабочего). Никакие COM-объекты нельзя передавать между потоками.

Значения 1С -> Python:
  примитивы (число, строка, булево) — как есть;
  дата — ISO-строка (пустая дата 0001-01-01 -> None);
  ссылки/прочее — сериализация через XMLСтрока() соединения.
"""

from __future__ import annotations

import datetime as _dt
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pythoncom
import pywintypes
import win32com.client

# Строка соединения по умолчанию — из переменных окружения:
#   ONEC_CONNECTION_STRING — полная строка (приоритет);
#   иначе собирается из ONEC_FILE (путь к файловой базе) / ONEC_USR / ONEC_PWD.
_BASE_PATH = os.environ.get("ONEC_FILE", "")
BASE = os.environ.get("ONEC_CONNECTION_STRING") or (
    f'File="{_BASE_PATH}";Usr="{os.environ.get("ONEC_USR", "")}";Pwd="{os.environ.get("ONEC_PWD", "")}"'
    if _BASE_PATH
    else ""
)
EXECUTOR_EPF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "build", "mcpExecutor.epf")
# Исполнитель кода как объект расширения конфигурации — работает при включённой
# «Защите от опасных действий» (ослаблять её не нужно). Если расширение не применено —
# fallback на внешний EPF.
EXECUTOR_EXT_NAME = "ИИМост_ИсполнительКода"
PROGID = "V83.COMConnector"


class OneCError(RuntimeError):
    """Ошибка работы с 1С через COM."""


class OneC:
    """Постоянное COM-подключение к информационной базе 1С."""

    def __init__(self, connection_string: str = BASE, executor_epf: str | None = None,
                 executor_ext: str | None = EXECUTOR_EXT_NAME):
        self._conn_str = connection_string
        self._executor_epf = executor_epf or EXECUTOR_EPF
        self._executor_ext = executor_ext
        self._connection = None
        self._executor = None
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="onec-com",
            initializer=pythoncom.CoInitialize,
        )

    # ── инфраструктура: всё через один COM-поток ────────────────────────────

    def _run(self, fn, *args):
        return self._pool.submit(fn, *args).result()

    @staticmethod
    def _norm(value):
        """Нормализация результата: COM-методы обработок из конфигурации в 8.3.18
        возвращают кортеж (результат, код); у EPF — просто значение."""
        if isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], str):
            return value[0]
        return value

    def _reconnect(self):
        """Сброс соединения и исполнителя — следующий вызов переподключится."""
        self._connection = None
        self._executor = None

    def _with_retry(self, fn, *args, retries: int = 1, delay: float = 0.6):
        """Выполнить fn с автопереподключением при COM-обрывах (боевые сценарии:
        сетевые глюки, рестарты кластера, зависшие rphost)."""
        last = None
        for attempt in range(retries + 1):
            try:
                return fn(*args)
            except pywintypes.com_error as exc:  # noqa: PERF203
                last = exc
                self._reconnect()
                if attempt >= retries:
                    break
                import time
                time.sleep(delay * (attempt + 1))
        raise last

    def close(self):
        def _close():
            self._executor = None
            self._connection = None

        try:
            self._run(_close)
        finally:
            self._pool.shutdown(wait=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── соединение ───────────────────────────────────────────────────────────

    def _ensure_connection(self):
        if self._connection is not None:
            return self._connection
        if not self._conn_str:
            raise OneCError(
                "Не задана строка соединения. Укажите её в ONEC_CONNECTION_STRING "
                "(или ONEC_FILE/ONEC_USR/ONEC_PWD) либо передайте в OneC(connection_string=...).\n"
                'Пример: File="C:\\Bases\\МояБаза";Usr="Имя";Pwd="пароль"'
            )
        try:
            connector = win32com.client.Dispatch(PROGID)
            self._connection = connector.Connect(self._conn_str)
        except Exception as exc:
            raise OneCError(
                f"Не удалось подключиться к 1С. Строка: {self._conn_str}\n{exc}"
            ) from exc
        return self._connection

    def _ensure_executor(self):
        if self._executor is not None:
            return self._executor
        conn = self._ensure_connection()
        # 1) Исполнитель из расширения конфигурации (не требует снятия защиты)
        if self._executor_ext:
            try:
                manager = conn.Обработки
                self._executor = getattr(manager, self._executor_ext).Создать()
                return self._executor
            except Exception:
                self._executor = None
        # 2) Fallback: внешняя обработка-исполнитель (EPF)
        if not os.path.exists(self._executor_epf):
            raise OneCError(
                f"Обработка-исполнитель не найдена: {self._executor_epf} и расширение "
                f"'{self._executor_ext}' недоступно. Соберите EPF из src/executor (см. README)."
            )
        try:
            self._executor = conn.ВнешниеОбработки.Создать(self._executor_epf)
        except Exception as exc:
            raise OneCError(
                f"Не удалось загрузить обработку-исполнитель. "
                f"Проверьте, что у пользователя ИБ снята «Защита от опасных действий» "
                f"или применено расширение {self._executor_ext}.\n{exc}"
            ) from exc
        return self._executor

    # ── конвертация значений ─────────────────────────────────────────────────

    @staticmethod
    def _to_python(value: Any, conn) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float, str)):
            return value
        if isinstance(value, (_dt.datetime, pywintypes.TimeType)):
            try:
                dt = _dt.datetime(value.year, value.month, value.day,
                                  value.hour, value.minute, value.second)
            except Exception:
                return str(value)
            if dt.year == 1 and dt.month == 1 and dt.day == 1:
                return None
            return dt.isoformat(sep=" ")
        try:
            return conn.XMLСтрока(value)
        except Exception:
            try:
                return str(value)
            except Exception:
                return "<значение 1С>"

    # ── публичный API ────────────────────────────────────────────────────────

    def connect(self) -> dict[str, Any]:
        return self._run(self._do_connect)

    def _do_connect(self):
        conn = self._ensure_connection()
        return {"connected": conn is not None}

    def info(self) -> dict[str, Any]:
        return self._run(self._with_retry, self._do_info)

    def _do_info(self):
        conn = self._ensure_connection()
        ex = self._ensure_executor()
        return {
            "connected": True,
            "configuration": conn.Метаданные.Имя,
            "platform_version": self._norm(ex.ВыполнитьКод(
                "СИ = Новый СистемнаяИнформация; Результат = СИ.ВерсияПриложения;"
            )),
            "connection": self._conn_str,
        }

    def execute(self, code: str, timeout: float | None = None) -> Any:
        fut = self._pool.submit(self._with_retry, self._execute_raw, code)
        try:
            return fut.result(timeout=timeout)
        except pywintypes.com_error as exc:
            raise OneCError(f"Ошибка выполнения кода 1С:\n{exc}") from exc

    def _execute_raw(self, code: str) -> Any:
        if not code or not code.strip():
            raise OneCError("Пустой код")
        ex = self._ensure_executor()
        return self._to_python(self._norm(ex.ВыполнитьКод(code)), self._ensure_connection())

    def eval(self, expr: str) -> Any:
        fut = self._pool.submit(self._with_retry, self._eval_raw, expr)
        try:
            return fut.result()
        except pywintypes.com_error as exc:
            raise OneCError(f"Ошибка вычисления выражения 1С:\n{exc}") from exc

    def _eval_raw(self, expr: str) -> Any:
        if not expr or not expr.strip():
            raise OneCError("Пустое выражение")
        ex = self._ensure_executor()
        return self._to_python(self._norm(ex.ВычислитьВыражение(expr)), self._ensure_connection())

    def query(self, text: str, params: dict[str, Any] | None = None, limit: int = 1000) -> dict[str, Any]:
        try:
            return self._run(self._with_retry, self._do_query, text, params or {}, limit)
        except pywintypes.com_error as exc:
            raise OneCError(f"Ошибка выполнения запроса:\n{exc}") from exc

    def _do_query(self, text: str, params: dict[str, Any], limit: int) -> dict[str, Any]:
        conn = self._ensure_connection()
        try:
            query = conn.NewObject("Запрос")
            query.Текст = text
            for name, raw in params.items():
                if isinstance(raw, str):
                    try:
                        dt = _dt.datetime.fromisoformat(raw.replace(" ", "T"))
                        raw = pywintypes.Time(dt)
                    except ValueError:
                        pass
                query.УстановитьПараметр(name, raw)
            result = query.Выполнить()
            table = result.Выгрузить()
            cols = table.Колонки
            n_cols = cols.Количество()
            columns = [cols.Получить(i).Имя for i in range(n_cols)]
            total = table.Количество()
            take = total if limit is None or limit < 0 else min(total, limit)
            rows = []
            for i in range(take):
                row = table.Получить(i)
                rows.append([self._to_python(row.Получить(j), conn) for j in range(n_cols)])
            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "total_rows": total,
                "truncated": take < total,
            }
        except pywintypes.com_error:
            raise  # проброс в _with_retry (обрыв сети/кластера)
        except Exception as exc:
            raise OneCError(f"Ошибка выполнения запроса:\n{exc}") from exc

    _META_KINDS = {
        "catalogs": "Справочники",
        "documents": "Документы",
        "informationregisters": "РегистрыСведений",
        "accumulationregisters": "РегистрыНакопления",
        "accountingregisters": "РегистрыБухгалтерии",
        "calculationregisters": "РегистрыРасчета",
        "enums": "Перечисления",
        "constants": "Константы",
        "chartsofcharacteristictypes": "ПланыВидовХарактеристик",
        "chartsofaccounts": "ПланыСчетов",
        "businessprocesses": "БизнесПроцессы",
        "tasks": "Задачи",
        "exchangeplans": "ПланыОбмена",
        "reports": "Отчеты",
        "dataprocessors": "Обработки",
    }

    def metadata(self, kind: str | None = None) -> dict[str, Any]:
        try:
            return self._run(self._with_retry, self._do_metadata, kind)
        except pywintypes.com_error as exc:
            raise OneCError(f"Ошибка чтения метаданных:\n{exc}") from exc

    def _do_metadata(self, kind: str | None) -> dict[str, Any]:
        conn = self._ensure_connection()
        meta = conn.Метаданные
        kinds = self._META_KINDS
        if kind:
            key = kind.strip().lower().replace(" ", "")
            ru = self._META_KINDS.get(key)
            if ru is None:
                raise OneCError(f"Неизвестный вид метаданных '{kind}'. Доступно: {', '.join(sorted(kinds))}")
            kinds = {key: ru}
        out = {}
        for eng, ru_attr in kinds.items():
            coll = getattr(meta, ru_attr)
            names = []
            try:
                count = coll.Количество()
                for i in range(count):
                    names.append(coll.Получить(i).Имя)
            except Exception:
                pass
            out[eng] = names
        return {"metadata": out}


def quick(code: str) -> Any:
    """Одноразовое выполнение кода (удобно из CLI/скриптов)."""
    with OneC() as c:
        return c.execute(code)


if __name__ == "__main__":
    import json
    import sys

    with OneC() as c:
        cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
        if cmd == "info":
            print(json.dumps(c.info(), ensure_ascii=False, indent=2))
        elif cmd == "exec":
            print(c.execute(sys.argv[2]))
        elif cmd == "query":
            print(json.dumps(c.query(sys.argv[2]), ensure_ascii=False, indent=2))
        elif cmd == "meta":
            print(json.dumps(c.metadata(sys.argv[2] if len(sys.argv) > 2 else None), ensure_ascii=False, indent=2))
        else:
            print("usage: onec.py [info|exec <код>|query <текст>|meta [вид]]")
