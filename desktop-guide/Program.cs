using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace BreederParallelGuide
{
    internal static class Program
    {
        internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024 };
        [STAThread]
        private static void Main(string[] args)
        {
            var options = new Dictionary<string, string>();
            for (int i = 0; i + 1 < args.Length; i += 2) options[args[i]] = args[i + 1];
            try
            {
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new GuideWindow(options));
            }
            catch (Exception error)
            {
                string report;
                if (options.TryGetValue("--status", out report) || options.TryGetValue("--self-test", out report))
                    File.WriteAllText(report, Json.Serialize(new { ok = false, error = error.ToString() }));
                Environment.ExitCode = 1;
            }
        }
    }

    internal sealed class GuideWindow : Form
    {
        private const string Host = "breeder-parallel-guide.local";
        private const string Home = "https://" + Host + "/index.html";
        private readonly Dictionary<string, string> options;
        private readonly WebView2 view = new WebView2 { Dock = DockStyle.Fill };
        private readonly Label loading = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, Text = "正在打开攻略…" };
        private readonly Button retry = new Button { Dock = DockStyle.Bottom, Height = 44, Text = "重新打开攻略", Visible = false };
        private readonly LinkLabel download = new LinkLabel { Dock = DockStyle.Bottom, Height = 44, TextAlign = ContentAlignment.MiddleCenter, Text = "微软官方下载页面", Visible = false };
        private readonly Timer parentTimer = new Timer { Interval = 200 };
        private readonly IntPtr parent;
        private readonly uint ownerPid;
        private readonly bool test;
        private CoreWebView2Environment environment;
        private bool testing;
        private bool configured;
        private TaskCompletionSource<bool> reloadWaiter;
        private Size previousSize;

        internal GuideWindow(Dictionary<string, string> args)
        {
            options = args;
            test = args.ContainsKey("--self-test");
            parent = args.ContainsKey("--parent") ? new IntPtr(long.Parse(args["--parent"])) : IntPtr.Zero;
            ownerPid = args.ContainsKey("--owner-pid") ? uint.Parse(args["--owner-pid"]) : 0;
            if (!test && !ValidParent()) throw new InvalidOperationException("攻略容器已关闭。");
            Text = "平行五通攻略";
            ShowInTaskbar = false;
            FormBorderStyle = FormBorderStyle.None;
            StartPosition = FormStartPosition.Manual;
            AutoScaleMode = AutoScaleMode.None;
            BackColor = Color.White;
            Size = new Size(900, 650);
            if (test && parent == IntPtr.Zero) { Location = new Point(-30000, -30000); Opacity = 0; }
            Controls.Add(view);
            Controls.Add(loading);
            Controls.Add(retry);
            Controls.Add(download);
            retry.Click += async delegate { await Initialize(); };
            download.LinkClicked += delegate { OpenExternal("https://developer.microsoft.com/microsoft-edge/webview2/"); };
            parentTimer.Tick += delegate { if (!ValidParent()) Close(); else FitParent(); };
            Shown += async delegate
            {
                if (parent != IntPtr.Zero)
                {
                    // Remove top-level window styles before attaching to the Tk content frame.
                    long style = GetWindowLong(Handle, -16).ToInt64();
                    SetWindowLong(Handle, -16, new IntPtr((style & ~0x80000000L) | 0x40000000L));
                    SetParent(Handle, parent);
                    FitParent();
                    parentTimer.Start();
                }
                WriteStatus(false, null);
                await Initialize();
            };
            FormClosed += delegate { parentTimer.Stop(); parentTimer.Dispose(); view.Dispose(); };
        }

        private bool ValidParent()
        {
            if (parent == IntPtr.Zero) return test;
            uint pid;
            return IsWindow(parent) && GetWindowThreadProcessId(parent, out pid) != 0 && pid == ownerPid;
        }

        private void FitParent()
        {
            RECT rect;
            if (!GetClientRect(parent, out rect)) return;
            var size = new Size(Math.Max(1, rect.Right), Math.Max(1, rect.Bottom));
            if (size == previousSize) return;
            previousSize = size;
            SetWindowPos(Handle, IntPtr.Zero, 0, 0, size.Width, size.Height, 0x0014);
        }

        private void WriteStatus(bool ready, string error)
        {
            string path;
            if (options.TryGetValue("--status", out path))
                File.WriteAllText(path, Program.Json.Serialize(new { ready = ready, error = error, hwnd = Handle.ToInt64() }));
        }

        private async Task Initialize()
        {
            try
            {
                retry.Visible = false;
                download.Visible = false;
                view.Visible = true;
                loading.Visible = true;
                loading.Text = "正在打开攻略…";
                CoreWebView2Environment.SetLoaderDllFolderPath(AppDomain.CurrentDomain.BaseDirectory);
                if (environment == null) environment = await CoreWebView2Environment.CreateAsync(null, options["--profile"]);
                if (IsDisposed) return;
                await view.EnsureCoreWebView2Async(environment);
                if (IsDisposed) return;
                var core = view.CoreWebView2;
                if (configured) { core.Navigate(Home); return; }
                configured = true;
                core.SetVirtualHostNameToFolderMapping(Host, options["--site"], CoreWebView2HostResourceAccessKind.DenyCors);
                core.Settings.AreDevToolsEnabled = false;
                core.Settings.AreDefaultContextMenusEnabled = false;
                core.Settings.AreBrowserAcceleratorKeysEnabled = false;
                core.Settings.IsStatusBarEnabled = false;
                core.Settings.IsWebMessageEnabled = false;
                core.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e)
                {
                    if (IsLocal(e.Uri)) return;
                    e.Cancel = true;
                    OpenExternal(e.Uri);
                };
                core.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e)
                {
                    e.Handled = true;
                    if (IsLocal(e.Uri) || e.Uri.StartsWith("data:image/", StringComparison.OrdinalIgnoreCase))
                        OpenImage(e.Uri);
                    else OpenExternal(e.Uri);
                };
                core.NavigationCompleted += async delegate(object sender, CoreWebView2NavigationCompletedEventArgs e)
                {
                    if (IsDisposed) return;
                    if (!e.IsSuccess) { Fail(new InvalidOperationException("攻略页面加载失败，请重新打开攻略。")); return; }
                    loading.Visible = false;
                    WriteStatus(true, null);
                    if (reloadWaiter != null) reloadWaiter.TrySetResult(true);
                    if (test && !testing) { testing = true; await SelfTest(); }
                };
                core.Navigate(Home);
            }
            catch (Exception error) { if (!IsDisposed) Fail(error); }
        }

        private void Fail(Exception error)
        {
            WriteStatus(false, error.Message);
            if (test)
            {
                File.WriteAllText(options["--self-test"], Program.Json.Serialize(new { ok = false, error = error.ToString() }));
                Environment.ExitCode = 1;
                Close();
                return;
            }
            view.Visible = false;
            loading.Visible = true;
            loading.Text = error is WebView2RuntimeNotFoundException
                ? "这台电脑缺少 Microsoft Edge WebView2 运行时。\n安装后重新打开攻略。"
                : "攻略暂时无法打开，请点击下方按钮重试。\n" + error.Message;
            retry.Visible = true;
            download.Visible = error is WebView2RuntimeNotFoundException;
        }

        private static bool IsLocal(string value)
        {
            Uri uri;
            return Uri.TryCreate(value, UriKind.Absolute, out uri) && uri.Scheme == "https" && uri.Host == Host && uri.IsDefaultPort;
        }

        private static void OpenExternal(string value)
        {
            Uri uri;
            if (!Uri.TryCreate(value, UriKind.Absolute, out uri) || (uri.Scheme != "https" && uri.Scheme != "http")) return;
            try { Process.Start(new ProcessStartInfo(value) { UseShellExecute = true }); } catch { }
        }

        private async void OpenImage(string uri)
        {
            var imageWindow = new Form { Text = "图片 · 平行五通攻略", Size = new Size(1000, 750), StartPosition = FormStartPosition.CenterScreen };
            var imageView = new WebView2 { Dock = DockStyle.Fill };
            imageWindow.Controls.Add(imageView);
            imageWindow.FormClosed += delegate { imageView.Dispose(); };
            imageWindow.Show(this);
            try
            {
                await imageView.EnsureCoreWebView2Async(environment);
                if (imageWindow.IsDisposed) return;
                var core = imageView.CoreWebView2;
                core.SetVirtualHostNameToFolderMapping(Host, options["--site"], CoreWebView2HostResourceAccessKind.DenyCors);
                core.Settings.AreDevToolsEnabled = false;
                core.Settings.AreDefaultContextMenusEnabled = false;
                core.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e)
                { if (!IsLocal(e.Uri) && !e.Uri.StartsWith("data:image/", StringComparison.OrdinalIgnoreCase)) e.Cancel = true; };
                core.Navigate(uri);
            }
            catch { if (!imageWindow.IsDisposed) imageWindow.Close(); }
        }

        private async Task SelfTest()
        {
            try
            {
                string script = File.ReadAllText(Path.Combine(options["--site"], "self-test.js"));
                string onOpen = await view.CoreWebView2.ExecuteScriptAsync("JSON.parse(localStorage.getItem('pokemmo-parallel-reader-progress-v1')).completedById.u1.length === 1");
                string result = await view.CoreWebView2.ExecuteScriptAsync(script);
                var record = Program.Json.Deserialize<Dictionary<string, object>>(result);
                if (!(bool)record["ok"]) throw new InvalidOperationException(result);
                // Reload exercises the actual disk-backed progress profile.
                reloadWaiter = new TaskCompletionSource<bool>();
                await view.CoreWebView2.ExecuteScriptAsync("location.reload()");
                if (await Task.WhenAny(reloadWaiter.Task, Task.Delay(15000)) != reloadWaiter.Task)
                    throw new InvalidOperationException("攻略重新加载超时。");
                string persisted = await view.CoreWebView2.ExecuteScriptAsync("JSON.parse(localStorage.getItem('pokemmo-parallel-reader-progress-v1')).completedById.u1.length === 1");
                if (persisted != "true") throw new InvalidOperationException("阅读进度未能跨重新加载保留。");
                record["progress_reload"] = true;
                record["progress_on_open"] = onOpen == "true";
                record["embedded"] = parent != IntPtr.Zero && GetParent(Handle) == parent;
                RECT parentRect, childRect;
                GetClientRect(parent, out parentRect);
                GetClientRect(Handle, out childRect);
                if (parent != IntPtr.Zero && (parentRect.Right != childRect.Right || parentRect.Bottom != childRect.Bottom))
                    throw new InvalidOperationException("攻略子窗口未适合容器大小。");
                record["fits_parent"] = true;
                record["browser_version"] = environment.BrowserVersionString;
                File.WriteAllText(options["--self-test"], Program.Json.Serialize(record));
                Close();
            }
            catch (Exception error) { Fail(error); }
        }

        [StructLayout(LayoutKind.Sequential)] private struct RECT { public int Left, Top, Right, Bottom; }
        [DllImport("user32.dll")] private static extern bool IsWindow(IntPtr handle);
        [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr handle, out uint pid);
        [DllImport("user32.dll")] private static extern bool GetClientRect(IntPtr handle, out RECT rect);
        [DllImport("user32.dll")] private static extern IntPtr SetParent(IntPtr handle, IntPtr parentHandle);
        [DllImport("user32.dll")] private static extern IntPtr GetParent(IntPtr handle);
        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] private static extern IntPtr GetWindowLong(IntPtr handle, int index);
        [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] private static extern IntPtr SetWindowLong(IntPtr handle, int index, IntPtr value);
        [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr handle, IntPtr after, int x, int y, int width, int height, uint flags);
    }
}
