using System.Data;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace P1Dashboard;

public partial class VideoIntelligenceWindow : Window
{
    private readonly AieCliClient _cli = new();
    private readonly CancellationTokenSource _lifetime = new();
    private readonly DispatcherTimer _refreshTimer;
    private bool _busy;
    private string? _selectedFindingId;

    public VideoIntelligenceWindow()
    {
        InitializeComponent();
        _refreshTimer = new DispatcherTimer(DispatcherPriority.Background)
        {
            Interval = TimeSpan.FromSeconds(20),
        };
        _refreshTimer.Tick += async (_, _) => await RefreshAsync();
        Loaded += async (_, _) =>
        {
            await RefreshAsync();
            _refreshTimer.Start();
        };
        Closed += (_, _) =>
        {
            _refreshTimer.Stop();
            _lifetime.Cancel();
        };
        FindingsGrid.SelectionChanged += (_, _) =>
        {
            if (FindingsGrid.SelectedItem is DataRowView row
                && row.Row.Table.Columns.Contains("id"))
            {
                _selectedFindingId = row["id"]?.ToString();
            }
        };
    }

    private static string Value(JsonElement element, string name, string fallback = "—")
    {
        if (!element.TryGetProperty(name, out var value) || value.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined)
            return fallback;
        return value.ValueKind == JsonValueKind.String ? value.GetString() ?? fallback : value.ToString();
    }

    private static string FormatNumber(JsonElement element, string name, string suffix = "")
    {
        var value = Value(element, name, "unknown");
        return value == "unknown" || value == "—" ? value : value + suffix;
    }

    private static DataView TableFrom(JsonElement array)
    {
        var table = new DataTable();
        if (array.ValueKind != JsonValueKind.Array)
            return table.DefaultView;

        var rows = array.EnumerateArray().Where(item => item.ValueKind == JsonValueKind.Object).ToList();
        var columns = rows.SelectMany(item => item.EnumerateObject().Select(property => property.Name))
            .Distinct(StringComparer.Ordinal).ToList();
        foreach (var column in columns)
            table.Columns.Add(column, typeof(string));

        foreach (var item in rows)
        {
            var row = table.NewRow();
            foreach (var property in item.EnumerateObject())
            {
                row[property.Name] = property.Value.ValueKind switch
                {
                    JsonValueKind.Null or JsonValueKind.Undefined => "—",
                    JsonValueKind.Object or JsonValueKind.Array => property.Value.GetRawText(),
                    JsonValueKind.String => property.Value.GetString() ?? "",
                    _ => property.Value.ToString(),
                };
            }
            table.Rows.Add(row);
        }
        return table.DefaultView;
    }

    private static string Pretty(JsonElement element) =>
        JsonSerializer.Serialize(element, new JsonSerializerOptions { WriteIndented = true });

    private static string FormatAdvice(JsonElement root)
    {
        var output = new StringBuilder();
        output.AppendLine("EXECUTIVE SUMMARY");
        output.AppendLine(Value(root, "summary"));
        output.AppendLine();
        output.AppendLine($"LOCAL MODEL  {Value(root, "model")}  ·  {FormatNumber(root, "elapsed_seconds", "s")}");
        output.AppendLine("LOCAL-ONLY  ·  no actions executed");
        output.AppendLine();

        if (root.TryGetProperty("observations", out var observations) && observations.ValueKind == JsonValueKind.Array)
        {
            output.AppendLine("EVIDENCE-BASED OBSERVATIONS");
            foreach (var item in observations.EnumerateArray())
            {
                output.AppendLine($"• {Value(item, "statement")}");
                output.AppendLine($"  Evidence: {Value(item, "evidence_event_ids")}");
            }
            output.AppendLine();
        }

        if (root.TryGetProperty("next_steps", out var steps) && steps.ValueKind == JsonValueKind.Array)
        {
            output.AppendLine("SUGGESTED NEXT STEPS");
            var index = 1;
            foreach (var item in steps.EnumerateArray())
            {
                output.AppendLine($"{index}. [{Value(item, "priority").ToUpperInvariant()}] {Value(item, "title")}");
                output.AppendLine($"   {Value(item, "rationale")}");
                output.AppendLine($"   Mode: {Value(item, "mode")} · Evidence: {Value(item, "evidence_event_ids")}");
                index++;
            }
            output.AppendLine();
        }

        if (root.TryGetProperty("unknowns", out var unknowns) && unknowns.ValueKind == JsonValueKind.Array)
        {
            output.AppendLine("WHAT REMAINS UNKNOWN");
            foreach (var item in unknowns.EnumerateArray())
                output.AppendLine($"• {item.GetString()}");
            output.AppendLine();
        }

        output.AppendLine("Diagnosis remains rule-engine driven. Model text explains and prioritizes; it does not change the measured facts or execute remediation.");
        return output.ToString();
    }

