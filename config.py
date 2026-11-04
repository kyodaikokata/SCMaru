"""Atomic JSON settings and optional Windows user-bound secret protection."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import uuid
from copy import deepcopy


def merge_settings(base, values):
    result=deepcopy(base)
    for key,value in values.items():
        result[key]=merge_settings(result.get(key,{}),value) if isinstance(value,dict) and isinstance(result.get(key,{}),dict) else deepcopy(value)
    return result


def load_defaults():
    path=Path(__file__).parent/'assets/defaults.json'
    if not path.is_file(): return {}
    value=json.loads(path.read_text(encoding='utf-8'))
    return value if isinstance(value,dict) else {}


class Settings:
    def __init__(self, path, initial=None):
        self.path = Path(path)
        self.data = merge_settings(load_defaults(),initial or {})
        self.error = None
        if self.path.is_file():
            try:
                value = json.loads(self.path.read_text(encoding='utf-8-sig'))
                if not isinstance(value, dict): raise ValueError('config must be an object')
                self.data = merge_settings(self.data,value)
            except (OSError, ValueError) as exc:
                self.error = type(exc).__name__

    def update(self, values):
        self.data = merge_settings(self.data,values)
        self.data['config_version'] = 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(value, decrypt=False):
    if not value: return ''
    if sys.platform != 'win32': raise OSError('Windows DPAPI required')
    raw = base64.b64decode(value) if decrypt else value.encode('utf-8')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    if decrypt:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(source), 'SCDesk', None, None, None, 1, ctypes.byref(result))
    if not ok: raise ctypes.WinError(ctypes.get_last_error())
    try:
        data = ctypes.string_at(result.data, result.size)
        return data.decode('utf-8') if decrypt else base64.b64encode(data).decode('ascii')
    finally:
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        kernel.LocalFree(result.data)


def unprotect(value):
    try: return protect(value, decrypt=True)
    except (OSError, ValueError, UnicodeError): return ''
