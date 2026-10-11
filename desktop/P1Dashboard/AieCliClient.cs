using System.ComponentModel;
using System.Diagnostics;

namespace P1Dashboard;

internal sealed record CliResult(int ExitCode, string StandardOutput, string StandardError)
{
    public bool Succeeded => ExitCode == 0;
    public string CombinedOutput =>
        string.Join(
            Environment.NewLine,
            new[] { StandardOutput.TrimEnd(), StandardError.TrimEnd() }
                .Where(value => !string.IsNullOrWhiteSpace(value)));
}

internal sealed class AieCliClient
{
    private static readonly TimeSpan DefaultTimeout = TimeSpan.FromMinutes(3);

    public async Task<CliResult> RunAsync(
        IReadOnlyList<string> arguments,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(arguments);
        if (arguments.Count == 0)
        {
            throw new ArgumentException("A fixed AIE subcommand is required.", nameof(arguments));
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = "aie",
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };

        // ArgumentList avoids shell parsing and command-string injection.
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = new Process { StartInfo = startInfo };
        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException("The AIE CLI process did not start.");
            }
        }
        catch (Win32Exception exception)
        {
            throw new InvalidOperationException(
                "The 'aie' executable was not found. Install the P1- CLI and add its Scripts folder to PATH.",
                exception);
        }

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(DefaultTimeout);

        var stdoutTask = process.StandardOutput.ReadToEndAsync();
        var stderrTask = process.StandardError.ReadToEndAsync();
        try
        {
            await process.WaitForExitAsync(timeout.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
            try
            {
                if (!process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                }
            }
            catch (InvalidOperationException)
            {
                // The process exited while cancellation was being handled.
            }

            throw;
        }

        var stdout = await stdoutTask.ConfigureAwait(false);
        var stderr = await stderrTask.ConfigureAwait(false);
        return new CliResult(process.ExitCode, stdout, stderr);
    }
}
