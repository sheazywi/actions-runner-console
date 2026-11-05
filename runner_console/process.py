"""Read-only runner process checks; no service-control or WMI privileges."""
import ctypes
import os
from pathlib import Path
import subprocess


def runner_active(runner, service=""):
    if os.name != "nt":
        if service:
            result = subprocess.run(["systemctl", "is-active", service],
                                    capture_output=True, text=True, timeout=3)
            return result.stdout.strip() == "active"
        for entry in Path("/proc").glob("[0-9]*/exe"):
            try:
                if entry.resolve() == (runner / "bin/Runner.Listener").resolve():
                    return True
            except (OSError, RuntimeError):
                continue
        return False

    from ctypes import wintypes as w
    class Entry(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                    ("heap", ctypes.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                    ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
                    ("name", w.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    expected = os.path.normcase(str(runner / "bin" / "Runner.Listener.exe"))
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        present = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while present:
            if entry.name.lower() == "runner.listener.exe":
                process = kernel.OpenProcess(0x1000, False, entry.pid)
                if process:
                    try:
                        length = w.DWORD(32768)
                        path = ctypes.create_unicode_buffer(length.value)
                        if kernel.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
                            if os.path.normcase(path.value) == expected:
                                return True
                    finally:
                        kernel.CloseHandle(process)
            present = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    finally:
        kernel.CloseHandle(snapshot)
