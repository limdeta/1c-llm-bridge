# -*- coding: utf-8 -*-
"""
HTTP API «Волшебного магазина» — прослойка между HTTP и базой 1С.

Реальный веб-сервер не нужен: это локальный API (localhost), который через
COM-мост (bridge/onec.py) исполняет код 1С в информационной базе.

Эндпоинты:
  GET  /api/info                     — версии, конфигурация
  GET  /api/catalog                  — каталог товаров с остатками и ценами
  GET  /api/catalog/<uuid>           — товар по UUID
  GET  /api/inventory                — остатки на складе
  GET  /api/sales                    — продажи (документы)
  GET  /api/finance                  — «маленькая бухгалтерия»: выручка, себестоимость, прибыль, затраты
  POST /api/purchase                 — закупка { "поставщик": "<имя>", "позиции": [{"товар": "<имя>", "количество": N}] }
  POST /api/sale                     — продажа { "контрагент": "<имя>", "позиции": [...] }

Запуск:  python -X utf8 bridge/api.py [порт]
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from onec import OneC, OneCError

# Магическая валюта: 1 галлеон = 17 сиклей = 493 кната
GALLEONS_PER_SICKLE = 17
KNUTS_PER_SICKLE = 29  # 17 сиклей = 493 кната → 1 сикль = 29 кнатов


def format_money(galleons: float) -> str:
    g = int(galleons)
    s = int(round((galleons - g) * GALLEONS_PER_SICKLE))
    k = int(round((galleons - g - s / GALLEONS_PER_SICKLE) * KNUTS_PER_SICKLE * GALLEONS_PER_SICKLE))
    return f"{g} галл. {s} сикл. {k} кн."


class Shop:
    def __init__(self):
        self.onec = OneC()

    # ── данные ─────────────────────────────────────────────────────────────

    def catalog(self):
        r = self.onec.query("""
            ВЫБРАТЬ
                Товары.Ссылка КАК Ссылка,
                Товары.Код КАК Код,
                Товары.Наименование КАК Наименование,
                Товары.ЦенаПродажи КАК ЦенаПродажи,
                Товары.ЦенаЗакупки КАК ЦенаЗакупки,
                Товары.ВидТовара КАК ВидТовара,
                Товары.МагическаяСила КАК МагическаяСила,
                Товары.Описание КАК Описание,
                ЕСТЬNULL(Остатки.КоличествоОстаток, 0) КАК Остаток
            ИЗ
                Справочник.Товары КАК Товары
                ЛЕВОЕ СОЕДИНЕНИЕ РегистрНакопления.ОстаткиТоваров.Остатки(, ) КАК Остатки
                ПО Товары.Ссылка = Остатки.Товар
            УПОРЯДОЧИТЬ ПО Наименование
        """, {}, limit=1000)
        items = []
        for row in r["rows"]:
            items.append({
                "uuid": row[0],
                "code": row[1],
                "name": row[2],
                "price_galleons": row[3],
                "price": format_money(row[3]),
                "purchase_price": row[4],
                "kind": row[5],
                "power": row[6],
                "description": row[7],
                "stock": row[8],
            })
        return {"items": items, "count": len(items)}

    def inventory(self):
        r = self.onec.query("""
            ВЫБРАТЬ
                Товары.Наименование КАК Товар,
                ЕСТЬNULL(Остатки.КоличествоОстаток, 0) КАК Остаток
            ИЗ
                Справочник.Товары КАК Товары
                ЛЕВОЕ СОЕДИНЕНИЕ РегистрНакопления.ОстаткиТоваров.Остатки(, ) КАК Остатки
                ПО Товары.Ссылка = Остатки.Товар
            УПОРЯДОЧИТЬ ПО Остаток УБЫВ
        """, {}, limit=1000)
        return {"items": [{"name": rw[0], "stock": rw[1]} for rw in r["rows"]]}

    def finance(self):
        r = self.onec.query("""
            ВЫБРАТЬ
                СУММА(Продажи.СуммаОборот) КАК Выручка,
                СУММА(Продажи.СебестоимостьОборот) КАК Себестоимость,
                СУММА(Продажи.КоличествоОборот) КАК Кол
            ИЗ РегистрНакопления.Продажи.Обороты(&Начало, &Конец, ) КАК Продажи
        """, {"Начало": "2000-01-01", "Конец": "2099-12-31"})
        revenue, cost, qty = r["rows"][0]
        r2 = self.onec.query("""
            ВЫБРАТЬ СУММА(Закупки.СуммаОборот) КАК Затраты
            ИЗ РегистрНакопления.Закупки.Обороты(&Начало, &Конец, ) КАК Закупки
        """, {"Начало": "2000-01-01", "Конец": "2099-12-31"})
        purchases = r2["rows"][0][0] or 0
        revenue = revenue or 0
        cost = cost or 0
        return {
            "revenue_galleons": revenue,
            "revenue": format_money(revenue),
            "cost_of_goods_galleons": cost,
            "cost_of_goods": format_money(cost),
            "profit_galleons": round(revenue - cost, 2),
            "profit": format_money(revenue - cost),
            "purchases_galleons": purchases,
            "purchases": format_money(purchases),
            "items_sold": qty or 0,
            "currency": "1 галлеон = 17 сиклей = 493 кната",
        }

    def sales(self):
        r = self.onec.query("""
            ВЫБРАТЬ
                Продажи.Ссылка КАК Ссылка,
                Продажи.Номер КАК Номер,
                Продажи.Дата КАК Дата,
                Продажи.Контрагент.Наименование КАК Контрагент,
                Продажи.Проведен КАК Проведен
            ИЗ Документ.ПродажаТовара КАК Продажи
            УПОРЯДОЧИТЬ ПО Дата УБЫВ
        """, {}, limit=100)
        return {"items": [{
            "uuid": rw[0], "number": rw[1], "date": rw[2],
            "customer": rw[3], "posted": rw[4],
        } for rw in r["rows"]]}

    # ── операции ───────────────────────────────────────────────────────────

    @staticmethod
    def _esc(value: str) -> str:
        """Экранирование строки для встраивания в BSL-литерал."""
        return value.replace('"', '""')

    def purchase(self, supplier: str, items: list[dict]):
        return self._make_doc("ЗакупкаТовара", "Поставщик", supplier, items)

    def sale(self, customer: str, items: list[dict]):
        return self._make_doc("ПродажаТовара", "Контрагент", customer, items)

    def _make_doc(self, doc_name: str, party_attr: str, party: str, items: list[dict]):
        if not items:
            raise OneCError("Пустой список позиций")
        lines = []
        for it in items:
            gname = self._esc(it["товар"])
            qty = float(it["количество"])
            lines.append(
                f"Стр = Д.Товары.Добавить();"
                f"Стр.Товар = Справочники.Товары.НайтиПоНаименованию(\"{gname}\");"
                f"Стр.Количество = {qty};"
                f"Стр.Цена = Стр.Товар.ЦенаПродажи;"
                f"Стр.Сумма = Стр.Цена * Стр.Количество;"
            )
        code = (
            f"Д = Документы.{doc_name}.СоздатьДокумент();"
            "Д.Дата = ТекущаяДата();"
            f"Д.{party_attr} = Справочники.Контрагенты.НайтиПоНаименованию(\"{self._esc(party)}\");"
            + "".join(lines)
            + "Д.Записать(); Д.Записать(РежимЗаписиДокумента.Проведение);"
            "Результат = XMLСтрока(Д.Ссылка);"
        )
        uuid = self.onec.execute(code)
        return {"document": uuid, "doc_type": doc_name, "party": party, "items": items}


class Handler(BaseHTTPRequestHandler):
    shop: Shop = None  # ставится снаружи

    def log_message(self, fmt, *args):
        sys.stderr.write("[http] %s\n" % (fmt % args))

    def _send(self, code: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise OneCError("Некорректный JSON")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/api/info":
                self._send(200, self.shop.onec.info())
            elif path == "/api/catalog":
                self._send(200, self.shop.catalog())
            elif path == "/api/inventory":
                self._send(200, self.shop.inventory())
            elif path == "/api/finance":
                self._send(200, self.shop.finance())
            elif path == "/api/sales":
                self._send(200, self.shop.sales())
            elif path.startswith("/api/catalog/"):
                uid = path.rsplit("/", 1)[-1]
                cat = self.shop.catalog()
                item = next((i for i in cat["items"] if i["uuid"] == uid), None)
                if item is None:
                    self._send(404, {"error": f"Товар не найден: {uid}"})
                else:
                    self._send(200, item)
            else:
                self._send(404, {"error": f"Неизвестный путь: {path}", "hint": "см. /api/info"})
        except OneCError as e:
            self._send(500, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self._body()
            if path == "/api/purchase":
                res = self.shop.purchase(data.get("поставщик", ""), data.get("позиции", []))
                self._send(200, res)
            elif path == "/api/sale":
                res = self.shop.sale(data.get("контрагент", ""), data.get("позиции", []))
                self._send(200, res)
            else:
                self._send(404, {"error": f"Неизвестный путь: {path}"})
        except OneCError as e:
            self._send(500, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    shop = Shop()
    Handler.shop = shop
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Волшебный магазин API: http://127.0.0.1:{port}/api/info", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shop.onec.close()


if __name__ == "__main__":
    main()
