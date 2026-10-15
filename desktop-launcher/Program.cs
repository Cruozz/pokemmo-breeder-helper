using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly: AssemblyTitle("Pokemmo孵蛋助手")]
[assembly: AssemblyProduct("Pokemmo孵蛋助手")]
[assembly: AssemblyCompany("晨若")]
[assembly: AssemblyVersion("__VERSION__.0")]
[assembly: AssemblyFileVersion("__VERSION__")]

internal static class Program
{
    const string PayloadHash = "__PAYLOAD_HASH__";
    const string CoreHash = "__CORE_HASH__";
    static string CacheRoot;
    static string Runtime;
    static string Core;
    static string SelectionPath;
    static string[] CacheCandidates;
    static string Operation = "检查运行组件";

    [STAThread]
    static int Main(string[] args)
    {
        try
        {
            CacheCandidates = new string[] {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PokeMMO-Breeder-Helper", "runtime"),
                Path.Combine(Path.GetTempPath(), "PokeMMO-Breeder-Helper", "runtime")
            };
            bool prepared = false;
            foreach (string root in CacheCandidates)
            {
                SetCacheRoot(root);
                if (SelectPreparedRuntime()) { prepared = true; break; }
            }
            if (!prepared)
            {
                SetCacheRoot(CacheCandidates[0]);
                if (args.Length == 0) PrepareWithProgress();
                else Prepare(null, CancellationToken.None);
            }
            Operation = "启动核心程序";
            ProcessStartInfo info = new ProcessStartInfo(Core);
            info.Arguments = String.Join(" ", Array.ConvertAll(args, Quote));
            info.UseShellExecute = false;
            info.WorkingDirectory = Runtime;
            using (Process child = Process.Start(info))
            {
                child.WaitForExit();
                return child.ExitCode;
            }
        }
        catch (Exception error)
        {
            if (error is OperationCanceledException) return 0;
            // Diagnostic invocations stay silent; normal launches show an actionable error.
            string log = WriteFailureLog(error);
            if (args.Length == 0) MessageBox.Show("启动失败：" + Operation + "。\n\n" + error.Message
                + "\n\n请将 ZIP 完整解压后运行；若仍失败，请把此提示和启动日志发给作者。"
                + (log.Length > 0 ? "\n启动日志：" + log : ""),
                "Pokemmo孵蛋助手", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    static string HashFile(string path)
    {
        using (SHA256 hash = SHA256.Create())
        using (FileStream stream = File.OpenRead(path))
            return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
    }

    static bool Ready()
    {
        try {
            string marker = Path.Combine(Runtime, "prepared.sha256");
            return File.Exists(Core) && File.Exists(marker) && File.ReadAllText(marker).Trim() == PayloadHash
                   && HashFile(Core) == CoreHash;
        } catch (IOException) { return false; } catch (UnauthorizedAccessException) { return false; }
    }

    static void SetCacheRoot(string root)
    {
        CacheRoot = Path.GetFullPath(root);
        Runtime = Path.Combine(CacheRoot, "V__VERSION__-" + PayloadHash.Substring(0, 16));
        Core = Path.Combine(Runtime, "PokeMMO-Breeder-Helper.exe");
        SelectionPath = Path.Combine(CacheRoot, "ready-V__VERSION__-" + PayloadHash.Substring(0, 16) + ".txt");
    }

    static bool SelectPreparedRuntime()
    {
        if (Ready()) return true;
        try {
            if (!File.Exists(SelectionPath) || new FileInfo(SelectionPath).Length > 256) return false;
            string name = File.ReadAllText(SelectionPath).Trim();
            string prefix = "V__VERSION__-" + PayloadHash.Substring(0, 16) + "-";
            if (!name.StartsWith(prefix, StringComparison.Ordinal) || name != Path.GetFileName(name)) return false;
            string candidate = Path.GetFullPath(Path.Combine(CacheRoot, name));
            CheckCachePath(candidate);
            Runtime = candidate;
            Core = Path.Combine(Runtime, "PokeMMO-Breeder-Helper.exe");
            return Ready();
        } catch (IOException) { return false; } catch (UnauthorizedAccessException) { return false; }
          catch (ArgumentException) { return false; }
    }

    static string CreateStageDirectory()
    {
        Exception last = null;
        foreach (string root in CacheCandidates)
        {
            try {
                SetCacheRoot(root);
                Directory.CreateDirectory(CacheRoot);
                string path = Path.Combine(CacheRoot, "V__VERSION__-" + PayloadHash.Substring(0, 16) + "-" + Guid.NewGuid().ToString("N").Substring(0, 12));
                CheckCachePath(path);
                Directory.CreateDirectory(path);
                return path;
            } catch (IOException error) { last = error; } catch (UnauthorizedAccessException error) { last = error; }
        }
        throw new IOException("无法创建运行组件目录，请检查当前用户的文件夹写入权限。", last);
    }

    static string WriteFailureLog(Exception error)
    {
        foreach (string root in CacheCandidates ?? new string[] { Path.GetTempPath() })
        {
            try {
                Directory.CreateDirectory(root);
                string path = Path.Combine(root, "startup.log");
                File.AppendAllText(path, DateTime.Now.ToString("O") + "\n阶段：" + Operation
                    + "\n运行目录：" + Runtime + "\n" + error.ToString() + "\n\n", Encoding.UTF8);
                return path;
            } catch (IOException) {} catch (UnauthorizedAccessException) {}
        }
        return "";
    }

    static void PrepareWithProgress()
    {
        Application.EnableVisualStyles();
        using (Form form = new Form())
        using (Label label = new Label())
        using (ProgressBar progress = new ProgressBar())
        using (CancellationTokenSource cancellation = new CancellationTokenSource())
        {
            form.Text = "Pokemmo孵蛋助手";
            form.ClientSize = new System.Drawing.Size(360, 95);
            form.StartPosition = FormStartPosition.CenterScreen;
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.MaximizeBox = false;
            form.MinimizeBox = false;
            form.ControlBox = true;
            label.Text = "首次启动，正在准备运行组件…";
            label.SetBounds(16, 14, 328, 24);
            progress.SetBounds(16, 48, 328, 20);
            progress.Style = ProgressBarStyle.Marquee;
            form.Controls.Add(label);
            form.Controls.Add(progress);
            Exception failure = null;
            Task preparing = null;
            int finished = 0;
            form.FormClosing += delegate { if (Interlocked.CompareExchange(ref finished, 0, 0) == 0) cancellation.Cancel(); };
            form.Shown += delegate {
                preparing = Task.Factory.StartNew(delegate {
                    try { Prepare(delegate(int value) {
                        Dispatch(form, delegate {
                            progress.Style = ProgressBarStyle.Continuous;
                            progress.Value = Math.Min(100, value);
                        });
                    }, cancellation.Token); }
                    catch (Exception error) { failure = error; }
                    finally {
                        Interlocked.Exchange(ref finished, 1);
                        Dispatch(form, delegate { form.Close(); });
                    }
                });
            };
            form.ShowDialog();
            if (preparing != null) preparing.Wait();
            if (failure != null) throw failure;
            cancellation.Token.ThrowIfCancellationRequested();
        }
    }

    static void Dispatch(Form form, Action action)
    {
        // Closing the preparation window may destroy its handle between these checks.
        try {
            if (!form.IsDisposed && form.IsHandleCreated) form.BeginInvoke((Action)delegate {
                if (!form.IsDisposed) action();
            });
        } catch (InvalidOperationException) {}
    }

    static void Prepare(Action<int> progress, CancellationToken cancellation)
    {
        using (Mutex mutex = new Mutex(false, "Local\\PokemmoRuntime-" + PayloadHash.Substring(0, 24)))
        {
            bool acquired = false;
            string stage = null;
            try
            {
                DateTime deadline = DateTime.UtcNow.AddMinutes(3);
                while (!acquired && DateTime.UtcNow < deadline)
                {
                    cancellation.ThrowIfCancellationRequested();
                    try { acquired = mutex.WaitOne(100); }
                    catch (AbandonedMutexException) { acquired = true; }
                }
                if (!acquired) throw new IOException("运行组件正在准备，请稍后重新打开。");
                cancellation.ThrowIfCancellationRequested();
                if (SelectPreparedRuntime()) return;
                Operation = "创建运行组件目录";
                stage = CreateStageDirectory();
                if (SelectPreparedRuntime()) return;
                Operation = "写入内置运行组件";
                string archivePath = Path.Combine(stage, "payload.zip");
                using (Stream resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("RuntimePayload"))
                using (FileStream archive = File.Create(archivePath))
                {
                    if (resource == null) throw new IOException("运行组件缺失，请重新下载软件。");
                    resource.CopyTo(archive);
                }
                Operation = "校验运行组件";
                if (HashFile(archivePath) != PayloadHash) throw new IOException("程序数据校验失败，请重新下载软件。");
                Operation = "解压运行组件";
                using (ZipArchive archive = ZipFile.OpenRead(archivePath))
                {
                    long total = 0, written = 0;
                    int lastProgress = -1;
                    foreach (ZipArchiveEntry entry in archive.Entries) total += entry.Length;
                    string prefix = Path.GetFullPath(stage) + Path.DirectorySeparatorChar;
                    foreach (ZipArchiveEntry entry in archive.Entries)
                    {
                        cancellation.ThrowIfCancellationRequested();
                        string path = Path.GetFullPath(Path.Combine(stage, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                        if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("运行组件路径无效。");
                        if (entry.Name.Length == 0) { Directory.CreateDirectory(path); continue; }
                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                        using (Stream input = entry.Open())
                        using (FileStream output = File.Create(path)) input.CopyTo(output);
                        written += entry.Length;
                        int percent = total > 0 ? (int)(written * 100 / total) : 100;
                        if (progress != null && percent != lastProgress) { progress(percent); lastProgress = percent; }
                    }
                }
                File.Delete(archivePath);
                string stagedCore = Path.Combine(stage, "PokeMMO-Breeder-Helper.exe");
                if (!File.Exists(stagedCore) || HashFile(stagedCore) != CoreHash) throw new IOException("核心程序校验失败。");
                File.WriteAllText(Path.Combine(stage, "prepared.sha256"), PayloadHash);
                cancellation.ThrowIfCancellationRequested();
                CheckCachePath(stage);
                // A scanner/Explorer handle without delete sharing can deny
                // Directory.Move after successful extraction. Keep this fully
                // verified directory in place and publish only its relative
                // name. A partial pointer is rejected by the next hash check.
                Operation = "记录已准备的运行目录";
                Runtime = stage;
                Core = stagedCore;
                stage = null;
                try { File.WriteAllText(SelectionPath, Path.GetFileName(Runtime), Encoding.UTF8); }
                catch (IOException) {} catch (UnauthorizedAccessException) {}
            }
            finally
            {
                if (stage != null)
                {
                    string checkedStage = Path.GetFullPath(stage);
                    string checkedRoot = Path.GetFullPath(CacheRoot) + Path.DirectorySeparatorChar;
                    if (checkedStage.StartsWith(checkedRoot, StringComparison.OrdinalIgnoreCase))
                        try { Directory.Delete(checkedStage, true); } catch (IOException) {} catch (UnauthorizedAccessException) {}
                }
                if (acquired) mutex.ReleaseMutex();
            }
        }
    }

    static void CheckCachePath(string path)
    {
        string prefix = Path.GetFullPath(CacheRoot) + Path.DirectorySeparatorChar;
        if (!Path.GetFullPath(path).StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) throw new IOException("缓存路径无效。");
    }

    static string Quote(string value)
    {
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"') result.Append('\\', slashes * 2 + 1);
            else result.Append('\\', slashes);
            result.Append(character);
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        result.Append('"');
        return result.ToString();
    }
}
