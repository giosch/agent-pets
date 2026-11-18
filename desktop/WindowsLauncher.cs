using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

// The stable executable is the registered hook command. Preserve the original
// command line and inherited stdin/stdout handles, including for GUI callers.
class WindowsLauncher {
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
    struct Startup {
        public int size;
        public string reserved, desktop, title;
        public int x,y,w,h,cx,cy,fill,flags;
        public short show, reserved2;
        public IntPtr bytes,input,output,error;
    }
    [StructLayout(LayoutKind.Sequential)]
    struct ProcessInfo { public IntPtr process, thread; public int pid, tid; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool CreateProcess(string app, StringBuilder args, IntPtr p, IntPtr t, bool inherit,
        uint flags, IntPtr env, string cwd, ref Startup startup, out ProcessInfo proc);
    [DllImport("kernel32.dll")] static extern IntPtr GetStdHandle(int n);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr h, uint time);
    [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr h, out uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);

    [STAThread] static int Main(string[] args) {
        try {
            string self=System.Reflection.Assembly.GetExecutingAssembly().Location;
            string root=Path.GetDirectoryName(self);
            string target=File.ReadAllText(Path.Combine(root,"current")).Trim();
            if (!Regex.IsMatch(target, @"\A[A-Za-z0-9._-]+\z") || target.StartsWith(".")) throw new IOException("Invalid installation");
            string program=Path.Combine(root,"releases",target,"habitat-runtime.exe");
            Environment.SetEnvironmentVariable("CLAWD_TANK_LAUNCHER",Path.Combine(root,"clawd-tank.exe"));
            Startup s=new Startup(); s.size=Marshal.SizeOf(s); s.flags=0x101;
            s.input=GetStdHandle(-10); s.output=GetStdHandle(-11); s.error=GetStdHandle(-12);
            ProcessInfo pi;
            if (!CreateProcess(program,new StringBuilder(Environment.CommandLine),IntPtr.Zero,IntPtr.Zero,true,
                0x08000000,IntPtr.Zero,null,ref s,out pi)) throw new System.ComponentModel.Win32Exception();
            CloseHandle(pi.thread); WaitForSingleObject(pi.process,0xffffffff); uint code;
            GetExitCodeProcess(pi.process,out code); CloseHandle(pi.process); return (int)code;
        } catch(Exception e) {
            if (args.Length==0) MessageBox.Show(e.Message,"Clawd Tank");
            return 1;
        }
    }
}
