"""Thin ctypes wrapper around CascLib.dll (from D2RMM's tools) for
reading files out of the D2R game's CASC storage.

Verified working against this CascLib build: ANSI (char*) paths,
chunked CascReadFile (CascGetFileSize is unreliable here).
"""
import ctypes
import ctypes.wintypes as wt
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DLL = os.path.join(HERE, "CascLib.dll")
import config  # noqa: E402
GAME_ROOT = (config.GAME_ROOT or "").encode("mbcs", "replace")


class CASC_FIND_DATA(ctypes.Structure):
    _fields_ = [
        ("szFileName", ctypes.c_char * 1024),
        ("szPlainName", ctypes.c_char_p),
        ("CKey", ctypes.c_ubyte * 16),
        ("EKey", ctypes.c_ubyte * 16),
        ("TagBitMask", ctypes.c_ulonglong),
        ("FileSize", ctypes.c_ulonglong),
        ("bFileAvailable", ctypes.c_uint),
        ("NameType", ctypes.c_uint),
    ]


def available():
    return (os.path.isfile(DLL) and bool(GAME_ROOT)
            and os.path.isdir(GAME_ROOT.decode("mbcs")))


def _lib():
    lib = ctypes.WinDLL(DLL, use_last_error=True)
    lib.CascOpenStorage.restype = ctypes.c_bool
    lib.CascOpenFile.restype = ctypes.c_bool
    lib.CascReadFile.restype = ctypes.c_bool
    lib.CascFindFirstFile.restype = ctypes.c_void_p
    lib.CascFindNextFile.restype = ctypes.c_bool
    return lib


class Storage:
    def __init__(self, game_root=GAME_ROOT):
        self.lib = _lib()
        self.h = ctypes.c_void_p()
        if not self.lib.CascOpenStorage(ctypes.c_char_p(game_root), 0,
                                        ctypes.byref(self.h)):
            raise OSError("CascOpenStorage failed (err {})".format(
                ctypes.get_last_error()))

    def read(self, casc_name):
        """casc_name e.g. b'data:data/hd/global/video/logoloop.webm'"""
        f = ctypes.c_void_p()
        if not self.lib.CascOpenFile(self.h, ctypes.c_char_p(casc_name),
                                     0, 0, ctypes.byref(f)):
            return None
        chunks = []
        buf = ctypes.create_string_buffer(1 << 20)
        read = wt.DWORD()
        while (self.lib.CascReadFile(f, buf, len(buf), ctypes.byref(read))
               and read.value):
            chunks.append(buf.raw[:read.value])
        self.lib.CascCloseFile(f)
        return b"".join(chunks)

    def find(self, mask=b"*"):
        """Yield (name, size) for files matching mask."""
        fd = CASC_FIND_DATA()
        hf = ctypes.c_void_p(self.lib.CascFindFirstFile(
            self.h, ctypes.c_char_p(mask), ctypes.byref(fd), None))
        if not hf.value or hf.value == ctypes.c_void_p(-1).value:
            return
        try:
            while True:
                yield fd.szFileName.decode("utf-8", "replace"), fd.FileSize
                if not self.lib.CascFindNextFile(hf, ctypes.byref(fd)):
                    break
        finally:
            self.lib.CascFindClose(hf)

    def extract(self, casc_name, dest):
        data = self.read(casc_name)
        if data is None:
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        return True

    def close(self):
        if self.h:
            self.lib.CascCloseStorage(self.h)
            self.h = None
