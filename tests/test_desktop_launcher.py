"""Exercise the compiled Windows launcher using an isolated tiny payload."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


HARNESS = r'''
internal static class LauncherHarness {
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet=System.Runtime.InteropServices.CharSet.Unicode, SetLastError=true)]
    static extern Microsoft.Win32.SafeHandles.SafeFileHandle CreateFile(string name, uint access, uint share,
        IntPtr security, uint mode, uint flags, IntPtr template);
    static BindingFlags Flags = BindingFlags.NonPublic | BindingFlags.Static;
    static object Invoke(string name, params object[] args) { return typeof(Program).GetMethod(name, Flags).Invoke(null, args); }
    static string Field(string name) { return (string)typeof(Program).GetField(name, Flags).GetValue(null); }
    static int Main(string[] args) {
        Microsoft.Win32.SafeHandles.SafeFileHandle held = null;
        bool blocked = false;
        try {
            string[] roots = new string[args.Length - 1];
            Array.Copy(args, 1, roots, 0, roots.Length);
            typeof(Program).GetField("CacheCandidates", Flags).SetValue(null, roots);
            Invoke("SetCacheRoot", roots[0]);
            if (args[0] == "log") {
                Console.WriteLine("log|" + Invoke("WriteFailureLog", new UnauthorizedAccessException("TEST denied")));
                return 0;
            }
            if (args[0] == "select") {
                Console.WriteLine("selected|" + Invoke("SelectPreparedRuntime"));
            } else {
                using (CancellationTokenSource cancel = new CancellationTokenSource()) {
                    Action<int> progress = delegate(int value) {
                        if (args[0] == "cancel") cancel.Cancel();
                        if (args[0] != "locked" || held != null) return;
                        string root = Path.GetFullPath(Field("CacheRoot"));
                        foreach (string stage in Directory.GetDirectories(root)) {
                            if (!File.Exists(Path.Combine(stage, "payload.zip"))) continue;
                            held = CreateFile(stage, 0, 3, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero);
                            if (held.IsInvalid) throw new IOException("Could not acquire directory handle");
                            string rename = stage + "-probe";
                            string prefix = root + Path.DirectorySeparatorChar;
                            if (!Path.GetFullPath(stage).StartsWith(prefix) || !Path.GetFullPath(rename).StartsWith(prefix))
                                throw new IOException("Unsafe test move");
                            try { Directory.Move(stage, rename); }
                            catch (UnauthorizedAccessException) { blocked = true; }
                            catch (IOException) { blocked = true; }
                            if (!blocked) throw new IOException("Directory lock did not block rename");
                            break;
                        }
                    };
                    Invoke("Prepare", progress, cancel.Token);
                }
            }
            Console.WriteLine("ready|" + Invoke("Ready"));
            Console.WriteLine("runtime|" + Field("Runtime"));
            Console.WriteLine("selection|" + Field("SelectionPath"));
            Console.WriteLine("blocked|" + blocked);
            return 0;
        } catch (TargetInvocationException error) {
            Console.WriteLine("error|" + error.InnerException.GetType().Name + "|" + error.InnerException.Message);
            return 2;
        } finally { if (held != null) held.Dispose(); }
    }
}
'''


@unittest.skipUnless(os.name == "nt", "Requires Windows .NET Framework")
class DesktopLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="pokemmo-launcher-test-")
        cls.build = Path(cls.folder.name).resolve()
        core = b"isolated launcher test core"
        archive = cls.build / "payload.zip"
        with zipfile.ZipFile(archive, "w") as payload:
            payload.writestr("PokeMMO-Breeder-Helper.exe", core)
            payload.writestr("_internal/example.txt", "test data")
        cls.digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        cls.prefix = "V0.2.36-" + cls.digest[:16]
        source = (Path(__file__).resolve().parents[1] / "desktop-launcher/Program.cs").read_text(encoding="utf-8-sig")
        source = source.replace("__VERSION__", "0.2.36").replace("__PAYLOAD_HASH__", cls.digest)
        source = source.replace("__CORE_HASH__", hashlib.sha256(core).hexdigest())
        generated = cls.build / "Launcher.cs"
        generated.write_text(source + HARNESS, encoding="utf-8-sig")
        cls.exe = cls.build / "LauncherTests.exe"
        compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
        result = subprocess.run([str(compiler), "/nologo", "/target:exe", "/main:LauncherHarness", "/platform:x64",
                                 "/utf8output", "/out:" + str(cls.exe), "/resource:" + str(archive) + ",RuntimePayload",
                                 "/reference:System.dll", "/reference:System.Core.dll", "/reference:System.Windows.Forms.dll",
                                 "/reference:System.Drawing.dll", "/reference:System.IO.Compression.dll",
                                 "/reference:System.IO.Compression.FileSystem.dll", str(generated)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_launcher(self, mode, *roots, expected=0):
        result = subprocess.run([str(self.exe), mode, *(str(p) for p in roots)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return dict(line.split("|", 1) for line in result.stdout.splitlines() if "|" in line)

    def test_first_prepare_and_cached_restart_with_unicode_path(self):
        with tempfile.TemporaryDirectory(dir=self.build, prefix="用户-") as directory:
            root = Path(directory) / "runtime"
            first = self.run_launcher("prepare", root)
            self.assertEqual(first["ready"], "True")
            selected = self.run_launcher("select", root)
            self.assertEqual(selected["selected"], "True")
            self.assertEqual(first["runtime"], selected["runtime"])
            self.assertEqual(self.run_launcher("prepare", root)["runtime"], first["runtime"])
            self.assertEqual(len(list(root.glob(self.prefix + "-*"))), 1)

    def test_real_windows_directory_rename_denial_does_not_prevent_prepare(self):
        with tempfile.TemporaryDirectory(dir=self.build) as directory:
            result = self.run_launcher("locked", Path(directory) / "runtime")
            self.assertEqual(result["blocked"], "True")
            self.assertEqual(result["ready"], "True")

    def test_broken_runtime_is_preserved_and_inventory_is_untouched(self):
        with tempfile.TemporaryDirectory(dir=self.build) as directory:
            folder = Path(directory)
            inventory = folder / "inventory.db"
            inventory.write_bytes(b"not a real inventory")
            root = folder / "runtime"
            first = self.run_launcher("prepare", root)
            bad_core = Path(first["runtime"]) / "PokeMMO-Breeder-Helper.exe"
            bad_core.write_bytes(b"broken")
            replacement = self.run_launcher("prepare", root)
            self.assertEqual(replacement["ready"], "True")
            self.assertNotEqual(first["runtime"], replacement["runtime"])
            self.assertEqual(bad_core.read_bytes(), b"broken")
            self.assertEqual(inventory.read_bytes(), b"not a real inventory")

    def test_invalid_pointer_does_not_select_an_outside_directory(self):
        with tempfile.TemporaryDirectory(dir=self.build) as directory:
            root = Path(directory) / "runtime"
            result = self.run_launcher("prepare", root)
            Path(result["selection"]).write_text("../outside", encoding="utf-8")
            selected = self.run_launcher("select", root)
            self.assertEqual(selected["selected"], "False")
            self.assertTrue(Path(selected["runtime"]).is_relative_to(root))

    def test_unwritable_primary_path_uses_separate_runtime_cache(self):
        with tempfile.TemporaryDirectory(dir=self.build) as directory:
            blocked = Path(directory) / "blocked"
            blocked.write_bytes(b"blocked directory path")
            fallback = Path(directory) / "fallback"
            result = self.run_launcher("prepare", blocked, fallback)
            self.assertEqual(result["ready"], "True")
            self.assertTrue(Path(result["runtime"]).is_relative_to(fallback))
            self.assertEqual(blocked.read_bytes(), b"blocked directory path")

    def test_cancellation_cleans_only_its_incomplete_runtime(self):
        with tempfile.TemporaryDirectory(dir=self.build) as directory:
            root = Path(directory) / "runtime"
            result = self.run_launcher("cancel", root, expected=2)
            self.assertIn("OperationCanceledException", result["error"])
            self.assertFalse(list(root.iterdir()))

    def test_permission_diagnostic_is_saved_in_a_writable_location(self):
        with tempfile.TemporaryDirectory(dir=self.build) as directory:
            blocked = Path(directory) / "blocked"
            blocked.write_bytes(b"blocked")
            fallback = Path(directory) / "fallback"
            result = self.run_launcher("log", blocked, fallback)
            log = Path(result["log"])
            self.assertTrue(log.is_relative_to(fallback))
            self.assertIn("UnauthorizedAccessException", log.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
