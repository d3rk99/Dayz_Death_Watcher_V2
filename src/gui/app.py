from __future__ import annotations

import json
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, ttk, Text, messagebox
from typing import Dict, List

from ..core.config import AppConfig, ConfigLoader
from ..core.persistence import UsersRepository
from ..watchers.ljson_tailer import LogEvent, parse_death_event


class DeathWatcherGUI:
    def __init__(self, root: Tk, config_path: Path) -> None:
        self.root = root
        self.root.title("DeathWatcher v2")
        self.config_loader = ConfigLoader(config_path)
        self.config = self.config_loader.load()
        self.users_repo = UsersRepository(Path(self.config.paths.users_db_path))
        self.enable_writes = BooleanVar(value=False)
        self.theme = StringVar(value="dark")
        self.tabs: Dict[str, ttk.Frame] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.root.geometry("1200x800")
        self.root.minsize(900, 600)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        for name in [
            "Dashboard",
            "Currently Dead",
            "Death Counter",
            "Lists",
            "Admins",
            "Leaderboard",
            "Settings",
            "Danger Zone",
        ]:
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=name)
            self.tabs[name] = frame

        self._build_dashboard()
        self._build_currently_dead()
        self._build_death_counter()
        self._build_lists()
        self._build_admins()
        self._build_leaderboard()
        self._build_settings()
        self._build_danger_zone()

    def _build_dashboard(self) -> None:
        frame = self.tabs["Dashboard"]
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Checkbutton(top, text="Enable Writes", variable=self.enable_writes).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_dashboard).pack(side="left", padx=8)
        ttk.Button(top, text="Test Parse", command=self.open_test_parse).pack(side="left")

        logs_frame = ttk.Frame(frame)
        logs_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_boxes: List[Text] = []
        for server in self.config.servers:
            box = Text(logs_frame, height=8, wrap="none")
            box.insert("end", f"Server {server.server_id} log preview\n")
            box.configure(state="disabled")
            box.pack(fill="both", expand=True, pady=4)
            self.log_boxes.append(box)

        activity = Text(frame, height=8)
        activity.insert("end", "Bot activity feed\n")
        activity.configure(state="disabled")
        activity.pack(fill="both", expand=True, padx=10, pady=10)
        self.activity_box = activity

    def refresh_dashboard(self) -> None:
        audit_path = Path(self.config.paths.audit_log_path)
        lines = audit_path.read_text(encoding="utf-8").splitlines() if audit_path.exists() else []
        self.activity_box.configure(state="normal")
        self.activity_box.delete("1.0", "end")
        self.activity_box.insert("end", "\n".join(lines[-20:]) + "\n")
        self.activity_box.configure(state="disabled")

    def open_test_parse(self) -> None:
        dialog = Tk()
        dialog.title("Test Parse")
        dialog.geometry("600x300")
        input_box = Text(dialog, height=6)
        input_box.pack(fill="both", expand=True, padx=8, pady=8)
        output_box = Text(dialog, height=6)
        output_box.pack(fill="both", expand=True, padx=8, pady=8)

        def run_parse() -> None:
            raw = input_box.get("1.0", "end").strip()
            output_box.configure(state="normal")
            output_box.delete("1.0", "end")
            try:
                payload = json.loads(raw)
                event = LogEvent(server_id="test", raw=raw, data=payload)
                result = parse_death_event(event)
                output_box.insert("end", json.dumps(result, indent=2))
            except json.JSONDecodeError as exc:
                output_box.insert("end", f"Invalid JSON: {exc}")
            output_box.configure(state="disabled")

        ttk.Button(dialog, text="Parse", command=run_parse).pack(pady=6)

    def _build_currently_dead(self) -> None:
        frame = self.tabs["Currently Dead"]
        columns = ("steam_id", "discord_id", "server", "dead")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
        tree.pack(fill="both", expand=True)
        self.dead_tree = tree
        self.refresh_dead_list()

    def refresh_dead_list(self) -> None:
        self.dead_tree.delete(*self.dead_tree.get_children())
        users = self.users_repo.load().users.values()
        for user in users:
            if user.dead:
                self.dead_tree.insert("", "end", values=(user.steam_id, user.discord_id, user.active_server_id, user.dead))

    def _build_death_counter(self) -> None:
        frame = self.tabs["Death Counter"]
        box = Text(frame)
        box.pack(fill="both", expand=True)
        self.death_counter_box = box
        self.refresh_death_counter()

    def refresh_death_counter(self) -> None:
        users = self.users_repo.load().users.values()
        total_deaths = sum(user.death_count for user in users)
        self.death_counter_box.delete("1.0", "end")
        self.death_counter_box.insert("end", f"Total deaths: {total_deaths}\n")

    def _build_lists(self) -> None:
        frame = self.tabs["Lists"]
        box = Text(frame)
        box.pack(fill="both", expand=True)
        box.insert("end", "Ban/Whitelist view placeholder\n")

    def _build_admins(self) -> None:
        frame = self.tabs["Admins"]
        box = Text(frame)
        box.pack(fill="both", expand=True)
        box.insert("end", "Admins list placeholder\n")

    def _build_leaderboard(self) -> None:
        frame = self.tabs["Leaderboard"]
        box = Text(frame)
        box.pack(fill="both", expand=True)
        box.insert("end", "Leaderboard preview placeholder\n")

    def _build_settings(self) -> None:
        frame = self.tabs["Settings"]
        row = ttk.Frame(frame)
        row.pack(fill="x", padx=10, pady=10)
        ttk.Label(row, text="Theme").pack(side="left")
        ttk.Combobox(row, textvariable=self.theme, values=["dark", "light"]).pack(side="left", padx=8)
        ttk.Button(row, text="Reload Config", command=self.reload_config).pack(side="left")
        self.settings_box = Text(frame)
        self.settings_box.pack(fill="both", expand=True, padx=10, pady=10)
        self._render_config()

    def _render_config(self) -> None:
        self.settings_box.delete("1.0", "end")
        self.settings_box.insert("end", json.dumps(self.config.to_dict(), indent=2))

    def reload_config(self) -> None:
        self.config = self.config_loader.load()
        self._render_config()
        messagebox.showinfo("Config", "Config reloaded.")

    def _build_danger_zone(self) -> None:
        frame = self.tabs["Danger Zone"]
        ttk.Button(frame, text="Wipe Database", command=self.wipe_database).pack(pady=12)

    def wipe_database(self) -> None:
        if not self.enable_writes.get():
            messagebox.showwarning("Writes Disabled", "Enable writes first.")
            return
        confirm = messagebox.askyesno("Confirm", "This will wipe the database. Continue?")
        if not confirm:
            return
        self.users_repo.store.save({})
        messagebox.showinfo("Complete", "Database wiped.")


def run_gui() -> None:
    root = Tk()
    app = DeathWatcherGUI(root, Path("config.json"))
    root.mainloop()
