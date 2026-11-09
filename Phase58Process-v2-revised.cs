using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

// REVIEW ONLY: not compiled or executed on Windows. Requires explicit approval before testing.
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
    private const uint EXTENDED_STARTUPINFO_PRESENT = 0x00080000;
    private const uint STARTF_USESTDHANDLES = 0x00000100;
    private const uint HANDLE_FLAG_INHERIT = 1;
    private const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;
    private const uint PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002;
    private const uint WAIT_OBJECT_0 = 0;
    private const uint WAIT_TIMEOUT = 258;
    private const uint INVALID_RESUME = 0xFFFFFFFF;
    private const uint GENERIC_READ = 0x80000000;
    private const uint FILE_SHARE_READ = 1;
    private const uint FILE_SHARE_WRITE = 2;
    private const uint OPEN_EXISTING = 3;
    private const int JobObjectExtendedLimitInformation = 9;
    private const int MaxStdoutChars = 1048576;
    private const int MaxStderrChars = 8192;
    private const int DrainTimeoutMs = 5000;

    [StructLayout(LayoutKind.Sequential)]
    private struct SECURITY_ATTRIBUTES {
        public int nLength;
        public IntPtr lpSecurityDescriptor;
        [MarshalAs(UnmanagedType.Bool)] public bool bInheritHandle;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFO {
        public uint cb;
        public string lpReserved, lpDesktop, lpTitle;
        public uint dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars;
        public uint dwFillAttribute, dwFlags;
        public ushort wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct STARTUPINFOEX {
        public STARTUPINFO StartupInfo;
        public IntPtr lpAttributeList;
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
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFile(string name, uint access, uint share, ref SECURITY_ATTRIBUTES security,
        uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, uint flags, ref IntPtr size);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr attribute,
        IntPtr value, IntPtr size, IntPtr previous, IntPtr returnSize);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, EntryPoint = "CreateProcessW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CreateProcess(string application, StringBuilder commandLine, IntPtr processAttributes,
        IntPtr threadAttributes, [MarshalAs(UnmanagedType.Bool)] bool inheritHandles, uint flags,
        IntPtr environment, string currentDirectory, ref STARTUPINFOEX startup, out PROCESS_INFORMATION process);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool TerminateProcess(IntPtr process, uint exitCode);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);

    private static void Check(bool ok, string operation) {
        if (!ok) throw new Win32Exception(Marshal.GetLastWin32Error(), operation);
    }
    private static void Close(ref IntPtr handle) {
        if (handle != IntPtr.Zero && handle != new IntPtr(-1)) CloseHandle(handle);
        handle = IntPtr.Zero;
    }
    private static string QuoteExecutable(string value) {
        if (value.IndexOf('"') >= 0) throw new ArgumentException("Executable path contains a quote");
        return "\"" + value + "\"";
    }
    private sealed class Capture {
        public readonly StringBuilder Buffer = new StringBuilder();
        public readonly int Maximum;
        public bool Overflow;
        public Exception Error;
        public Capture(int maximum) { Maximum = maximum; }
        public void Read(StreamReader reader) {
            try {
                char[] block = new char[4096];
                int count;
                while ((count = reader.Read(block, 0, block.Length)) > 0) {
                    if (Overflow) continue;
                    if (count > Maximum - Buffer.Length) { Overflow = true; continue; }
                    Buffer.Append(block, 0, count);
                }
            } catch (Exception ex) { Error = ex; }
        }
    }
    private static void ReadPipe(Stream stream, Capture capture) {
        try {
            using (var reader = new StreamReader(stream, Encoding.UTF8, true)) capture.Read(reader);
        } catch (Exception ex) { capture.Error = ex; }
    }

    public static Phase58Result Run(string executable, string arguments, int timeoutMs) {
        var watch = Stopwatch.StartNew();
        var result = new Phase58Result { Status = "FAIL", ExitCode = 1, Detail = "process startup failure", Output = "" };
        IntPtr job = IntPtr.Zero, outRead = IntPtr.Zero, outWrite = IntPtr.Zero;
        IntPtr errRead = IntPtr.Zero, errWrite = IntPtr.Zero, nulInput = IntPtr.Zero;
        IntPtr attributeList = IntPtr.Zero, handleArray = IntPtr.Zero;
        bool attributeInitialized = false;
        PROCESS_INFORMATION pi = new PROCESS_INFORMATION();
        FileStream outStream = null, errStream = null;
        SafeFileHandle outSafe = null, errSafe = null;
        bool assignedToJob = false;
        Thread outThread = null, errThread = null;
        var stdout = new Capture(MaxStdoutChars);
        var stderr = new Capture(MaxStderrChars);
        try {
            if (string.IsNullOrWhiteSpace(executable) || timeoutMs <= 0) throw new ArgumentException("Invalid executable or timeout");
            if (!Path.IsPathRooted(executable)) throw new ArgumentException("Executable path must be absolute");
            job = CreateJobObject(IntPtr.Zero, null);
            Check(job != IntPtr.Zero && job != new IntPtr(-1), "CreateJobObject");
            var limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            Check(SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref limits,
                (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))), "SetInformationJobObject");

            var sa = new SECURITY_ATTRIBUTES { nLength = Marshal.SizeOf(typeof(SECURITY_ATTRIBUTES)), bInheritHandle = true };
            Check(CreatePipe(out outRead, out outWrite, ref sa, 0), "CreatePipe(stdout)");
            Check(CreatePipe(out errRead, out errWrite, ref sa, 0), "CreatePipe(stderr)");
            Check(SetHandleInformation(outRead, HANDLE_FLAG_INHERIT, 0), "SetHandleInformation(stdout)");
            Check(SetHandleInformation(errRead, HANDLE_FLAG_INHERIT, 0), "SetHandleInformation(stderr)");
            nulInput = CreateFile("NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, ref sa, OPEN_EXISTING, 0, IntPtr.Zero);
            Check(nulInput != IntPtr.Zero && nulInput != new IntPtr(-1), "CreateFile(NUL)");

            IntPtr size = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            if (size == IntPtr.Zero) throw new InvalidOperationException("Attribute list size was zero");
            attributeList = Marshal.AllocHGlobal(size);
            Check(InitializeProcThreadAttributeList(attributeList, 1, 0, ref size), "InitializeProcThreadAttributeList");
            attributeInitialized = true;
            handleArray = Marshal.AllocHGlobal(IntPtr.Size * 3);
            Marshal.WriteIntPtr(handleArray, 0, nulInput);
            Marshal.WriteIntPtr(handleArray, IntPtr.Size, outWrite);
            Marshal.WriteIntPtr(handleArray, IntPtr.Size * 2, errWrite);
            Check(UpdateProcThreadAttribute(attributeList, 0, new IntPtr(PROC_THREAD_ATTRIBUTE_HANDLE_LIST),
                handleArray, new IntPtr(IntPtr.Size * 3), IntPtr.Zero, IntPtr.Zero), "UpdateProcThreadAttribute");

            var si = new STARTUPINFOEX();
            si.StartupInfo.cb = (uint)Marshal.SizeOf(typeof(STARTUPINFOEX));
            si.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
            si.StartupInfo.hStdInput = nulInput;
            si.StartupInfo.hStdOutput = outWrite;
            si.StartupInfo.hStdError = errWrite;
            si.lpAttributeList = attributeList;
            var command = new StringBuilder(QuoteExecutable(executable) + " " + (arguments ?? ""), 32768);
            Check(CreateProcess(executable, command, IntPtr.Zero, IntPtr.Zero, true,
                CREATE_SUSPENDED | CREATE_NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT,
                IntPtr.Zero, null, ref si, out pi), "CreateProcess");
            Check(AssignProcessToJobObject(job, pi.hProcess), "AssignProcessToJobObject");
            assignedToJob = true;
            Close(ref outWrite); Close(ref errWrite); Close(ref nulInput);

            // Transfer each owned read handle to its stream immediately.
            outSafe = new SafeFileHandle(outRead, true); outRead = IntPtr.Zero;
            outStream = new FileStream(outSafe, FileAccess.Read, 4096, false);
            errSafe = new SafeFileHandle(errRead, true); errRead = IntPtr.Zero;
            errStream = new FileStream(errSafe, FileAccess.Read, 4096, false);
            FileStream capturedOut = outStream, capturedErr = errStream;
            outThread = new Thread(() => ReadPipe(capturedOut, stdout));
            errThread = new Thread(() => ReadPipe(capturedErr, stderr));
            outThread.IsBackground = true; errThread.IsBackground = true;
            outThread.Start(); errThread.Start();
            if (ResumeThread(pi.hThread) == INVALID_RESUME) throw new Win32Exception(Marshal.GetLastWin32Error(), "ResumeThread");
            uint wait = WaitForSingleObject(pi.hProcess, (uint)timeoutMs);
            if (wait == WAIT_TIMEOUT) {
                Check(TerminateJobObject(job, 124), "TerminateJobObject");
                result.Status = "TIMEOUT";
                result.ExitCode = 124;
                result.Detail = "monitoring exceeded configured timeout";
            }
            if (wait == WAIT_OBJECT_0) {
                uint code;
                Check(GetExitCodeProcess(pi.hProcess, out code), "GetExitCodeProcess");
                result.ExitCode = unchecked((int)code);
                result.Status = code == 0 ? "PASS" : "FAIL";
                result.Detail = code == 0 ? "collection process completed" : "collection process returned nonzero exit code";
            }
            if (wait != WAIT_OBJECT_0 && wait != WAIT_TIMEOUT)
                throw new Win32Exception(Marshal.GetLastWin32Error(), "WaitForSingleObject");
        } catch (Exception ex) {
            result.Status = "FAIL";
            result.ExitCode = 1;
            result.Detail = ex.GetType().Name + ": " + ex.Message;
        } finally {
            // A suspended child not yet assigned to the job must be terminated explicitly.
            if (!assignedToJob && pi.hProcess != IntPtr.Zero) TerminateProcess(pi.hProcess, 1);
            // Job closure kills any surviving process tree, allowing pipe EOF.
            Close(ref job);
            Close(ref outWrite); Close(ref errWrite); Close(ref nulInput);
            bool outDone = outThread == null || (outThread.ThreadState == ThreadState.Unstarted) || outThread.Join(DrainTimeoutMs);
            bool errDone = errThread == null || (errThread.ThreadState == ThreadState.Unstarted) || errThread.Join(DrainTimeoutMs);
            if (!outDone || !errDone) {
                result.Status = "FAIL";
                result.ExitCode = 1;
                result.Detail += "; output reader did not finish within drain timeout";
            }
            // Avoid disposing streams concurrently with a still-running reader.
            if (outDone && outStream != null) outStream.Dispose();
            if (errDone && errStream != null) errStream.Dispose();
            if (outDone && outSafe != null) outSafe.Dispose();
            if (errDone && errSafe != null) errSafe.Dispose();
            Close(ref outRead); Close(ref errRead);
            Close(ref pi.hThread); Close(ref pi.hProcess);
            if (attributeInitialized) DeleteProcThreadAttributeList(attributeList);
            if (attributeList != IntPtr.Zero) Marshal.FreeHGlobal(attributeList);
            if (handleArray != IntPtr.Zero) Marshal.FreeHGlobal(handleArray);
            watch.Stop();
            result.DurationMs = (int)Math.Min(int.MaxValue, watch.ElapsedMilliseconds);
            if (outDone && errDone) {
                if (stdout.Error != null || stderr.Error != null) {
                    result.Status = "FAIL"; result.ExitCode = 1;
                    result.Detail += "; pipe reader failed: " + (stdout.Error ?? stderr.Error).Message;
                }
                if (stdout.Overflow) {
                    result.Status = "FAIL"; result.ExitCode = 1;
                    result.Detail += "; stdout exceeded character limit";
                }
                if (stderr.Overflow) result.Detail += "; stderr truncated";
                if (stderr.Buffer.Length > 0) result.Detail += "; stderr: " + stderr.Buffer.ToString();
                if (!stdout.Overflow && stdout.Error == null) result.Output = stdout.Buffer.ToString();
            }
        }
        return result;
    }
}
