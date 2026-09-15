# -*- coding: utf-8 -*-
"""
Администрирование кластера 1С через COM (IServerAgentConnection).

Назначение: работа с **собственным** тестовым кластером (создание/удаление
информационных баз, просмотр рабочих процессов rphost, разбор зависших сессий при
отладке). В контуре заказчика этот модуль не используется: доступ к кластеру
не запрашивается и не требуется.

Возможности:
  * видеть кластеры, инфобазы, рабочие процессы (rphost);
  * видеть сессии/соединения пользователей (включая собственные COM-сессии);
  * завершать зависшие сессии (TerminateSession);
  * читать информацию о лицензиях, блокировках.

Требует прав администратора кластера: без них агент отказывает в операциях изменения;
часть сведений читается на кластере, где администраторы не заданы.

Ключевой момент аутентификации (проверено на 8.3.18):
  connector.ConnectAgent("host")                      # адрес БЕЗ порта (или :1540)
  agent.Authenticate(кластер, имя_админа, пароль)     # если админов кластера нет — ("", "")
  agent.AuthenticateAgent(имя, пароль)                # для операций уровня агента

Пример:
    cl = OneCCluster("localhost")
    cl.connect()                       # ConnectAgent + Authenticate("", "")
    print(cl.sessions())               # все сессии кластера
    print(cl.base_sessions("ИмяБазы")) # сессии конкретной ИБ
    cl.terminate_session(session_id)
"""

from __future__ import annotations

import pythoncom
import win32com.client


class OneCClusterError(RuntimeError):
    pass


class OneCCluster:
    """Управление кластером 1С через COM (IServerAgentConnection)."""

    def __init__(self, address: str, admin: str = "", password: str = ""):
        self._address = address          # "host" (порт агента 1540 по умолчанию)
        self._admin = admin              # админ кластера; если админов нет — ""
        self._password = password
        self._agent = None
        self._cluster = None

    def connect(self) -> "OneCCluster":
        connector = win32com.client.Dispatch("V83.COMConnector")
        try:
            self._agent = connector.ConnectAgent(self._address)
        except Exception as exc:
            raise OneCClusterError(
                f"Не удалось подключиться к агенту {self._address} (нужен запущенный ragent): {exc}"
            ) from exc
        clusters = self._agent.GetClusters()
        if not clusters:
            raise OneCClusterError("На сервере нет кластеров")
        self._cluster = clusters[0]
        # Аутентификация: если админов кластера нет — пустые имя/пароль дают доступ
        self._agent.Authenticate(self._cluster, self._admin, self._password)
        return self

    # ── кластер ─────────────────────────────────────────────────────────────

    @property
    def cluster(self):
        return self._cluster

    def cluster_info(self) -> dict:
        c = self._cluster
        return {"name": c.ClusterName, "host": c.HostName, "port": c.MainPort}

    def clusters(self) -> list[dict]:
        return [{"name": c.ClusterName, "host": c.HostName, "port": c.MainPort}
                for c in self._agent.GetClusters()]

    def infobases(self) -> list[dict]:
        coll = self._agent.GetInfoBases(self._cluster)
        return [{"name": ib.Name, "descr": ib.Descr} for ib in coll]

    def working_processes(self) -> list[dict]:
        coll = self._agent.GetWorkingProcesses(self._cluster)
        return [{"pid": wp.ProcessId, "port": wp.Port, "started": str(wp.StartedAt)} for wp in coll]

    # ── сессии ──────────────────────────────────────────────────────────────

    def sessions(self) -> list[dict]:
        coll = self._agent.GetSessions(self._cluster)
        out = []
        for s in coll:
            out.append({
                "session": s.SessionID,
                "user": s.userName,
                "app": s.AppID,
                "host": s.Host,
                "started": str(s.StartedAt),
                "blocked_by": getattr(s, "BlockedBy", None),
            })
        return out

    def base_sessions(self, base_name: str) -> list[dict]:
        """Сессии конкретной инфобазы (GetInfoBaseSessions)."""
        ib = None
        for b in self.infobases():
            if b["name"].lower() == base_name.lower():
                ib = b
                break
        if ib is None:
            raise OneCClusterError(f"Инфобаза не найдена: {base_name}")
        # GetInfoBaseSessions принимает объект инфобазы
        target = None
        for x in self._agent.GetInfoBases(self._cluster):
            if x.Name.lower() == base_name.lower():
                target = x
                break
        coll = self._agent.GetInfoBaseSessions(self._cluster, target)
        out = []
        for s in coll:
            out.append({
                "session": s.SessionID,
                "user": s.userName,
                "app": s.AppID,
                "host": s.Host,
                "started": str(s.StartedAt),
            })
        return out

    def terminate_session(self, session_id, base_name: str | None = None) -> None:
        """Завершить сессию по SessionID. Если base_name не указан — ищет по всем ИБ."""
        if base_name:
            targets = [(self._cluster, self._find_ib(base_name))]
        else:
            targets = [(self._cluster, ib) for ib in self._agent.GetInfoBases(self._cluster)]
        for cluster, ib in targets:
            for s in self._agent.GetInfoBaseSessions(cluster, ib):
                if s.SessionID == session_id:
                    self._agent.TerminateSession(cluster, s)
                    return
        raise OneCClusterError(f"Сессия {session_id} не найдена")

    def _find_ib(self, base_name):
        for ib in self._agent.GetInfoBases(self._cluster):
            if ib.Name.lower() == base_name.lower():
                return ib
        raise OneCClusterError(f"Инфобаза не найдена: {base_name}")


if __name__ == "__main__":
    import json
    import sys
    addr = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    cl = OneCCluster(addr).connect()
    print("Кластер:", cl.cluster_info())
    print("Инфобазы:", json.dumps(cl.infobases(), ensure_ascii=False))
    print("Сессии:", json.dumps(cl.sessions(), ensure_ascii=False, default=str))
