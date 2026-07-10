import ctypes
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from ctypes import wintypes


HOST = "127.0.0.1"
DEFAULT_PORT = int(
    os.environ.get("CHECKSS_PORT") or os.environ.get("CHESS_PORT", "5000")
)
PORT = DEFAULT_PORT
PORT_RANGE = range(DEFAULT_PORT, DEFAULT_PORT + 100)
INSTANCE_MUTEX_NAME = os.environ.get(
    "CHECKSS_INSTANCE_MUTEX",
    "Local\\checkss-single-instance",
)
ERROR_ALREADY_EXISTS = 183
STARTUP_WINDOW_CLASS = "checkss-startup-window"
STARTUP_WINDOW_TITLE = "checkss 시작 중"
APP_USER_MODEL_ID = "checkss.checkss"


def resource_path(*parts):
    if getattr(sys, "frozen", False):
        root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, *parts)


def app_icon_path():
    return resource_path("static", "assets", "checkss.ico")


def app_icon_png_path():
    return resource_path("static", "assets", "checkss-icon.png")


def configure_windows_app_identity():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            APP_USER_MODEL_ID
        )
    except Exception:
        pass


class StartupWindow:
    def __init__(self):
        self._commands = queue.Queue()
        self._ready = threading.Event()
        self._thread = None

    def start(self):
        if sys.platform != "win32":
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(2)

    def set_status(self, message):
        if self._thread:
            self._commands.put(("status", message))

    def close(self):
        if self._thread:
            self._commands.put(("close", None))

    def _run(self):
        if sys.platform != "win32":
            self._ready.set()
            return

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        hinstance = kernel32.GetModuleHandleW(None)
        width, height = 440, 176
        animation_x = 0
        status_text = "실행 환경을 확인하고 있습니다."

        WM_DESTROY = 0x0002
        WM_PAINT = 0x000F
        WM_SETICON = 0x0080
        WM_TIMER = 0x0113
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WS_POPUP = 0x80000000
        WS_VISIBLE = 0x10000000
        WS_BORDER = 0x00800000
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        SW_SHOW = 5
        IDC_ARROW = 32512
        DT_CENTER = 0x00000001
        DT_VCENTER = 0x00000004
        DT_SINGLELINE = 0x00000020
        TRANSPARENT = 1

        class PaintStruct(ctypes.Structure):
            _fields_ = [
                ("hdc", wintypes.HDC),
                ("fErase", wintypes.BOOL),
                ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32),
            ]

        window_proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        class WindowClass(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", window_proc_type),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.UnregisterClassW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.HINSTANCE,
        ]
        user32.LoadCursorW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.HANDLE,
        ]
        user32.LoadCursorW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.UpdateWindow.argtypes = [wintypes.HWND]
        user32.SetTimer.argtypes = [
            wintypes.HWND,
            ctypes.c_size_t,
            wintypes.UINT,
            wintypes.LPVOID,
        ]
        user32.SetTimer.restype = ctypes.c_size_t
        user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        user32.InvalidateRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
            wintypes.BOOL,
        ]
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        user32.BeginPaint.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(PaintStruct),
        ]
        user32.BeginPaint.restype = wintypes.HDC
        user32.EndPaint.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(PaintStruct),
        ]
        user32.DrawTextW.argtypes = [
            wintypes.HDC,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(wintypes.RECT),
            wintypes.UINT,
        ]
        user32.FillRect.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.HBRUSH,
        ]
        gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
        gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
        gdi32.CreateFontW.restype = wintypes.HFONT
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL

        def color(red, green, blue):
            return red | (green << 8) | (blue << 16)

        title_font = gdi32.CreateFontW(
            -31, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"
        )
        body_font = gdi32.CreateFontW(
            -15, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"
        )
        detail_font = gdi32.CreateFontW(
            -12, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI"
        )

        def fill_rect(hdc, left, top, right, bottom, fill_color):
            brush = gdi32.CreateSolidBrush(fill_color)
            rect = wintypes.RECT(left, top, right, bottom)
            user32.FillRect(hdc, ctypes.byref(rect), brush)
            gdi32.DeleteObject(brush)

        @window_proc_type
        def window_proc(hwnd, message, wparam, lparam):
            nonlocal animation_x, status_text

            if message == WM_TIMER:
                should_close = False
                while True:
                    try:
                        command, value = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    if command == "status":
                        status_text = value
                    elif command == "close":
                        should_close = True
                if should_close:
                    user32.DestroyWindow(hwnd)
                    return 0
                animation_x = (animation_x + 7) % 412
                user32.InvalidateRect(hwnd, None, False)
                return 0

            if message == WM_PAINT:
                paint = PaintStruct()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(paint))
                fill_rect(hdc, 0, 0, width, height, color(66, 17, 29))
                gdi32.SetBkMode(hdc, TRANSPARENT)

                title_rect = wintypes.RECT(0, 23, width, 61)
                gdi32.SelectObject(hdc, title_font)
                gdi32.SetTextColor(hdc, color(255, 250, 246))
                user32.DrawTextW(
                    hdc,
                    "checkss",
                    -1,
                    ctypes.byref(title_rect),
                    DT_CENTER | DT_VCENTER | DT_SINGLELINE,
                )

                status_rect = wintypes.RECT(0, 68, width, 92)
                gdi32.SelectObject(hdc, body_font)
                gdi32.SetTextColor(hdc, color(243, 231, 234))
                user32.DrawTextW(
                    hdc,
                    status_text,
                    -1,
                    ctypes.byref(status_rect),
                    DT_CENTER | DT_VCENTER | DT_SINGLELINE,
                )

                detail_rect = wintypes.RECT(0, 96, width, 118)
                gdi32.SelectObject(hdc, detail_font)
                gdi32.SetTextColor(hdc, color(205, 184, 190))
                user32.DrawTextW(
                    hdc,
                    "잠시만 기다려 주세요. 준비가 끝나면 브라우저가 열립니다.",
                    -1,
                    ctypes.byref(detail_rect),
                    DT_CENTER | DT_VCENTER | DT_SINGLELINE,
                )

                fill_rect(hdc, 55, 137, 385, 141, color(91, 28, 44))
                right = 55 + animation_x
                left = right - 82
                fill_rect(
                    hdc,
                    max(55, left),
                    137,
                    min(385, right),
                    141,
                    color(208, 166, 90),
                )
                user32.EndPaint(hwnd, ctypes.byref(paint))
                return 0

            if message == WM_DESTROY:
                user32.KillTimer(hwnd, 1)
                user32.PostQuitMessage(0)
                return 0

            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        window_class = WindowClass()
        window_class.lpfnWndProc = window_proc
        window_class.hInstance = hinstance
        window_class.hCursor = user32.LoadCursorW(
            None,
            ctypes.c_void_p(IDC_ARROW),
        )
        hicon = None
        icon_path = app_icon_path()
        if os.path.exists(icon_path):
            hicon = user32.LoadImageW(
                None,
                icon_path,
                IMAGE_ICON,
                32,
                32,
                LR_LOADFROMFILE,
            )
            window_class.hIcon = hicon
        window_class.lpszClassName = STARTUP_WINDOW_CLASS

        try:
            if not user32.RegisterClassW(ctypes.byref(window_class)):
                raise ctypes.WinError(ctypes.get_last_error())

            x = max(0, (user32.GetSystemMetrics(0) - width) // 2)
            y = max(0, (user32.GetSystemMetrics(1) - height) // 2)
            hwnd = user32.CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_TOOLWINDOW,
                STARTUP_WINDOW_CLASS,
                STARTUP_WINDOW_TITLE,
                WS_POPUP | WS_VISIBLE | WS_BORDER,
                x,
                y,
                width,
                height,
                None,
                None,
                hinstance,
                None,
            )
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())

            if hicon:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
            user32.SetTimer(hwnd, 1, 35, None)
            user32.ShowWindow(hwnd, SW_SHOW)
            user32.UpdateWindow(hwnd)
            self._ready.set()

            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception:
            self._ready.set()
        finally:
            for font in (title_font, body_font, detail_font):
                if font:
                    gdi32.DeleteObject(font)
            user32.UnregisterClassW(STARTUP_WINDOW_CLASS, hinstance)


