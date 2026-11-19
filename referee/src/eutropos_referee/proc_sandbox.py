"""OS process-tree containment for isolated athlete worker subprocesses."""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
from typing import Any

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class ProcessTreeGuard:
    """Binds a child Popen handle to a Windows Job Object or POSIX process session."""

    def __init__(self, proc: subprocess.Popen[Any]) -> None:
        self.proc = proc
        self.attached = False
        self._job_handle: int | None = None
        if sys.platform == "win32":
            self._attach_windows_job(proc)
        else:
            self.attached = True

    def _attach_windows_job(self, proc: subprocess.Popen[Any]) -> None:
        try:
            k32 = ctypes.windll.kernel32
            job = k32.CreateJobObjectW(None, None)
            if not job:
                return

            class _IO_COUNTERS(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
                )]

            class _BASIC_LIMIT(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32),
                ]

            class _EXTENDED_LIMIT(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", _BASIC_LIMIT),
                    ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t),
                ]

            info = _EXTENDED_LIMIT()
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            ok_set = k32.SetInformationJobObject(
                job,
                _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ok_set:
                k32.CloseHandle(job)
                return
            ok_assign = k32.AssignProcessToJobObject(job, int(proc._handle))
            if not ok_assign:
                # Some Windows CI / container sandboxes assign a non-breakaway parent job
                k32.CloseHandle(job)
                return
            self._job_handle = int(job)
            self.attached = True
        except Exception:
            self.attached = False

    def terminate(self) -> None:
        if sys.platform == "win32":
            k32 = ctypes.windll.kernel32
            if self._job_handle is not None:
                try:
                    k32.TerminateJobObject(self._job_handle, 1)
                except Exception:
                    pass
                try:
                    k32.CloseHandle(self._job_handle)
                except Exception:
                    pass
                self._job_handle = None
            try:
                if self.proc.poll() is None:
                    self.proc.kill()
            except Exception:
                pass
            return

        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:
            try:
                if self.proc.poll() is None:
                    self.proc.kill()
            except Exception:
                pass


def popen_session_kwargs() -> dict[str, Any]:
    """Return platform-appropriate subprocess isolation flags for Popen."""
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}
