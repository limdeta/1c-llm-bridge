// onec-cs — мост к 1С:Предприятие 8.3 через COM (V83.COMConnector).
//
// Зачем отдельный исполняемый файл: на рабочих машинах с политиками (ExecutionPolicy,
// AppLocker) скрипты PowerShell могут быть запрещены, а Python обычно нет вовсе.
// Этот мост не требует ни Python, ни PowerShell — только установленную платформу 1С
// и зарегистрированный COM-коннектор (регистрация — bridge/setup_com.ps1).
//
// Использование:
//   onec.exe check  -cs 'File="C:\Bases\МояБаза";Usr="Имя";Pwd=""'
//   onec.exe info   -cs '...'
//   onec.exe exec   -cs '...' 'Результат = 6 * 7;'
//   onec.exe query  -cs '...' "ВЫБРАТЬ 1 КАК А"
//   onec.exe meta   -cs '...' catalogs
//
// Строка соединения берётся из -cs, а если он не указан — из переменной
// окружения ONEC_CONNECTION_STRING.
//
// Потоки вывода: результат — в stdout, ход работы — в stderr (чтобы stdout
// оставался машиночитаемым).

using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.Versioning;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Threading.Tasks;

[SupportedOSPlatform("windows")] // COM-коннектор 1С существует только на Windows
internal static class OneC
{
    /// <summary>Активное COM-соединение с информационной базой.</summary>
    private static object? Conn;

    /// <summary>Имя обработки-исполнителя в расширении конфигурации.</summary>
    private static string ExecutorName =
        Environment.GetEnvironmentVariable("ONEC_EXECUTOR_EXT") is { Length: > 0 } ext
            ? ext
            : "ИИМост_ИсполнительКода";

    private static readonly JsonSerializerOptions JsonOpts = new JsonSerializerOptions
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    private static string J(object? o) => JsonSerializer.Serialize(o, JsonOpts);

    // ── позднее связывание с COM (без ссылок на типы 1С) ─────────────────────

    private static object? Call(object obj, string name, params object?[] args) =>
        obj.GetType().InvokeMember(name, BindingFlags.InvokeMethod, null, obj, args);

    private static object? Get(object obj, string name) =>
        obj.GetType().InvokeMember(name, BindingFlags.GetProperty, null, obj, null);

    private static void Set(object obj, string name, object? value) =>
        obj.GetType().InvokeMember(name, BindingFlags.SetProperty, null, obj, new object?[] { value });

    /// <summary>Приведение значения 1С к тому, что сериализуется в JSON.</summary>
    private static object? Py(object? v)
    {
        if (v is null) return null;
        if (v is int || v is long || v is double || v is bool || v is string) return v;
        if (v is DateTime dt) return dt.ToString("yyyy-MM-dd HH:mm:ss");
        // COM-методы обработок из расширения возвращают кортеж (результат, код)
        if (v is Array { Length: 2 } a && a.GetValue(1) is string) return Py(a.GetValue(0));
        try
        {
            return Call(Conn!, "XMLСтрока", v); // ссылки (UUID) читаемее строкой
        }
        catch
        {
            return v.ToString();
        }
    }

    // ── исполнитель кода (обработка из расширения конфигурации) ──────────────

    private static object? Executor() =>
        Call(Get(Get(Conn!, "Обработки")!, ExecutorName)!, "Создать");

    private static object? ExecCode(string code) =>
        Py(Call(Executor()!, "ВыполнитьКод", code));

    // ── операции моста ──────────────────────────────────────────────────────

    private static string Query(string text)
    {
        object q = Call(Conn!, "NewObject", "Запрос")!;
        Set(q, "Текст", text);
        object table = Call(Call(q, "Выполнить")!, "Выгрузить")!;

        object cols = Get(table, "Колонки")!;
        int colCount = (int)Call(cols, "Количество")!;
        var columns = new List<string>();
        for (int i = 0; i < colCount; i++)
            columns.Add((string)Get(Call(cols, "Получить", i)!, "Имя")!);

        int rowCount = (int)Call(table, "Количество")!;
        var rows = new List<List<object?>>();
        for (int r = 0; r < rowCount; r++)
        {
            object row = Call(table, "Получить", r)!;
            var cells = new List<object?>();
            for (int c = 0; c < colCount; c++)
                cells.Add(Py(Call(row, "Получить", c)));
            rows.Add(cells);
        }

        return J(new
        {
            columns,
            rows,
            row_count = rows.Count,
            total_rows = rowCount,
            truncated = false,
        });
    }