def focus_startup_window():
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    handle = user32.FindWindowW(STARTUP_WINDOW_CLASS, None)
    if not handle:
        return False
    user32.ShowWindow(handle, 9)
    user32.SetForegroundWindow(handle)
    return True


def instance_port_path():
    base_dir = os.environ.get("LOCALAPPDATA")
    if not base_dir:
        base_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base_dir, "checkss", "instance.port")


def read_instance_port():
    try:
        with open(instance_port_path(), encoding="ascii") as port_file:
            port = int(port_file.read().strip())
    except (OSError, TypeError, ValueError):
        return None
    return port if port in PORT_RANGE else None


def write_instance_port(port):
    path = instance_port_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = f"{path}.{os.getpid()}.tmp"
    with open(temporary_path, "w", encoding="ascii") as port_file:
        port_file.write(str(port))
    os.replace(temporary_path, path)


def clear_instance_port(port):
    path = instance_port_path()
    if read_instance_port() != port:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def app_url(port=None):
    return f"http://{HOST}:{port or PORT}"


def health_url(port=None):
    return f"{app_url(port)}/api/health"


def browser_app_candidates():
    configured = os.environ.get("CHECKSS_APP_BROWSER_PATH")
    if configured:
        yield configured

    for executable in ("msedge.exe", "chrome.exe"):
        found = shutil.which(executable)
        if found:
            yield found

    roots = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ]
    relative_paths = [
        ("Microsoft", "Edge", "Application", "msedge.exe"),
        ("Google", "Chrome", "Application", "chrome.exe"),
    ]
    for root in roots:
        if not root:
            continue
        for relative_path in relative_paths:
            yield os.path.join(root, *relative_path)


