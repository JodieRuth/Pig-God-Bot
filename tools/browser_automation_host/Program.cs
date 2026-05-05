namespace browser_automation_host;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm(HostOptions.Parse(args)));
    }
}
