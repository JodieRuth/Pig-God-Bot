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
    public string UserDataFolder { get; init; } = "";
    public string CookieSource { get; init; } = "webview2";
    public string BrowserUserDataFolder { get; init; } = "";
    public string ProfileDirectory { get; init; } = "Default";
    public string CookieUrl { get; init; } = "https://www.bilibili.com/";

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
            CaptureJson = flags.Contains("capture-json"),
            UserDataFolder = values.GetValueOrDefault("user-data-folder", ""),
            CookieSource = values.GetValueOrDefault("cookie-source", "webview2"),
            BrowserUserDataFolder = values.GetValueOrDefault("browser-user-data-folder", ""),
            ProfileDirectory = values.GetValueOrDefault("profile-directory", "Default"),
            CookieUrl = values.GetValueOrDefault("cookie-url", "https://www.bilibili.com/")
        };
    }

    public void Validate()
    {
        var task = Task.ToLowerInvariant();
        if (task is not "animetrace" and not "bilibili-cookie" and not "bilibili-login")
        {
            throw new InvalidOperationException($"未知任务：{Task}");
        }
        if (task == "animetrace" && (string.IsNullOrWhiteSpace(Image) || !File.Exists(Image)))
        {
            throw new FileNotFoundException("图片文件不存在或不可访问");
        }
        if (string.IsNullOrWhiteSpace(OutputJson))
        {
            throw new InvalidOperationException("缺少 --output-json 参数");
        }
    }

    public string ResolveUserDataFolder()
    {
        if (!string.IsNullOrWhiteSpace(BrowserUserDataFolder))
        {
            return Path.GetFullPath(Environment.ExpandEnvironmentVariables(BrowserUserDataFolder));
        }
        var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var source = CookieSource.ToLowerInvariant();
        if (source == "edge")
        {
            return Path.Combine(localAppData, "Microsoft", "Edge", "User Data");
        }
        if (source == "chrome")
        {
            return Path.Combine(localAppData, "Google", "Chrome", "User Data");
        }
        if (!string.IsNullOrWhiteSpace(UserDataFolder))
        {
            return Path.GetFullPath(Environment.ExpandEnvironmentVariables(UserDataFolder));
        }
        if (Task.Equals("animetrace", StringComparison.OrdinalIgnoreCase))
        {
            return Path.Combine(Path.GetTempPath(), "browser_automation_host", Guid.NewGuid().ToString("N"));
        }
        return Path.Combine(localAppData, "NapCatLocalOneBot", "browser_automation_host", "bilibili");
    }

    public JsonSerializerOptions JsonOptions => new()
    {
        WriteIndented = false,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };
}
