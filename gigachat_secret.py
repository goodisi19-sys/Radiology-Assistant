"""Optional per-user Windows DPAPI storage, separate from SQLite/backups."""
import ctypes
import os
from pathlib import Path

def _crypt(data, decrypt=False):
    if os.name != 'nt': raise OSError('Сохранение ключа доступно только в Windows. Ключ можно использовать без сохранения.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte*len(data)).from_buffer_copy(data)
    source, target = Blob(len(data),buffer), Blob()
    crypt = ctypes.WinDLL('crypt32',use_last_error=True)
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]; kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob),wintypes.LPCWSTR,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(source),'Radiology Assistant GigaChat',None,None,None,1,ctypes.byref(target))
    if not ok: raise OSError('Windows не удалось защитить или прочитать ключ.')
    try: return ctypes.string_at(target.data,target.size)
    finally: kernel.LocalFree(target.data)

def save_key(path, key):
    encrypted = _crypt(key.encode('utf-8'))
    path = Path(path); temporary = path.with_suffix('.tmp')
    try: temporary.write_bytes(encrypted); os.replace(temporary,path)
    finally: temporary.unlink(missing_ok=True)

def load_key(path):
    path = Path(path)
    return _crypt(path.read_bytes(),True).decode('utf-8') if path.exists() else ''
