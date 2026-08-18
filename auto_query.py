"""
auto_query.py
====================
The "Tự động truy vấn" timer: re-runs the pipeline on a schedule via
root.after(), independent of the log/info-panel widgets that live in main.py.

Reaches into the App instance (see main.py) for app.v["auto_value"]/
["auto_unit"], the log helper, and app.runner to check/start a run.

pause()/resume() are the only entry points other modules should use to stop
and restart the timer (e.g. while the "Tải số liệu" advanced-mode dialog is
open) — they keep auto_job/auto_next_run consistent instead of callers
poking those fields directly.
"""

import datetime


class AutoQuery:
    def __init__(self, app):
        self.app = app
        self.auto_job = None        # root.after() id for the pending auto-query tick
        self.auto_next_run = None   # datetime of the next scheduled auto-query tick (None = off)

    def _auto_effective_minutes(self) -> int:
        """Current interval in minutes; 0 means auto-query is off."""
        app = self.app
        try:
            v = int(app.v["auto_value"].get().strip())
        except ValueError:
            v = 0
        v = max(v, 0)
        return v * 60 if app.v["auto_unit"].get() == "Giờ" else v

    def _schedule_auto_tick(self):
        """(Re)schedule the next auto-query tick from the current value/unit; cancels any pending
        one first. Also tracks auto_next_run and refreshes the info panel's auto-query status."""
        app = self.app
        if self.auto_job is not None:
            app.root.after_cancel(self.auto_job)
            self.auto_job = None
        minutes = self._auto_effective_minutes()
        if minutes <= 0:
            self.auto_next_run = None
        else:
            self.auto_next_run = datetime.datetime.now() + datetime.timedelta(minutes=minutes)
            self.auto_job = app.root.after(minutes * 60 * 1000, self._on_auto_tick)
        app._refresh_info_panel()

    def _on_auto_tick(self):
        app = self.app
        self.auto_job = None
        if app.runner.worker and app.runner.worker.is_alive():
            app._log("SKIP", "Tự động truy vấn: bỏ qua vì đang có tác vụ chạy")
        else:
            app._log("ACT", "Tự động truy vấn: chạy truy vấn")
            app.runner._on_run()
        self._schedule_auto_tick()

    def _on_auto_change(self, event=None):
        """Entry/dropdown changed: normalize the value and reschedule the timer right away
        (takes effect immediately); persisting to config.ini happens via 'Lưu thiết lập'."""
        app = self.app
        v = self._auto_effective_value()
        app.v["auto_value"].set(str(v))
        unit = app.v["auto_unit"].get()
        state = "tắt" if v == 0 else f"mỗi {v} {unit.lower()}"
        app._log("ACT", f"Tùy chọn 'Tự động truy vấn': {state}")
        self._schedule_auto_tick()

    def _auto_effective_value(self) -> int:
        try:
            return max(int(self.app.v["auto_value"].get().strip()), 0)
        except ValueError:
            return 0

    def pause(self):
        """Cancel any pending tick and clear auto_next_run — used while advanced
        (date-range) mode is on, so a background tick can't re-fire a fetch the
        user is busy configuring."""
        app = self.app
        if self.auto_job is not None:
            app.root.after_cancel(self.auto_job)
            self.auto_job = None
        self.auto_next_run = None

    def resume(self):
        """Resume using the already-configured interval."""
        self._schedule_auto_tick()
