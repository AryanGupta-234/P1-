using System.IO;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;

namespace P1Dashboard;

public partial class MainWindow : Window
{
    private readonly AieCliClient _cli = new();
    private readonly CancellationTokenSource _lifetime = new();
    private bool _busy;

    public MainWindow()
    {
        InitializeComponent();
        Loaded += MainWindow_Loaded;
        Closed += (_, _) => _lifetime.Cancel();
    }

    private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
    {
        await RefreshDashboardAsync();
    }

    private async Task<CliResult?> InvokeAsync(
        string command,
        params string[] arguments)
    {
        if (_busy)
        {
            return null;
        }

        _busy = true;
        FooterStatus.Text = $"Running aie {command}…";
        try
        {
            var values = new List<string> { command };
            values.AddRange(arguments);
            var result = await _cli.RunAsync(values, _lifetime.Token);
            OutputBox.Text = result.CombinedOutput;
            FooterStatus.Text = result.Succeeded
                ? $"Completed · aie {command}"
                : $"aie {command} returned exit code {result.ExitCode}";
            return result;
        }
        catch (OperationCanceledException)
        {
            FooterStatus.Text = "The CLI operation was cancelled or timed out.";
            OutputBox.Text = "No further action was started by the dashboard.";
            return null;
        }
        catch (Exception exception)
        {
            FooterStatus.Text = "P1- CLI unavailable";
            OutputBox.Text = $"{exception.GetType().Name}: {exception.Message}";
            return null;
        }
        finally
        {
            _busy = false;
        }
    }

    private async Task RefreshDashboardAsync()
    {
        if (_busy)
        {
            return;
        }

        _busy = true;
        FooterStatus.Text = "Refreshing local status…";
        try
        {
            var statusTask = _cli.RunAsync(["status"], _lifetime.Token);
            var healthTask = _cli.RunAsync(["health"], _lifetime.Token);
            var retentionTask = _cli.RunAsync(["retention-status"], _lifetime.Token);
            var tasksTask = _cli.RunAsync(["task", "list", "--limit", "50"], _lifetime.Token);

            await Task.WhenAll(statusTask, healthTask, retentionTask, tasksTask);
            var status = await statusTask;
            var health = await healthTask;
            var retention = await retentionTask;
            var tasks = await tasksTask;

            ObserverOutput.Text = status.CombinedOutput + Environment.NewLine
                + Environment.NewLine + health.CombinedOutput;
            TaskHistoryOutput.Text = tasks.CombinedOutput;
            OutputBox.Text = retention.CombinedOutput;

            var statusText = status.StandardOutput;
            ObserverValue.Text = statusText.Contains("paused", StringComparison.OrdinalIgnoreCase)
                ? "Paused"
                : statusText.Contains("running", StringComparison.OrdinalIgnoreCase)
                    ? "Running"
                    : "Check status";

            var eventMatch = Regex.Match(
                retention.StandardOutput,
                @"Events\s+(\d+)",
                RegexOptions.IgnoreCase);
            EventCountValue.Text = eventMatch.Success ? eventMatch.Groups[1].Value : "Local";

            var taskLines = tasks.StandardOutput
                .Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries)
                .Count(line =>
                    line.Contains("queued", StringComparison.OrdinalIgnoreCase)
                    || line.Contains("running", StringComparison.OrdinalIgnoreCase)
                    || line.Contains("completed", StringComparison.OrdinalIgnoreCase)
                    || line.Contains("awaiting_", StringComparison.OrdinalIgnoreCase));
            TaskCountValue.Text = taskLines.ToString();

            var dataDirectory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "AIE");
            var killPath = Path.Combine(dataDirectory, "execution.kill");
            var enabledPath = Path.Combine(dataDirectory, "execution.enabled");
            ExecutionValue.Text = File.Exists(killPath)
                ? "KILLED"
                : File.Exists(enabledPath)
                    ? "Enabled"
                    : "Disabled";

