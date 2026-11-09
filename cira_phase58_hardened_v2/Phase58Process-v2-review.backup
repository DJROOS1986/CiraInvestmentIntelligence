using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

// REVIEW CANDIDATE ONLY. Not validated on Windows; do not execute until approved.
public sealed class Phase58Result {
    public string Status { get; set; }
    public int ExitCode { get; set; }
    public int DurationMs { get; set; }
    public string Detail { get; set; }
    public string Output { get; set; }
}

public static class Phase58Process {
    private const uint CREATE_SUSPENDED = 0x00000004;
    private const uint CREATE_NO_WINDOW = 0x08000000;
    private const uint STARTF_USESTDHANDLES = 0x00000100;
    private const uint HANDLE_FLAG_INHERIT = 0x00000001;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const uint WAIT_OBJECT_0 = 0;
    private const uint WAIT_TIMEOUT = 258;
    private const uint INFINITE = 0xFFFFFFFF;
    private const int JobObjectExtendedLimitInformation = 9;
    private const int MaxStdoutChars = 1048576;
    private const int MaxStderrChars = 8192;

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        [MarshalAs(UnmanagedType.Bool)] public bool bInheritHandle;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO {
        public uint cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public uint dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars;
        public uint dwFillAttribute;
        public uint dwFlags;
        public ushort wShowWindow;
        public ushort cbReserved2;
        public IntPtr lpReserved2;
        public IntPtr hStdInput, hStdOutput, hStdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION {
        public IntPtr hProcess, hThread;
        public uint dwProcessId, dwThreadId;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [DllImport("kernel32.dll", SetLastError = true)] private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint size);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateJobObject(IntPtr job, uint exitCode);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreatePipe(out IntPtr read, out IntPtr write, ref SECURITY_ATTRIBUTES attributes, uint size);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetHandleInformation(IntPtr handle, uint mask, uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcess(string application, StringBuilder commandLine, IntPtr processAttributes,
        IntPtr threadAttributes, [MarshalAs(UnmanagedType.Bool)] bool inheritHandles, uint flags,
        IntPtr environment, string currentDirectory, ref STARTUPINFO startup, out PROCESS_INFORMATION process);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint GetLastError();
    [DllImport("kernel32.dll", SetLastError = true)] private static extern IntPtr GetStdHandle(int handle);

    private static void Check(bool success, string operation) {
        if (!success) throw new Win32Exception(Marshal.GetLastWin32Error(), operation);
    }
    private static void Close(ref IntPtr handle) {
        if (handle != IntPtr.Zero && handle != new IntPtr(-1)) CloseHandle(handle);
        handle = IntPtr.Zero;
    }
    private static string Quote(string value) {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private sealed class Capture {
        public readonly StringBuilder Buffer = new StringBuilder();
        public bool Overflow;
        private readonly int max;
        public Capture(int maximum) { max = maximum; }
        public void Read(StreamReader reader) {
            char[] block = new char[4096];
            int count;
            while ((count = reader.Read(block, 0, block.Length)) > 0) {
                if (Buffer.Length + count > max) { Overflow = true; continue; }
                if (!Overflow) Buffer.Append(block, 0, count);
            }
        }
    }

    public static Phase58Result Run(string executable, string arguments, int timeoutMs) {
        var watch = Stopwatch.StartNew();
        var result = new Phase58Result { Status = "FAIL", ExitCode = 1, Detail = "process startup failure", Output = "" };
        IntPtr job = IntPtr.Zero, outRead = IntPtr.Zero, outWrite = IntPtr.Zero;
        IntPtr errRead = IntPtr.Zero, errWrite = IntPtr.Zero;
        PROCESS_INFORMATION pi = new PROCESS_INFORMATION();
        bool started = false;
        var stdout = new Capture(MaxStdoutChars);
        var stderr = new Capture(MaxStderrChars);
        Thread outThread = null, errThread = null;
        try {
            if (string.IsNullOrWhiteSpace(executable) || timeoutMs <= 0) throw new ArgumentException("Invalid executable or timeout");
            job = CreateJobObject(IntPtr.Zero, null);
            Check(job != IntPtr.Zero, "CreateJobObject");
            var limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            Check(SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref limits,
                (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))), "SetInformationJobObject");
            var sa = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES)), bInheritHandle = true };
            Check(CreatePipe(out outRead, out outWrite, ref sa, 0), "CreatePipe(stdout)");
            Check(CreatePipe(out errRead, out errWrite, ref sa, 0), "CreatePipe(stderr)");
            Check(SetHandleInformation(outRead, HANDLE_FLAG_INHERIT, 0), "SetHandleInformation(stdout)");
            Check(SetHandleInformation(errRead, HANDLE_FLAG_INHERIT, 0), "SetHandleInformation(stderr)");
            var si = new STARTUPINFO();
            si.cb = (uint)Marshal.SizeOf(typeof(STARTUPINFO));
            si.dwFlags = STARTF_USESTDHANDLES;
            si.hStdInput = GetStdHandle(-10);
            si.hStdOutput = outWrite;
            si.hStdError = errWrite;
            var command = new StringBuilder(Quote(executable) + " " + (arguments ?? ""));
            Check(CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                CREATE_SUSPENDED | CREATE_NO_WINDOW, IntPtr.Zero, null, ref si, out pi), "CreateProcess");
            started = true;
            Check(AssignProcessToJobObject(job, pi.hProcess), "AssignProcessToJobObject");
            // Parent write ends must close before reading so readers observe EOF.
            Close(ref outWrite);
            Close(ref errWrite);
            var outStream = new FileStream(new Microsoft.Win32.SafeHandles.SafeFileHandle(outRead, true), FileAccess.Read, 4096, false);
            outRead = IntPtr.Zero;
            var errStream = new FileStream(new Microsoft.Win32.SafeHandles.SafeFileHandle(errRead, true), FileAccess.Read, 4096, false);
            errRead = IntPtr.Zero;
            outThread = new Thread(() => { using (outStream) using (var reader = new StreamReader(outStream, Encoding.UTF8, true)) stdout.Read(reader); });
            errThread = new Thread(() => { using (errStream) using (var reader = new StreamReader(errStream, Encoding.UTF8, true)) stderr.Read(reader); });
            outThread.IsBackground = true;
            errThread.IsBackground = true;
            outThread.Start();
            errThread.Start();
            if (ResumeThread(pi.hThread) == 0xFFFFFFFF) throw new Win32Exception(Marshal.GetLastWin32Error(), "ResumeThread");
            uint wait = WaitForSingleObject(pi.hProcess, (uint)timeoutMs);
            if (wait == WAIT_TIMEOUT) {
                Check(TerminateJobObject(job, 124), "TerminateJobObject");
                WaitForSingleObject(pi.hProcess, 5000);
                result.Status = "TIMEOUT";
                result.ExitCode = 124;
                result.Detail = "monitoring exceeded configured timeout";
            } else if (wait == WAIT_OBJECT_0) {
                uint code;
                Check(GetExitCodeProcess(pi.hProcess, out code), "GetExitCodeProcess");
                result.ExitCode = unchecked((int)code);
                result.Status = code == 0 ? "PASS" : "FAIL";
                result.Detail = code == 0 ? "collection process completed" : "collection process returned nonzero exit code";
            } else {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "WaitForSingleObject");
            }
        } catch (Exception ex) {
            result.Status = "FAIL";
            result.ExitCode = 1;
            result.Detail = ex.GetType().Name + ": " + ex.Message;
        } finally {
            // Closing the job terminates any surviving descendants before stream drain.
            Close(ref job);
            if (outThread != null) outThread.Join(5000);
            if (errThread != null) errThread.Join(5000);
            Close(ref outRead); Close(ref outWrite); Close(ref errRead); Close(ref errWrite);
            Close(ref pi.hThread); Close(ref pi.hProcess);
            watch.Stop();
            result.DurationMs = (int)Math.Min(int.MaxValue, watch.ElapsedMilliseconds);
            result.Output = stdout.Overflow ? "" : stdout.Buffer.ToString();
            if (stdout.Overflow) {
                result.Status = "FAIL";
                result.ExitCode = 1;
                result.Detail = "Collection stdout exceeded 1 MB character limit.";
            }
            if (stderr.Buffer.Length > 0) result.Detail += "; stderr: " + stderr.Buffer.ToString();
            if (stderr.Overflow) result.Detail += "; stderr truncated";
        }
        return result;
    }
}
