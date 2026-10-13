"""Windows의 자격 증명 관리자에 API 키를 두는 길. macOS의 키체인 자리예요 (backend/engines/keys.py가 불러요).

넣은 키는 제어판 → 자격 증명 관리자 → Windows 자격 증명 → ‘일반 자격 증명’에 보여요. 그 PC에 로그인한 사용자만 읽을 수 있게
Windows가 암호화해 둬요. 파일에 글자 그대로 적지 않고, 명령 줄에도 넘기지 않아요 (Windows에 직접 물어요).
Windows에서만 불러요.
"""
import ctypes
from ctypes import wintypes

GENERIC = 1            # CRED_TYPE_GENERIC
LOCAL_MACHINE = 2      # CRED_PERSIST_LOCAL_MACHINE: 이 PC에만 둬요 (다른 PC로 따라가지 않아요)
USER = "gadak"         # 자격 증명 관리자의 ‘사용자 이름’ 칸에 보이는 말


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


def _api():
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(_Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def read(target):
    """그 이름으로 넣어 둔 글. 없으면 None."""
    api, found = _api(), ctypes.POINTER(_Credential)()
    if not api.CredReadW(target, GENERIC, 0, ctypes.byref(found)):
        return None
    try:
        raw = ctypes.string_at(found.contents.CredentialBlob, found.contents.CredentialBlobSize)
    finally:
        api.CredFree(found)
    return raw.decode("utf-16-le", errors="replace") or None


def write(target, secret, label) -> bool:
    """넣어요(있으면 바꿔요). 됐으면 True."""
    raw = secret.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    entry = _Credential(Type=GENERIC, TargetName=target, Comment=label, CredentialBlobSize=len(raw),
                        CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)), Persist=LOCAL_MACHINE, UserName=USER)
    return bool(_api().CredWriteW(ctypes.byref(entry), 0))


def delete(target) -> bool:
    """지워요. 지운 것이 있으면 True."""
    return bool(_api().CredDeleteW(target, GENERIC, 0))