    private async Task<CliResult?> RunAsync(params string[] arguments)
    {
        try
        {
            return await _cli.RunAsync(arguments, _lifetime.Token);
        }
        catch (Exception exception)
        {
            FooterStatus.Text = $"AIE command unavailable · {exception.GetType().Name}";
            return null;
        }
    }

    private async Task RefreshAsync()
    {
        if (_busy || !IsLoaded)
            return;

        _busy = true;
        FooterStatus.Text = "Refreshing local video intelligence…";
        try
        {
            var result = await RunAsync("video-dashboard", "--json", "--lookback-hours", "24", "--limit", "500");
            if (result is null || !result.Succeeded)
            {
                FooterStatus.Text = "Video dashboard snapshot unavailable";
                EvaluationOutput.Text = result?.CombinedOutput ?? "The AIE CLI could not be started.";
                return;
            }

            using var document = JsonDocument.Parse(result.StandardOutput);
            var root = document.RootElement;
            var overview = root.GetProperty("overview");

            PlaybackCount.Text = Value(overview, "playback_snapshots", "0");
            FindingCount.Text = Value(overview, "diagnostic_findings", "0");
            ProbeCount.Text = Value(overview, "network_probes", "0");
            FeedbackCount.Text = Value(overview, "user_feedback_records", "0");
            TotalEventCount.Text = Value(overview, "total_events_in_store", "0");

            if (root.TryGetProperty("live_context", out var live) && live.ValueKind == JsonValueKind.Object)
            {
                var builder = new StringBuilder();
                builder.AppendLine($"Playback state     {Value(live, "playback_state")}");
                builder.AppendLine($"Observed           {Value(live, "observed_at")}  ·  age {FormatNumber(live, "age_seconds", "s")}");
                builder.AppendLine($"Stalls / window    {Value(live, "stall_count")}  /  {FormatNumber(live, "observation_window_seconds", "s")}");
                builder.AppendLine($"Buffer ahead       {FormatNumber(live, "buffered_ahead_seconds", "s")}");
                builder.AppendLine($"Progress delta     {FormatNumber(live, "playback_progress_delta_seconds", "s")}");
                builder.AppendLine($"Dropped frames     {FormatNumber(live, "dropped_frames_pct", "%")}");
                builder.AppendLine($"Throughput         {FormatNumber(live, "throughput_mbps", " Mbps")}");
                builder.AppendLine($"Stream requirement {FormatNumber(live, "estimated_required_mbps", " Mbps")}");
                builder.AppendLine($"Packet loss        {FormatNumber(live, "packet_loss_pct", "%")}  · scope {Value(live, "packet_loss_scope")}");
                builder.AppendLine($"Browser CPU        {FormatNumber(live, "cpu_pct", "%")}");
                if (live.TryGetProperty("active_application", out var app) && app.ValueKind == JsonValueKind.Object)
                {
                    builder.AppendLine();
                    builder.AppendLine("FOREGROUND APPLICATION");
                    builder.AppendLine($"Process            {Value(app, "process_name")}  (PID {Value(app, "pid")})");
                    builder.AppendLine($"CPU / memory       {FormatNumber(app, "cpu_pct", "%")}  /  {FormatNumber(app, "memory_rss_mib", " MiB")}");
                    builder.AppendLine($"Threads / age      {Value(app, "thread_count")}  /  {FormatNumber(app, "age_seconds", "s")}");
                    builder.AppendLine($"Window title data  {(Value(app, "window_title_collected", "false") == "true" ? "collected (sensitive)" : "not collected")}");
                }
                if (live.TryGetProperty("network_evidence", out var network) && network.ValueKind == JsonValueKind.Array)
                {
                    builder.AppendLine();
                    builder.AppendLine("CORRELATED NETWORK EVIDENCE");
                    foreach (var item in network.EnumerateArray())
                    {
                        builder.AppendLine(
                            $"{Value(item, "kind")} · age {FormatNumber(item, "age_seconds", "s")} · " +
                            $"connect {FormatNumber(item, "connect_latency_ms", " ms")} · DNS {FormatNumber(item, "resolution_ms", " ms")} · " +
                            $"throughput {FormatNumber(item, "throughput_mbps", " Mbps")} · loss {FormatNumber(item, "packet_loss_pct", "%")}");
                    }
                }
                LiveContextText.Text = builder.ToString();
            }
            else
            {
                LiveContextText.Text = "No fresh playback context. The dashboard is read-only and will show data when the opt-in browser observer has recorded snapshots.";
            }

            LiveHypothesesGrid.ItemsSource = TableFrom(root.GetProperty("live_hypotheses"));
            FindingsGrid.ItemsSource = TableFrom(root.GetProperty("findings"));
            ProbesGrid.ItemsSource = TableFrom(root.GetProperty("probes"));
            EventsGrid.ItemsSource = TableFrom(root.GetProperty("events"));
            FeedbackSummaryGrid.ItemsSource = TableFrom(root.GetProperty("feedback_summary"));
            EventTypesGrid.ItemsSource = TableFrom(overview.GetProperty("event_types"));

            if (root.TryGetProperty("models", out var models))
            {
                var modelText = new StringBuilder();
                modelText.AppendLine("Installed local Ollama models");
                foreach (var model in models.GetProperty("installed").EnumerateArray())
                    modelText.AppendLine($"  • {model.GetString()}");
                modelText.AppendLine();
                foreach (var tier in new[] { "routine", "complex", "embedding" })
                {
                    var choice = models.GetProperty(tier);
                    modelText.AppendLine($"{tier.ToUpperInvariant()}: {Value(choice, "model", "unavailable")}");
                    modelText.AppendLine($"  {Value(choice, "reason")}");
                }
                modelText.AppendLine();
                modelText.AppendLine($"Available RAM: {Value(models, "memory_available_gib")} GiB");
                modelText.AppendLine($"CPU: {Value(models, "cpu_physical")} physical / {Value(models, "cpu_logical")} logical");
                var discoveryError = Value(models, "discovery_error", "");
                if (!string.IsNullOrWhiteSpace(discoveryError) && discoveryError != "—")
                    modelText.AppendLine($"Ollama discovery: {discoveryError}");
                ModelStatusText.Text = modelText.ToString();
            }

            FooterStatus.Text = $"Updated {DateTime.Now:T} · 24-hour view · read-only refresh every 20 seconds";
        }
        catch (Exception exception)
        {
            FooterStatus.Text = $"Dashboard refresh failed · {exception.GetType().Name}";
        }
        finally
        {
            _busy = false;
        }
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e) => await RefreshAsync();

