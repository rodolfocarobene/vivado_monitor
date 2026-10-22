"""ctypes bindings for the Win32/NT calls vmon needs (read-only). Importing this is safe on any OS:
the DLLs are only loaded when WinApi() is constructed. Structures use fixed-width fields so their
layout (x64) can be checked on Linux too.

Layout reference (x64):
  PROCESSENTRY32W  568 bytes: dwSize, cntUsage, pid, [pad4], heapID(8), moduleID, threads, ppid, priClass, flags, exe[260 WCHAR]
  PROCESS_BASIC_INFORMATION 48 bytes: ExitStatus, [pad4], PebBaseAddress@8, Affinity, BasePriority, pid@32, ppid@40
  PEB.ProcessParameters @0x20; RTL_USER_PROCESS_PARAMETERS.CurrentDirectory.DosPath @0x38, .CommandLine @0x70
  UNICODE_STRING 16 bytes: Length(u16, bytes), MaximumLength(u16), [pad4], Buffer(u64)
"""
import ctypes
import struct

TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
STILL_ACTIVE = 259
ERROR_ACCESS_DENIED = 5
MAX_PATH = 260

PEB_PARAMS_OFFSET = 0x20
PARAMS_CWD_OFFSET = 0x38
PARAMS_CMDLINE_OFFSET = 0x70
PARAMS_READ_SIZE = 0x80


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_int32),
                ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_uint16 * MAX_PATH)]


class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("ExitStatus", ctypes.c_int32), ("PebBaseAddress", ctypes.c_void_p),
                ("AffinityMask", ctypes.c_size_t), ("BasePriority", ctypes.c_int32),
                ("UniqueProcessId", ctypes.c_size_t), ("InheritedFromUniqueProcessId", ctypes.c_size_t)]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64)]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_uint32), ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


