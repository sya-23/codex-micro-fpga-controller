from __future__ import annotations

import argparse
import logging
import signal
import threading

from codex_micro.core import Controller
from codex_micro.desktop import VK_CONTROL, VK_RETURN, DesktopAdapter
from codex_micro.server import ControllerHTTPServer
from codex_micro.session_log import SessionLogMonitor
from codex_micro.status_monitor import ChatGPTStatusMonitor
from codex_micro.transport import SerialTransport


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex-Micro local controller")
    parser.add_argument("--serial-port", default="COM5")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument(
        "--sync-interval",
        type=float,
        default=0.0,
        help="periodic FPGA state resynchronization interval in seconds",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-serial", action="store_true")
    parser.add_argument(
        "--send-hotkey",
        choices=("enter", "ctrl-enter"),
        default="enter",
        help="desktop send shortcut; assign the same shortcut in the app",
    )
    parser.add_argument(
        "--status-interval",
        type=float,
        default=0.8,
        help="ChatGPT conversation-list status polling interval in seconds",
    )
    parser.add_argument(
        "--no-status-monitor",
        action="store_true",
        help="disable Windows UI Automation status monitoring",
    )
    parser.add_argument(
        "--session-log-root",
        default="",
        help="Codex JSONL session directory; defaults to the user's .codex\\sessions",
    )
    parser.add_argument(
        "--no-session-log-monitor",
        action="store_true",
        help="disable read-only Codex JSONL lifecycle monitoring",
    )
    return parser.parse_args()


def send_hotkey(name: str) -> tuple[int, ...]:
    return (VK_RETURN,) if name == "enter" else (VK_CONTROL, VK_RETURN)


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    adapter = DesktopAdapter(
        dry_run=args.dry_run,
        send_hotkey=send_hotkey(args.send_hotkey),
    )
    controller = Controller(adapter)
    transport = None
    if not args.no_serial:
        transport = SerialTransport(
            port=args.serial_port,
            baud=args.baud,
            on_frame=controller.on_frame,
            on_connect=controller.sync,
        )
        controller.set_transport(transport)
        transport.start()

    server = ControllerHTTPServer(("127.0.0.1", args.http_port), controller)
    session_log_monitor = None
    if not args.no_session_log_monitor and not args.dry_run:
        session_log_monitor = SessionLogMonitor(
            controller,
            root=args.session_log_root or None,
            interval=args.status_interval,
        )
        session_log_monitor.start()
    status_monitor = None
    if not args.no_status_monitor and not args.dry_run:
        status_monitor = ChatGPTStatusMonitor(controller, args.status_interval)
        status_monitor.start()
    stop = threading.Event()

    def shutdown(_signum=None, _frame=None) -> None:
        stop.set()
        server.shutdown()

    def sync_loop() -> None:
        while args.sync_interval > 0 and not stop.wait(args.sync_interval):
            try:
                controller.sync()
            except Exception:
                logging.exception("periodic FPGA sync failed")

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    sync_thread = threading.Thread(target=sync_loop, name="fpga-sync", daemon=True)
    sync_thread.start()
    logging.info("Controller API listening on http://127.0.0.1:%d", args.http_port)
    try:
        server.serve_forever()
    finally:
        stop.set()
        sync_thread.join(timeout=1)
        if session_log_monitor is not None:
            session_log_monitor.stop()
        if status_monitor is not None:
            status_monitor.stop()
        controller.shutdown()
        if transport is not None:
            transport.stop()
        server.server_close()


if __name__ == "__main__":
    main()
