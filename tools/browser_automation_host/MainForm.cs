using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using System.Diagnostics;
using System.Text.Json;

namespace browser_automation_host;

public partial class MainForm : Form
{
    private readonly HostOptions options;
    private readonly WebView2 webView;
    private readonly List<object[]> capturedNetwork = [];
    private readonly Stopwatch stopwatch = new();
    private Dictionary<string, object?> searchResponse = new()
    {
        ["status"] = null,
        ["content_type"] = null,
        ["text"] = null,
        ["url"] = null,
        ["elapsed"] = null
    };
    private int exitCode;

    public MainForm(HostOptions options)
    {
        this.options = options;
        InitializeComponent();
        if (!options.Visible)
        {
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.Manual;
            Location = new Point(-32000, -32000);
            Size = new Size(1, 1);
            FormBorderStyle = FormBorderStyle.None;
            Opacity = 0;
            WindowState = FormWindowState.Minimized;
        }
        webView = new WebView2
        {
            Dock = DockStyle.Fill
        };
        Controls.Add(webView);
        Shown += async (_, _) => await RunAsync();
    }

    protected override bool ShowWithoutActivation => true;


    private async Task RunAsync()
    {
        try
        {
            options.Validate();
            var userDataFolder = Path.Combine(Path.GetTempPath(), "browser_automation_host", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(userDataFolder);
            var environment = await CoreWebView2Environment.CreateAsync(null, userDataFolder);
            await webView.EnsureCoreWebView2Async(environment);
            ConfigureWebView();
            var result = await RunAnimeTraceAsync();
            await WriteResultAsync(result);
            exitCode = 0;
        }
        catch (Exception ex)
        {
            exitCode = 1;
            await WriteErrorAsync(ex);
        }
        finally
        {
            BeginInvoke(() => Close());
        }
    }

    protected override void OnFormClosed(FormClosedEventArgs e)
    {
        base.OnFormClosed(e);
        Environment.ExitCode = exitCode;
    }

    private void ConfigureWebView()
    {
        var core = webView.CoreWebView2;
        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.AreDevToolsEnabled = false;
        core.WebResourceResponseReceived += async (_, e) => await OnWebResourceResponseReceivedAsync(e);
    }

    private async Task<Dictionary<string, object?>> RunAnimeTraceAsync()
    {
        stopwatch.Restart();
        await NavigateAsync(options.Url);
        await WaitForPageReadyAsync();
        await UploadImageAsync(options.Image);
        await TriggerSearchAsync();
        await Task.Delay(Math.Max(1000, options.WaitMs));
        var bodyText = await EvalStringAsync("document.body ? document.body.innerText : ''");
        var title = await EvalStringAsync("document.title || ''");
        var currentUrl = webView.Source?.ToString() ?? options.Url;
        return new Dictionary<string, object?>
        {
            ["title"] = title,
            ["url"] = currentUrl,
            ["image"] = options.Image,
            ["waited_seconds"] = stopwatch.Elapsed.TotalSeconds,
            ["body_text"] = bodyText,
            ["captured_network"] = capturedNetwork,
            ["search_response"] = searchResponse
        };
    }

    private Task NavigateAsync(string url)
    {
        var tcs = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        void Handler(object? sender, CoreWebView2NavigationCompletedEventArgs e)
        {
            webView.CoreWebView2.NavigationCompleted -= Handler;
            if (e.IsSuccess)
            {
                tcs.TrySetResult();
            }
            else
            {
                tcs.TrySetException(new InvalidOperationException($"页面导航失败：{e.WebErrorStatus}"));
            }
        }
        webView.CoreWebView2.NavigationCompleted += Handler;
        webView.CoreWebView2.Navigate(url);
        return tcs.Task;
    }

    private async Task WaitForPageReadyAsync()
    {
        var deadline = DateTimeOffset.UtcNow.AddSeconds(30);
        while (DateTimeOffset.UtcNow < deadline)
        {
            var ready = await EvalStringAsync("document.readyState");
            if (ready is "interactive" or "complete")
            {
                return;
            }
            await Task.Delay(250);
        }
        throw new TimeoutException("等待页面就绪超时");
    }

    private async Task UploadImageAsync(string image)
    {
        var count = await EvalIntAsync("document.querySelectorAll('input[type=file]').length");
        if (count <= 0)
        {
            throw new InvalidOperationException("页面里没有找到文件上传控件");
        }
        var evaluateJson = await webView.CoreWebView2.CallDevToolsProtocolMethodAsync(
            "Runtime.evaluate",
            JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["expression"] = "document.querySelector('input[type=file]')",
                ["objectGroup"] = "browser_automation_host",
                ["includeCommandLineAPI"] = false,
                ["silent"] = false,
                ["returnByValue"] = false
            }, options.JsonOptions)
        );
        using var doc = JsonDocument.Parse(evaluateJson);
        var objectId = doc.RootElement.GetProperty("result").GetProperty("objectId").GetString();
        if (string.IsNullOrWhiteSpace(objectId))
        {
            throw new InvalidOperationException("无法定位文件上传控件");
        }
        await webView.CoreWebView2.CallDevToolsProtocolMethodAsync(
            "DOM.setFileInputFiles",
            JsonSerializer.Serialize(new Dictionary<string, object?>
            {
                ["files"] = new[] { Path.GetFullPath(image) },
                ["objectId"] = objectId
            }, options.JsonOptions)
        );
        await Task.Delay(1200);
    }

    private async Task TriggerSearchAsync()
    {
        var script = """
(() => {
  const labels = ['识别', 'Search', '识别图片', '提交', 'Recognize'];
  const nodes = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],[role=button]'));
  for (const label of labels) {
    const target = nodes.find(x => ((x.innerText || x.value || x.getAttribute('aria-label') || '').trim()).includes(label));
    if (target) {
      target.click();
      return true;
    }
  }
  document.body.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  return false;
})()
""";
        await webView.CoreWebView2.ExecuteScriptAsync(script);
    }

    private async Task OnWebResourceResponseReceivedAsync(CoreWebView2WebResourceResponseReceivedEventArgs e)
    {
        var uri = e.Request.Uri ?? "";
        var lower = uri.ToLowerInvariant();
        if (!lower.Contains("animetrace") && !lower.Contains("animedb"))
        {
            return;
        }
        capturedNetwork.Add(["RESP " + e.Response.StatusCode, uri, null]);
        if (e.Request.Method.Equals("POST", StringComparison.OrdinalIgnoreCase) && uri.TrimEnd('/').EndsWith("/v1/search", StringComparison.OrdinalIgnoreCase) && searchResponse["text"] is null)
        {
            string? text = null;
            try
            {
                using var stream = await e.Response.GetContentAsync();
                using var reader = new StreamReader(stream);
                text = await reader.ReadToEndAsync();
            }
            catch (Exception ex)
            {
                text = $"<failed to read response text: {ex.GetType().Name}: {ex.Message}>";
            }
            searchResponse = new Dictionary<string, object?>
            {
                ["status"] = e.Response.StatusCode,
                ["content_type"] = e.Response.Headers.GetHeader("content-type"),
                ["text"] = text,
                ["url"] = uri,
                ["elapsed"] = stopwatch.Elapsed.TotalSeconds
            };
        }
    }

    private async Task<string> EvalStringAsync(string expression)
    {
        var json = await webView.CoreWebView2.ExecuteScriptAsync(expression);
        return JsonSerializer.Deserialize<string>(json) ?? "";
    }

    private async Task<int> EvalIntAsync(string expression)
    {
        var json = await webView.CoreWebView2.ExecuteScriptAsync(expression);
        return JsonSerializer.Deserialize<int>(json);
    }

    private async Task WriteResultAsync(Dictionary<string, object?> result)
    {
        var path = Path.GetFullPath(options.OutputJson);
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        await File.WriteAllTextAsync(path, JsonSerializer.Serialize(result, options.JsonOptions));
        Console.WriteLine("OK");
    }

    private async Task WriteErrorAsync(Exception ex)
    {
        if (!string.IsNullOrWhiteSpace(options.OutputJson))
        {
            var path = Path.GetFullPath(options.OutputJson);
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var result = new Dictionary<string, object?>
            {
                ["error"] = ex.GetType().Name,
                ["message"] = ex.Message
            };
            await File.WriteAllTextAsync(path, JsonSerializer.Serialize(result, options.JsonOptions));
        }
        Console.Error.WriteLine($"{ex.GetType().Name}: {ex.Message}");
    }
}
