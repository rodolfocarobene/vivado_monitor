"""Decoding of Vivado text files: UTF-8 with replacement, CRLF (Vivado on Windows) folded to LF."""


def decode(data):
    return data.decode("utf-8", "replace").replace("\r\n", "\n")