def open_app_window(url):
    if sys.platform != "win32" or os.environ.get("CHECKSS_OPEN_BROWSER") == "1":
        return False

    for executable in browser_app_candidates():
        if not executable or not os.path.exists(executable):
            continue
        try:
            subprocess.Popen(
                [executable, f"--app={url}", "--new-window"],
                close_fds=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return True
        except OSError:
            continue
    return False


def open_browser():
    if (
        os.environ.get("CHECKSS_NO_BROWSER")
        or os.environ.get("CHESS_NO_BROWSER")
    ) != "1":
        url = app_url()
        if not open_app_window(url):
            webbrowser.open(url)


def show_error(message):
    ctypes.windll.user32.MessageBoxW(0, message, "checkss", 0x10)


def checkss_is_running(port=None, timeout=0.5):
    try:
        with urllib.request.urlopen(health_url(port), timeout=timeout) as response:
            return response.status == 200 and b'"checkss"' in response.read()
    except (OSError, urllib.error.URLError):
        return False


def port_is_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
        except OSError:
            return False
    return True


def find_running_port():
    preferred_port = read_instance_port()
    ports = ([preferred_port] if preferred_port is not None else []) + [
        port for port in PORT_RANGE if port != preferred_port
    ]
    for port in ports:
        if not port_is_available(port) and checkss_is_running(port, timeout=0.15):
            return port
    return None


def select_port():
    first_available = None
    for port in PORT_RANGE:
        if port_is_available(port):
            if first_available is None:
                first_available = port
        elif checkss_is_running(port):
            return port, True
    if first_available is not None:
        return first_available, False
    raise RuntimeError("사용 가능한 로컬 포트를 찾지 못했습니다.")


def wait_for_running_port(timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        running_port = find_running_port()
        if running_port is not None:
            return running_port
        time.sleep(0.1)
    return None


def acquire_instance_mutex(name=INSTANCE_MUTEX_NAME):
    if sys.platform != "win32":
        return None, False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    )
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return (kernel32, handle), ctypes.get_last_error() == ERROR_ALREADY_EXISTS


def release_instance_mutex(mutex):
    if mutex:
        kernel32, handle = mutex
        kernel32.CloseHandle(handle)


def tray_image():
    from PIL import Image, ImageDraw

    icon_path = app_icon_png_path()
    if os.path.exists(icon_path):
        return Image.open(icon_path).convert("RGBA").resize((64, 64))

    image = Image.new("RGBA", (64, 64), "#111827")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=9, fill="#f8fafc")
    draw.rectangle((17, 16, 27, 27), fill="#111827")
    draw.rectangle((37, 16, 47, 27), fill="#111827")
    draw.rectangle((27, 27, 37, 38), fill="#111827")
    draw.rectangle((17, 38, 27, 48), fill="#111827")
    draw.rectangle((37, 38, 47, 48), fill="#111827")
    return image


