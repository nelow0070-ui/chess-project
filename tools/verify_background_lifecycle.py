import argparse
import ctypes
import gc
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_DIR / "src"


def parse_args():
    parser = argparse.ArgumentParser(
        description="checkss 백그라운드 분석 중단/재개와 메모리 회귀를 검증합니다."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=PROJECT_DIR / "output" / "background-lifecycle.db",
    )
    parser.add_argument("--depth", type=int, default=14)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--memory-cycles", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=90)
    return parser.parse_args()


def wait_until(predicate, timeout, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise TimeoutError("검증 조건을 제한 시간 안에 충족하지 못했습니다.")


def active_engine_pids(worker):
    with worker.lock:
        control = worker.active_control
    if not control:
        return set()
    with control.lock:
        engines = list(control.engines)
    pids = set()
    for engine in engines:
        try:
            pids.add(engine.transport.get_pid())
        except Exception:
            pass
    return pids


def process_exists(pid):
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def working_set_bytes():
    if sys.platform != "win32":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    process = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    ):
        raise ctypes.WinError()
    return counters.WorkingSetSize


def remove_test_database(path):
    for suffix in ("", "-wal", "-shm"):
        target = Path(f"{path}{suffix}")
        if target.exists():
            target.unlink()


def main():
    args = parse_args()
    args.db = args.db.resolve()
    args.db.parent.mkdir(parents=True, exist_ok=True)
    remove_test_database(args.db)
    os.environ["CHECKSS_DB_PATH"] = str(args.db)
    if str(SRC_DIR) not in sys.path:
        sys.path.insert(0, str(SRC_DIR))

    import analysis_service
    import database

    database.init_db()
    imported = database.import_pgn(
        (SRC_DIR / "games.pgn").read_text(encoding="utf-8"),
        "Nelo_w",
        provider="chesscom",
    )
    move_ids = imported["move_ids"]
    if not move_ids:
        raise RuntimeError("검증용 PGN에서 분석할 수를 만들지 못했습니다.")

    accounts = [{"provider": "chesscom", "username": "Nelo_w"}]
    worker = analysis_service.worker
    observed_pids = set()
    memory_samples = []
    shutdown_pids = set()
    restart_pids = set()

    try:
        job_id, _ = analysis_service.create_job(
            accounts,
            args.depth,
            args.workers,
            move_ids=move_ids,
        )
        wait_until(
            lambda: analysis_service.job_payload(job_id)["status"] == "running",
            args.timeout,
        )
        first_pids = wait_until(
            lambda: active_engine_pids(worker),
            args.timeout,
        )
        observed_pids.update(first_pids)

        if not analysis_service.cancel_job(job_id):
            raise AssertionError("실행 중인 작업의 중단 요청이 거부되었습니다.")
        if not analysis_service.resume_job(job_id):
            raise AssertionError("중단 직후 이어하기 요청이 거부되었습니다.")

        resumed_pids = wait_until(
            lambda: active_engine_pids(worker) - first_pids,
            args.timeout,
        )
        observed_pids.update(resumed_pids)
        completed = wait_until(
            lambda: (
                payload
                if (payload := analysis_service.job_payload(job_id))["status"]
                == "completed"
                else None
            ),
            args.timeout,
        )
        if completed["completed_moves"] != completed["total_moves"]:
            raise AssertionError("이어하기 후 pending 수가 남았습니다.")

        wait_until(
            lambda: worker.active_job_id is None
            and not active_engine_pids(worker),
            10,
        )
        wait_until(
            lambda: all(not process_exists(pid) for pid in observed_pids),
            10,
        )

        gc.collect()
        memory_samples.append(working_set_bytes())
        for _ in range(args.memory_cycles):
            cycle_job_id, _ = analysis_service.create_job(
                accounts,
                8,
                args.workers,
                move_ids=move_ids,
            )
            wait_until(
                lambda: analysis_service.job_payload(cycle_job_id)["status"]
                == "completed",
                args.timeout,
            )
            wait_until(lambda: worker.active_job_id is None, 10)
            gc.collect()
            time.sleep(0.2)
            memory_samples.append(working_set_bytes())

        numeric_samples = [value for value in memory_samples if value is not None]
        memory_growth = (
            max(numeric_samples[1:] or numeric_samples)
            - numeric_samples[0]
            if numeric_samples
            else None
        )
        if memory_growth is not None and memory_growth > 64 * 1024 * 1024:
            raise AssertionError(
                f"반복 분석 후 작업 세트가 {memory_growth / 1024 / 1024:.1f}MB 증가했습니다."
            )

        shutdown_job_id, _ = analysis_service.create_job(
            accounts,
            16,
            args.workers,
            move_ids=move_ids[:10],
        )
        wait_until(
            lambda: analysis_service.job_payload(shutdown_job_id)["status"]
            == "running",
            args.timeout,
        )
        shutdown_pids = wait_until(
            lambda: active_engine_pids(worker),
            args.timeout,
        )
        worker.shutdown(timeout=5)
        wait_until(
            lambda: all(not process_exists(pid) for pid in shutdown_pids),
            10,
        )
        interrupted = analysis_service.job_payload(shutdown_job_id)
        if interrupted["status"] != "running":
            raise AssertionError(
                "앱 종료를 모사한 뒤 작업이 재시작 가능한 running 상태로 남지 않았습니다."
            )

        worker = analysis_service.AnalysisWorker()
        analysis_service.worker = worker
        worker.resume()
        restart_pids = wait_until(
            lambda: active_engine_pids(worker),
            args.timeout,
        )
        restarted = wait_until(
            lambda: (
                payload
                if (
                    payload := analysis_service.job_payload(shutdown_job_id)
                )["status"]
                == "completed"
                else None
            ),
            args.timeout,
        )
        if restarted["completed_moves"] != restarted["total_moves"]:
            raise AssertionError("앱 재시작 후 자동 재개 작업에 pending 수가 남았습니다.")
        wait_until(
            lambda: all(not process_exists(pid) for pid in restart_pids),
            10,
        )

        print(
            json.dumps(
                {
                    "status": "ok",
                    "job_id": job_id,
                    "moves": completed["total_moves"],
                    "first_engine_pids": sorted(first_pids),
                    "resumed_engine_pids": sorted(resumed_pids),
                    "all_engines_exited": True,
                    "memory_mb": [
                        round(value / 1024 / 1024, 1)
                        if value is not None
                        else None
                        for value in memory_samples
                    ],
                    "memory_growth_mb": (
                        round(memory_growth / 1024 / 1024, 1)
                        if memory_growth is not None
                        else None
                    ),
                    "shutdown_engine_pids": sorted(shutdown_pids),
                    "restart_engine_pids": sorted(restart_pids),
                    "restart_completed": True,
                },
                ensure_ascii=False,
            )
        )
    finally:
        worker.shutdown(timeout=5)
        gc.collect()
        for _ in range(20):
            try:
                remove_test_database(args.db)
                break
            except PermissionError:
                gc.collect()
                time.sleep(0.05)


if __name__ == "__main__":
    main()