# ---------------------------------------------------------------- pure helpers (testable anywhere)
def filetime_value(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def wide_to_str(units):
    """UTF-16 code units (c_uint16 array or bytes) up to the first NUL."""
    raw = bytes(units)
    return raw.decode("utf-16-le", "replace").split("\0", 1)[0]


def unicode_string_at(raw, offset):
    """(byte length, buffer address) of the 64-bit UNICODE_STRING at offset."""
    length, _max, address = struct.unpack_from("<HH4xQ", raw, offset)
    return length, address


def read_process_params(read, peb_address):
    """(command_line, cwd) from a remote 64-bit PEB; read(address, size) -> bytes | None.
    Either value is None when it cannot be read."""
    ptr = read(peb_address + PEB_PARAMS_OFFSET, 8)
    params = struct.unpack("<Q", ptr)[0] if ptr and len(ptr) == 8 else 0
    raw = read(params, PARAMS_READ_SIZE) if params else None
    if not raw or len(raw) < PARAMS_READ_SIZE:
        return None, None

    def text(offset):
        length, address = unicode_string_at(raw, offset)
        if not length or not address:
            return ""
        data = read(address, length)
        return data.decode("utf-16-le", "replace") if data else None

    return text(PARAMS_CMDLINE_OFFSET), strip_trailing_sep(text(PARAMS_CWD_OFFSET))


def strip_trailing_sep(path):
    """DosPath ends with a backslash ('C:\\x\\'); keep it only for a drive root."""
    if path and len(path) > 3 and path[-1] in "\\/":
        return path[:-1]
    return path


def split_command_line(text):
    """Split like CommandLineToArgvW (post-2008 rules): argv[0] only honours quotes; later
    arguments treat 2n backslashes+quote as n backslashes and a quote delimiter, 2n+1 as a literal
    quote, and a doubled quote inside quotes as a literal quote."""
    args, i, n = [], 0, len(text)
    if text.startswith('"'):
        end = text.find('"', 1)
        end = n if end < 0 else end
        args.append(text[1:end])
        i = end + 1
    else:
        while i < n and text[i] not in " \t":
            i += 1
        args.append(text[:i])
    while True:
        while i < n and text[i] in " \t":
            i += 1
        if i >= n:
            return args
        buf, in_quote = [], False
        while i < n and (in_quote or text[i] not in " \t"):
            slashes = 0
            while i < n and text[i] == "\\":
                slashes += 1
                i += 1
            if i < n and text[i] == '"':
                buf.append("\\" * (slashes // 2))
                if slashes % 2:
                    buf.append('"')
                elif in_quote and i + 1 < n and text[i + 1] == '"':
                    buf.append('"')
                    i += 1
                else:
                    in_quote = not in_quote
                i += 1
            else:
                buf.append("\\" * slashes)
                if i < n and (in_quote or text[i] not in " \t"):
                    buf.append(text[i])
                    i += 1
        args.append("".join(buf))


# ---------------------------------------------------------------- real calls (Windows only)
class WinApi:
    """Thin wrapper: every method returns None/empty on failure instead of raising and closes
    every handle it opens. Processes are only ever opened with query/read rights."""

    def __init__(self):
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._ntdll = ctypes.WinDLL("ntdll")
        self._shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self._k32 = k32
        vp, dw, bl = ctypes.c_void_p, wintypes.DWORD, wintypes.BOOL
        ref = ctypes.POINTER
        k32.CreateToolhelp32Snapshot.argtypes, k32.CreateToolhelp32Snapshot.restype = [dw, dw], vp
        for fn in (k32.Process32FirstW, k32.Process32NextW):
            fn.argtypes, fn.restype = [vp, ref(PROCESSENTRY32W)], bl
        k32.OpenProcess.argtypes, k32.OpenProcess.restype = [dw, bl, dw], vp
        k32.CloseHandle.argtypes, k32.CloseHandle.restype = [vp], bl
        k32.GetExitCodeProcess.argtypes, k32.GetExitCodeProcess.restype = [vp, ref(dw)], bl
        k32.GetProcessTimes.argtypes = [vp] + [ref(FILETIME)] * 4
        k32.GetProcessTimes.restype = bl
        k32.GetSystemTimes.argtypes, k32.GetSystemTimes.restype = [ref(FILETIME)] * 3, bl
        k32.GlobalMemoryStatusEx.argtypes, k32.GlobalMemoryStatusEx.restype = [ref(MEMORYSTATUSEX)], bl
        k32.K32GetProcessMemoryInfo.argtypes = [vp, ref(PROCESS_MEMORY_COUNTERS), dw]
        k32.K32GetProcessMemoryInfo.restype = bl
        k32.ReadProcessMemory.argtypes = [vp, vp, vp, ctypes.c_size_t, ref(ctypes.c_size_t)]
        k32.ReadProcessMemory.restype = bl
        k32.LocalFree.argtypes, k32.LocalFree.restype = [vp], vp
        self._ntdll.NtQueryInformationProcess.argtypes = [vp, ctypes.c_int, vp, wintypes.ULONG, ref(wintypes.ULONG)]
        self._ntdll.NtQueryInformationProcess.restype = ctypes.c_long
        self._shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ref(ctypes.c_int)]
        self._shell32.CommandLineToArgvW.restype = vp
        self._invalid = ctypes.c_void_p(-1).value
        self._wow64 = ctypes.sizeof(ctypes.c_void_p) != 8       # 32-bit Python cannot read 64-bit PEBs

    def _open(self, pid, access):
        return self._k32.OpenProcess(access, False, pid) or None

    def process_entries(self):
        """[(pid, ppid, image name)] from a Toolhelp snapshot."""
        snap = self._k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or snap == self._invalid:
            return []
        out, entry = [], PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            ok = self._k32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                out.append((entry.th32ProcessID, entry.th32ParentProcessID, wide_to_str(entry.szExeFile)))
                ok = self._k32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            self._k32.CloseHandle(snap)
        return out

    def alive(self, pid):
        handle = self._open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
        if handle is None:
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED       # exists but protected
        try:
            code = ctypes.c_uint32()
            return bool(self._k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE
        finally:
            self._k32.CloseHandle(handle)

    def command_line_and_cwd(self, pid):
        """(command line, cwd) read from the target's PEB, or (None, None) when not permitted."""
        if self._wow64:
            return None, None
        handle = self._open(pid, PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ)
        if handle is None:
            return None, None
        try:
            pbi = PROCESS_BASIC_INFORMATION()
            status = self._ntdll.NtQueryInformationProcess(handle, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
            if status != 0 or not pbi.PebBaseAddress:
                return None, None

            def read(address, size):
                buf, got = ctypes.create_string_buffer(size), ctypes.c_size_t()
                if not self._k32.ReadProcessMemory(handle, address, buf, size, ctypes.byref(got)):
                    return None
                return buf.raw[:got.value]

            return read_process_params(read, pbi.PebBaseAddress)
        finally:
            self._k32.CloseHandle(handle)

    def command_line_to_argv(self, text):
        count = ctypes.c_int()
        argv = self._shell32.CommandLineToArgvW(text, ctypes.byref(count))
        if not argv:
            return None
        try:
            return [ctypes.wstring_at(ctypes.cast(argv, ctypes.POINTER(ctypes.c_void_p))[i])
                    for i in range(count.value)]
        finally:
            self._k32.LocalFree(argv)

    def process_cpu_seconds(self, pid):
        handle = self._open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
        if handle is None:
            return None
        try:
            times = [FILETIME() for _ in range(4)]
            if not self._k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                return None
            return (filetime_value(times[2]) + filetime_value(times[3])) / 1e7       # kernel + user
        finally:
            self._k32.CloseHandle(handle)

    def working_set_bytes(self, pid):
        handle = self._open(pid, PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ)
        if handle is None:
            return None
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if not self._k32.K32GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            return counters.WorkingSetSize
        finally:
            self._k32.CloseHandle(handle)

    def system_times(self):
        """(idle, kernel, user) in 100 ns units; kernel includes idle."""
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        if not self._k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        return filetime_value(idle), filetime_value(kernel), filetime_value(user)

    def memory_status(self):
        """{"total_phys", "avail_phys", "total_pagefile", "avail_pagefile"} in bytes."""
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not self._k32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return {"total_phys": status.ullTotalPhys, "avail_phys": status.ullAvailPhys,
                "total_pagefile": status.ullTotalPageFile, "avail_pagefile": status.ullAvailPageFile}