def run_server(state):
    try:
        from waitress import serve
        from server import app, worker

        state["worker"] = worker
        serve(app, host=HOST, port=PORT, threads=8)
    except Exception as exc:
        state["error"] = str(exc)


def wait_until_ready(icon, state, startup):
    while not state.get("error"):
        if checkss_is_running():
            startup.close()
            open_browser()
            try:
                icon.notify(
                    "checkss 앱 창을 열었습니다.",
                    "checkss 실행 중",
                )
            except Exception:
                pass
            return
        time.sleep(0.25)
    startup.close()
    show_error(f"서버를 시작하지 못했습니다.\n\n{state['error']}")
    icon.stop()


def exit_app(icon, _item, state):
    worker = state.get("worker")
    if worker:
        worker.shutdown(timeout=5)
    icon.stop()
    os._exit(0)


def main():
    global PORT
    configure_windows_app_identity()
    mutex = None
    startup = StartupWindow()
    owns_instance = False
    try:
        mutex, duplicate_instance = acquire_instance_mutex()
        if duplicate_instance:
            PORT = read_instance_port() or DEFAULT_PORT
            if checkss_is_running(PORT, timeout=0.3):
                open_browser()
            elif focus_startup_window():
                return
            elif (running_port := find_running_port()) is not None:
                PORT = running_port
                open_browser()
            else:
                show_error(
                    "checkss가 이미 시작 중입니다.\n"
                    "잠시 후 브라우저가 자동으로 열립니다."
                )
            return
        owns_instance = True
        startup.start()
        PORT, already_running = select_port()
        write_instance_port(PORT)
    except RuntimeError as exc:
        startup.close()
        show_error(str(exc))
        return
    except OSError as exc:
        startup.close()
        show_error(f"단일 실행 잠금을 만들지 못했습니다.\n\n{exc}")
        return

    try:
        if already_running:
            startup.close()
            open_browser()
            return

        startup.set_status("데이터와 분석 엔진을 준비하고 있습니다.")
        import pystray

        state = {}
        icon = pystray.Icon(
            "checkss",
            tray_image(),
            "checkss",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "checkss 창 열기",
                    lambda _icon, _item: open_browser(),
                    default=True,
                ),
                pystray.MenuItem(
                    "종료",
                    lambda tray_icon, item: exit_app(tray_icon, item, state),
                ),
            ),
        )
        threading.Thread(target=run_server, args=(state,), daemon=True).start()
        threading.Thread(
            target=wait_until_ready,
            args=(icon, state, startup),
            daemon=True,
        ).start()
        icon.run()
    except Exception as exc:
        startup.close()
        show_error(f"checkss를 시작하지 못했습니다.\n\n{exc}")
    finally:
        startup.close()
        if owns_instance:
            clear_instance_port(PORT)
        release_instance_mutex(mutex)


if __name__ == "__main__":
    main()