    private static string Meta(string kind)
    {
        object md = Get(Conn!, "Метаданные")!;
        var kinds = new Dictionary<string, string>
        {
            ["catalogs"] = "Справочники",
            ["documents"] = "Документы",
            ["enums"] = "Перечисления",
            ["informationregisters"] = "РегистрыСведений",
            ["accumulationregisters"] = "РегистрыНакопления",
            ["accountingregisters"] = "РегистрыБухгалтерии",
            ["chartsofaccounts"] = "ПланыСчетов",
            ["reports"] = "Отчеты",
            ["dataprocessors"] = "Обработки",
        };

        var wanted = !string.IsNullOrEmpty(kind) && kinds.ContainsKey(kind)
            ? new Dictionary<string, string> { [kind] = kinds[kind] }
            : kinds;

        var result = new Dictionary<string, List<string>>();
        foreach (var pair in wanted)
        {
            object collection = Get(md, pair.Value)!;
            int n = (int)Call(collection, "Количество")!;
            var names = new List<string>();
            for (int i = 0; i < n; i++)
                names.Add((string)Get(Call(collection, "Получить", i)!, "Имя")!);
            result[pair.Key] = names;
        }

        return J(new { metadata = result });
    }

    // ── точка входа ─────────────────────────────────────────────────────────

    private static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;

        string? cs = null;
        string cmd = "check";
        string arg = "";

        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "-cs" && i + 1 < args.Length) cs = args[++i];
            else if (cmd == "check" && args[i] is "check" or "info" or "exec" or "query" or "meta") cmd = args[i];
            else arg = args[i];
        }

        cs ??= Environment.GetEnvironmentVariable("ONEC_CONNECTION_STRING");
        if (string.IsNullOrEmpty(cs))
        {
            Log("Нет строки соединения: укажите -cs '...' или переменную ONEC_CONNECTION_STRING");
            return 1;
        }

        try
        {
            Log("1. Создание COM-коннектора (V83.COMConnector)...");
            object? connector = Activator.CreateInstance(Type.GetTypeFromProgID("V83.COMConnector")!);

            Log("2. Подключение к информационной базе...");
            Conn = Call(connector!, "Connect", cs);
            if (Conn is null)
            {
                Log("Не удалось подключиться");
                return 1;
            }
            Log("   Подключено.");

            switch (cmd)
            {
                case "check":
                {
                    bool ok = true;

                    Log($"3. Поиск исполнителя (расширение {ExecutorName})...");
                    try
                    {
                        Console.WriteLine($"[OK] Исполнитель: {ExecCode("Результат = 6 * 7;")}");
                    }
                    catch (Exception ex)
                    {
                        ok = false;
                        Console.WriteLine("[FAIL] Исполнитель: " + ex.Message);
                    }

                    Log("4. Проверка запросов...");
                    try
                    {
                        Query("ВЫБРАТЬ 1 КАК А");
                        Console.WriteLine("[OK] Запросы работают");
                    }
                    catch (Exception ex)
                    {
                        ok = false;
                        Console.WriteLine("[FAIL] Запросы: " + ex.Message);
                    }

                    Console.WriteLine(ok ? "[OK] Мост готов к работе" : "[FAIL] Мост не готов");
                    return ok ? 0 : 1;
                }

                case "info":
                {
                    Log("3. Загрузка исполнителя, чтение версии...");
                    string platformVersion = J(ExecCode(
                        "СИ = Новый СистемнаяИнформация; Результат = СИ.ВерсияПриложения;"));
                    object? configuration = Get(Get(Conn, "Метаданные")!, "Имя");
                    Console.WriteLine(J(new
                    {
                        connected = true,
                        configuration,
                        platform_version = platformVersion,
                        connection = cs,
                    }));
                    return 0;
                }

                case "exec":
                {
                    if (string.IsNullOrEmpty(arg))
                    {
                        Log("exec: нужен код");
                        return 1;
                    }
                    Log("3. Выполнение кода 1С...");
                    Console.WriteLine(J(ExecCode(arg)));
                    return 0;
                }

                case "query":
                {
                    if (string.IsNullOrEmpty(arg))
                    {
                        Log("query: нужен текст");
                        return 1;
                    }
                    Log("3. Выполнение запроса...");
                    Console.WriteLine(Query(arg));
                    return 0;
                }

                case "meta":
                    Log("3. Чтение метаданных...");
                    Console.WriteLine(Meta(arg));
                    return 0;
            }
        }
        catch (Exception ex)
        {
            Log("ОШИБКА: " + ex.Message);
            return 1;
        }
        finally
        {
            // При запуске двойным щелчком окно закрылось бы мгновенно — даём прочитать вывод.
            // При перенаправленном вводе (запуск агентом/скриптом) ожидания нет.
            if (!Console.IsInputRedirected)
            {
                Log("Готово. Нажмите Enter (или окно закроется через 20 сек)...");
                try
                {
                    Task.Run(() => Console.ReadLine()).Wait(TimeSpan.FromSeconds(20));
                }
                catch
                {
                    // ожидание — не критично
                }
            }
        }

        return 0;
    }

    private static void Log(string msg) =>
        Console.Error.WriteLine($"[{DateTime.Now:HH:mm:ss}] {msg}");
}
