using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Windows.Forms;

class WindowsSetup {
    [STAThread] static int Main(string[] args) {
        bool verify=args.Contains("/verify");
        bool quiet=args.Contains("/quiet") || verify;
        if (!quiet && MessageBox.Show("Install or update Agent Pets for this Windows account?", "Agent Pets Setup",
            MessageBoxButtons.OKCancel,MessageBoxIcon.Question)!=DialogResult.OK) return 0;
        string stage=Path.Combine(Path.GetTempPath(),"agent-pets-setup-"+Guid.NewGuid().ToString("N"));
        try {
            Directory.CreateDirectory(stage);
            using (Stream data=Assembly.GetExecutingAssembly().GetManifestResourceStream("habitat.zip"))
            using (ZipArchive zip=new ZipArchive(data)) zip.ExtractToDirectory(stage);
            var start=new ProcessStartInfo(Path.Combine(stage,"habitat-runtime.exe"),
                verify ? "self-test" : "desktop-install" + (args.Contains("/no-launch") ? " --no-open" : ""));
            start.WorkingDirectory=stage; start.UseShellExecute=false; start.CreateNoWindow=true;
            start.RedirectStandardError=true;
            using (var child=Process.Start(start)) {
                string detail=child.StandardError.ReadToEnd();
                child.WaitForExit();
                if(child.ExitCode!=0) throw new IOException("Installation failed ("+child.ExitCode+"). "+detail);
            }
            return 0;
        } catch(Exception e) {
            if (!quiet) MessageBox.Show(e.Message,"Agent Pets Setup",MessageBoxButtons.OK,MessageBoxIcon.Error);
            Console.Error.WriteLine(e.Message);
            return 1;
        } finally { try { Directory.Delete(stage,true); } catch(IOException) {} }
    }
}