            FooterStatus.Text = "Local status refreshed. The dashboard did not start observation.";
        }
        catch (Exception exception)
        {
            FooterStatus.Text = "Status refresh incomplete";
            OutputBox.Text = $"{exception.GetType().Name}: {exception.Message}";
        }
        finally
        {
            _busy = false;
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        await RefreshDashboardAsync();
    }

    private async void RunAgent_Click(object sender, RoutedEventArgs e)
    {
        var goal = GoalInput.Text.Trim();
        var model = ModelInput.Text.Trim();
        if (goal.Length is < 1 or > 500)
        {
            MessageBox.Show(
                this,
                "Enter a goal between 1 and 500 characters.",
                "P1- Agent",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        if (string.IsNullOrWhiteSpace(model) || model.Length > 200)
        {
            MessageBox.Show(
                this,
                "Enter the exact name of an already-installed local model.",
                "P1- Agent",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        if (!int.TryParse(StepLimitInput.Text, out var maxSteps) || maxSteps is < 1 or > 25)
        {
            MessageBox.Show(
                this,
                "The step limit must be between 1 and 25.",
                "P1- Agent",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        if (SensitiveMemoryCheck.IsChecked == true && WithMemoryCheck.IsChecked != true)
        {
            MessageBox.Show(
                this,
                "Enable local memory retrieval before including sensitive memories.",
                "P1- Agent",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        var arguments = new List<string>
        {
            "agent", "run", goal,
            "--model", model,
            "--max-steps", maxSteps.ToString(),
        };
        if (WithMemoryCheck.IsChecked == true)
        {
            arguments.Add("--with-memory");
        }
        if (SensitiveMemoryCheck.IsChecked == true)
        {
            arguments.Add("--include-sensitive-memory");
        }

        RunAgentButton.IsEnabled = false;
        try
        {
            var result = await _cli.RunAsync(arguments, _lifetime.Token);
            OutputBox.Text = result.CombinedOutput;
            FooterStatus.Text = result.Succeeded
                ? "Agent run reached its next recorded state."
                : $"Agent command returned exit code {result.ExitCode}";
        }
        catch (Exception exception)
        {
            OutputBox.Text = $"{exception.GetType().Name}: {exception.Message}";
            FooterStatus.Text = "Agent launch failed";
        }
        finally
        {
            RunAgentButton.IsEnabled = true;
        }

        await RefreshDashboardAsync();
    }

    private async void PauseObserver_Click(object sender, RoutedEventArgs e)
    {
        await InvokeAsync("pause");
        await RefreshDashboardAsync();
    }

    private async void ResumeObserver_Click(object sender, RoutedEventArgs e)
    {
        await InvokeAsync("resume");
        await RefreshDashboardAsync();
    }

    private async void KillExecution_Click(object sender, RoutedEventArgs e)
    {
        var answer = MessageBox.Show(
            this,
            "Activate the global kill switch? Registered capability execution will be blocked.",
            "Confirm emergency stop",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning);
        if (answer != MessageBoxResult.Yes)
        {
            return;
        }

        await InvokeAsync("execution-kill");
        await RefreshDashboardAsync();
    }

    private async void DisableExecution_Click(object sender, RoutedEventArgs e)
    {
        await InvokeAsync("execution-disable");
        await RefreshDashboardAsync();
    }

    private async void TaskHistory_Click(object sender, RoutedEventArgs e)
    {
        await InvokeAsync("task", "list", "--limit", "100");
        if (OutputBox.Text.Length > 0)
        {
            TaskHistoryOutput.Text = OutputBox.Text;
        }
    }

    private async void MemoryReview_Click(object sender, RoutedEventArgs e)
    {
        await InvokeAsync("memory-conflicts");
    }

    private async void Permissions_Click(object sender, RoutedEventArgs e)
    {
        await InvokeAsync("capability-permissions");
    }

    private async void Observer_Click(object sender, RoutedEventArgs e)
    {
        await InvokeAsync("health");
        ObserverOutput.Text = OutputBox.Text;
    }

    private void FocusAgent_Click(object sender, RoutedEventArgs e)
    {
        AgentCard.BringIntoView();
        GoalInput.Focus();
    }
}