    private async void Explain_Click(object sender, RoutedEventArgs e)
    {
        var tier = AdvisorTier.SelectedIndex == 1 ? "complex" : "routine";
        FooterStatus.Text = $"Requesting grounded {tier} reasoning from local Ollama…";
        var result = await RunAsync("video-advice", "--tier", tier);
        if (result is null || !result.Succeeded)
        {
            AdvisorOutput.Text = result?.CombinedOutput ?? "Local advisor unavailable.";
            FooterStatus.Text = "Local advisor did not return a grounded explanation.";
            return;
        }

        try
        {
            using var document = JsonDocument.Parse(result.StandardOutput);
            AdvisorOutput.Text = FormatAdvice(document.RootElement);
            FooterStatus.Text = $"Local explanation generated · {Value(document.RootElement, "model")} · {FormatNumber(document.RootElement, "elapsed_seconds", "s")}";
        }
        catch (JsonException)
        {
            AdvisorOutput.Text = result.CombinedOutput;
            FooterStatus.Text = "Advisor returned output that could not be displayed as structured JSON.";
        }
    }

    private async void SaveFeedback_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(_selectedFindingId))
        {
            MessageBox.Show(this, "Select a diagnostic finding first.", "Video intelligence", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }
        var outcome = (FeedbackOutcome.SelectedItem as ComboBoxItem)?.Content?.ToString() ?? "not_attempted";
        var result = await RunAsync("feedback", _selectedFindingId, "--outcome", outcome);
        EvaluationOutput.Text = result?.CombinedOutput ?? "Feedback command unavailable.";
        await RefreshAsync();
    }

    private async void Evaluate_Click(object sender, RoutedEventArgs e)
    {
        FooterStatus.Text = "Running the bundled synthetic regression corpus…";
        var result = await RunAsync("video-evaluate");
        EvaluationOutput.Text = result?.CombinedOutput ?? "Evaluation command unavailable.";
        FooterStatus.Text = result?.Succeeded == true ? "Synthetic regression evaluation completed." : "Evaluation did not complete.";
    }

    private async void Export_Click(object sender, RoutedEventArgs e)
    {
        var answer = MessageBox.Show(
            this,
            "Create an anonymized field-candidate file from the last 24 hours of local video observations?\n\nThe exporter never overwrites an existing file. Candidates still require independent human labels.",
            "Confirm field-candidate export",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning);
        if (answer != MessageBoxResult.Yes)
            return;

        var directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AIE");
        Directory.CreateDirectory(directory);
        var destination = Path.Combine(directory, "video_field_trace_candidates.json");
        var result = await RunAsync(
            "video-trace-export", "--confirm", "--hours", "24", "--limit", "100", "--output", destination);
        EvaluationOutput.Text = result?.CombinedOutput ?? "Field export command unavailable.";
        FooterStatus.Text = result?.Succeeded == true ? "Field candidates exported for manual labeling." : "Field candidate export was not completed.";
    }
}
