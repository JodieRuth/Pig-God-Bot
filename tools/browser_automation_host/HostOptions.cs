using System.Text.Json;

namespace browser_automation_host;

public sealed class HostOptions
{
    public string Task { get; init; } = "animetrace";
    public string Image { get; init; } = "";
    public string Url { get; init; } = "https://ai.animedb.cn/en/";
    public int WaitMs { get; init; } = 20000;
    public string OutputJson { get; init; } = "";
    public bool Visible { get; init; }
    public bool CaptureJson { get; init; }

    public static HostOptions Parse(string[] args)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var flags = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i < args.Length; i++)
        {
            var arg = args[i];
            if (!arg.StartsWith("--", StringComparison.Ordinal))
            {
                if (!values.ContainsKey("image"))
                {
                    values["image"] = arg;
                }
                continue;
            }
            var name = arg[2..];
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
            {
                values[name] = args[++i];
            }
            else
            {
                flags.Add(name);
            }
        }
        return new HostOptions
        {
            Task = values.GetValueOrDefault("task", "animetrace"),
            Image = values.GetValueOrDefault("image", ""),
            Url = values.GetValueOrDefault("url", "https://ai.animedb.cn/en/"),
            WaitMs = int.TryParse(values.GetValueOrDefault("wait-ms", "20000"), out var waitMs) ? waitMs : 20000,
            OutputJson = values.GetValueOrDefault("output-json", ""),
            Visible = flags.Contains("visible"),
            CaptureJson = flags.Contains("capture-json")
        };
    }

    public void Validate()
    {
        if (!Task.Equals("animetrace", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException($"未知任务：{Task}");
        }
        if (string.IsNullOrWhiteSpace(Image) || !File.Exists(Image))
        {
            throw new FileNotFoundException("图片文件不存在或不可访问");
        }
        if (string.IsNullOrWhiteSpace(OutputJson))
        {
            throw new InvalidOperationException("缺少 --output-json 参数");
        }
    }

    public JsonSerializerOptions JsonOptions => new()
    {
        WriteIndented = false,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };
}
