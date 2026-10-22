"""Incremental, read-only log reader: yields only appended complete lines."""
import os
import sys

INDEX_STEP = 1000  # remember the byte offset of every 1000th line for range reads


def file_identity(st):
    """Which file a path points at: the inode, else the creation time (Windows filesystems with st_ino 0).
    A scalar so it survives JSON; 0 elsewhere, where only a shrinking size reveals a replacement."""
    if st.st_ino:
        return st.st_ino
    born = getattr(st, "st_birthtime", None)
    if born is not None:
        return "born:%s" % born
    return "born:%d" % st.st_ctime_ns if sys.platform == "win32" else 0     # ctime is creation time on Windows only


class LogTail:
    def __init__(self, path):
        self.path = str(path)
        self._reset_state()
        self.last_growth = None   # wall time the file last grew (or its mtime on first sight)

    def _reset_state(self):
        self.inode = None
        self.offset = 0            # bytes consumed from the file (incl. partial buffer)
        self.line_count = 0        # complete lines emitted
        self._partial = b""
        self._line_pos = 0         # byte offset where the next complete line starts
        self.line_offsets = [0]

    def poll(self):
        """Return (new_lines, was_reset). Missing files yield ([], False)."""
        try:
            st = os.stat(self.path)
        except OSError:
            return [], False
        reset = False
        identity = file_identity(st)
        if self.inode is not None and (identity != self.inode or st.st_size < self.offset):
            self._reset_state()
            reset = True
        first_sight = self.inode is None
        self.inode = identity
        if first_sight or reset:
            self.last_growth = st.st_mtime
        if st.st_size == self.offset:
            return [], reset
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read(st.st_size - self.offset)
        except OSError:
            return [], reset
        if not chunk:
            return [], reset
        self.offset += len(chunk)
        self.last_growth = st.st_mtime
        parts = (self._partial + chunk).split(b"\n")
        self._partial = parts.pop()
        lines = []
        pos = self._line_pos
        count = self.line_count
        offsets = self.line_offsets
        for raw in parts:
            pos += len(raw) + 1
            count += 1
            if count % INDEX_STEP == 0:
                offsets.append(pos)
            lines.append(raw.decode("utf-8", "replace").rstrip("\r"))
        self._line_pos = pos
        self.line_count = count
        return lines, reset

    def read_range(self, start_line, end_line):
        """Raw lines start_line..end_line (1-based, inclusive), reading only that region."""
        start_line = max(1, start_line)
        end_line = min(end_line, self.line_count)
        if end_line < start_line:
            return []
        index = (start_line - 1) // INDEX_STEP
        out = []
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.line_offsets[index])
                lineno = index * INDEX_STEP
                for raw in fh:
                    lineno += 1
                    if lineno < start_line:
                        continue
                    if lineno > end_line:
                        break
                    out.append(raw.decode("utf-8", "replace").rstrip("\r\n"))
        except OSError:
            return []
        return out
