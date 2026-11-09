using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public sealed class Phase58Result {
    public string Status { get; set; }
    public int ExitCode { get; set; }
    public int DurationMs { get; set; }
    public string Detail { get; set; }
    public string Output { get; set; }
}
public static class Phase58Process {
    [StructLayout(LayoutKind.Sequential)] struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] struct IO_COUNTERS {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }
    [StructLayout(LayoutKind.Sequential)] struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int infoClass, ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint exitCode);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
    const uint JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;
    const int JobObjectExtendedLimitInformation = 9;

    public static Phase58Result Run(string executable, string arguments, int timeoutMs) {
        var watch = Stopwatch.StartNew();
        var result = new Phase58Result { Status="FAIL", ExitCode=1, Detail="process startup failure", Output="" };
        IntPtr job = IntPtr.Zero;
        Process child = null;
        var captured = new StringBuilder();
        object sync = new object();
        try {
            job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) throw new InvalidOperationException("Job Object creation failed");
            var limits = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ref limits, (uint)Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))))
                throw new InvalidOperationException("Job Object limit setup failed");
            var info = new ProcessStartInfo(executable, arguments);
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            child = new Process();
            child.StartInfo = info;
            DataReceivedEventHandler handler = (sender, e) => {
                if (e.Data == null) return;
                lock (sync) {
                    if (captured.Length < 8192) {
                        int remaining = 8192 - captured.Length;
                        captured.AppendLine(e.Data.Length > remaining ? e.Data.Substring(0, remaining) : e.Data);
                    }
                }
            };
            child.OutputDataReceived += handler;
            child.ErrorDataReceived += handler;
            if (!child.Start()) throw new InvalidOperationException("Child process failed to start");
            // A small start-to-assignment window exists; see README for this limitation.
            if (!AssignProcessToJobObject(job, child.Handle)) {
                try { child.Kill(); } catch { }
                throw new InvalidOperationException("Job Object assignment failed; fail closed");
            }
            child.BeginOutputReadLine();
            child.BeginErrorReadLine();
            if (!child.WaitForExit(timeoutMs)) {
                TerminateJobObject(job, 124);
                child.WaitForExit(5000);
                result.Status = "TIMEOUT";
                result.ExitCode = 124;
                result.Detail = "monitoring exceeded configured timeout";
            } else {
                child.WaitForExit(); // flush async event callbacks
                result.ExitCode = child.ExitCode;
                result.Status = child.ExitCode == 0 ? "PASS" : "FAIL";
                result.Detail = child.ExitCode == 0 ? "collection process completed" : "collection process returned nonzero exit code";
            }
        } catch (Exception ex) {
            result.Status = "FAIL";
            result.ExitCode = 1;
            result.Detail = ex.GetType().Name + ": " + ex.Message;
        } finally {
            if (job != IntPtr.Zero) CloseHandle(job); // KILL_ON_JOB_CLOSE kills surviving descendants
            if (child != null) child.Dispose();
            watch.Stop();
            result.DurationMs = (int)Math.Min(int.MaxValue, watch.ElapsedMilliseconds);
            lock (sync) { result.Output = captured.ToString(); }
        }
        return result;
    }
}
