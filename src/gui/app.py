from __future__ import annotations

import json
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, ttk, Text, messagebox
from typing import Dict, List, Optional

from ..adapters.dayz_lists import DayZListAdapter, ServerLists
from ..core.config import AppConfig, ConfigLoader
from ..core.persistence import UserRecord, UsersRepository
from ..watchers.ljson_tailer import LjsonTailer, TailerOptions


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
            "User Tools",
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
        self._build_user_tools()

    def _build_dashboard(self) -> None:
        frame = self.tabs["Dashboard"]
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Checkbutton(top, text="Enable Writes", variable=self.enable_writes).pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_dashboard).pack(side="left", padx=8)

        logs_frame = ttk.Frame(frame)
        logs_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.log_boxes: List[Text] = []
        for server in self.config.servers:
            box = Text(logs_frame, height=6, wrap="none")
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

        for box, server in zip(self.log_boxes, self.config.servers):
            options = TailerOptions(
                tail_mode="newest_with_backlog",
                backlog_max_lines=10,
                strict_death_schema=self.config.legacy_logs.strict_death_schema,
                archive_old_logs=False,
            )
            tailer = LjsonTailer(Path(server.path_to_logs_directory), 0, options)
            preview = []
            for event in tailer.read_events(server.server_id) or []:
                preview.append(event.raw)
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("end", "\n".join(preview[-10:]) + "\n")
            box.configure(state="disabled")

    def _build_currently_dead(self) -> None:
        frame = self.tabs["Currently Dead"]
        columns = ("steam_id", "discord_id", "server", "dead_until", "last_alive")
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
        tree.pack(fill="both", expand=True)
        self.dead_tree = tree
        ttk.Button(frame, text="Revive Selected", command=self.revive_selected).pack(pady=8)
        self.refresh_dead_list()

    def refresh_dead_list(self) -> None:
        self.dead_tree.delete(*self.dead_tree.get_children())
        users = self.users_repo.load().users.values()
        for user in users:
            if user.dead:
                self.dead_tree.insert(
                    "",
                    "end",
                    values=(
                        user.steam_id,
                        user.discord_id,
                        user.last_death_server_id,
                        user.dead_until,
                        user.last_alive_sec,
                    ),
                )

    def revive_selected(self) -> None:
        if not self.enable_writes.get():
            messagebox.showwarning("Writes Disabled", "Enable writes first.")
            return
        selection = self.dead_tree.selection()
        if not selection:
            return
        confirm = messagebox.askyesno("Confirm", "Revive selected users? This will edit the DB.")
        if not confirm:
            return
        db = self.users_repo.load()
        for item in selection:
            steam_id = self.dead_tree.item(item, "values")[0]
            user = db.users.get(steam_id)
            if not user:
                continue
            user.dead = False
            user.dead_until = None
            user.last_dead_at = None
            db.users[steam_id] = user
        self.users_repo.save(db)
        self.refresh_dead_list()

    def _build_death_counter(self) -> None:
        frame = self.tabs["Death Counter"]
        box = Text(frame)
        box.pack(fill="both", expand=True)
        self.death_counter_box = box
        self.refresh_death_counter()

    def refresh_death_counter(self) -> None:
        users = self.users_repo.load().users.values()
        total_deaths = sum(user.death_count for user in users)
        per_server: Dict[str, int] = {}
        for user in users:
            if user.last_death_server_id:
                per_server[user.last_death_server_id] = per_server.get(user.last_death_server_id, 0) + 1
        self.death_counter_box.delete("1.0", "end")
        self.death_counter_box.insert("end", f"Total deaths: {total_deaths}\n")
        for server_id, count in per_server.items():
            self.death_counter_box.insert("end", f"{server_id}: {count}\n")

    def _build_lists(self) -> None:
        frame = self.tabs["Lists"]
        notebook = ttk.Notebook(frame)
        notebook.pack(fill="both", expand=True)
        self.list_boxes: Dict[str, Dict[str, Text]] = {}
        for server in self.config.servers:
            sub = ttk.Frame(notebook)
            notebook.add(sub, text=server.server_id)
            ban_box = Text(sub, height=10)
            whitelist_box = Text(sub, height=10)
            ban_box.pack(fill="both", expand=True)
            whitelist_box.pack(fill="both", expand=True)
            self.list_boxes[server.server_id] = {"ban": ban_box, "whitelist": whitelist_box}
        ttk.Button(frame, text="Refresh Lists", command=self.refresh_lists).pack(pady=6)

    def refresh_lists(self) -> None:
        for server in self.config.servers:
            adapter = DayZListAdapter(ServerLists(Path(server.path_to_bans), Path(server.path_to_whitelist)))
            bans = sorted(adapter.read_ban_list())
            whitelist = sorted(adapter.read_whitelist())
            ban_box = self.list_boxes[server.server_id]["ban"]
            whitelist_box = self.list_boxes[server.server_id]["whitelist"]
            ban_box.delete("1.0", "end")
            ban_box.insert("end", "\n".join(bans))
            whitelist_box.delete("1.0", "end")
            whitelist_box.insert("end", "\n".join(whitelist))

    def _build_admins(self) -> None:
        frame = self.tabs["Admins"]
        box = Text(frame)
        box.pack(fill="both", expand=True)
        self.admins_box = box
        self.refresh_admins()

    def refresh_admins(self) -> None:
        users = [user for user in self.users_repo.load().users.values() if user.is_admin]
        self.admins_box.delete("1.0", "end")
        for user in users:
            self.admins_box.insert("end", f"{user.steam_id} -> {user.discord_id}\n")

    def _build_leaderboard(self) -> None:
        frame = self.tabs["Leaderboard"]
        box = Text(frame)
        box.pack(fill="both", expand=True)
        self.leaderboard_box = box
        ttk.Button(frame, text="Refresh Leaderboard", command=self.refresh_leaderboard).pack(pady=6)
        self.refresh_leaderboard()

    def refresh_leaderboard(self) -> None:
        users = list(self.users_repo.load().users.values())
        if self.config.leaderboard.metric == "death_count":
            ranked = sorted(users, key=lambda u: u.death_count, reverse=True)
            title = "Top Deaths"
            lines = [f"{idx+1}. {user.steam_id} — deaths: {user.death_count}" for idx, user in enumerate(ranked[:10])]
        else:
            ranked = sorted(users, key=lambda u: u.last_alive_sec or 0, reverse=True)
            title = "Top Survivors"
            lines = [
                f"{idx+1}. {user.steam_id} — aliveSec: {user.last_alive_sec or 0}" for idx, user in enumerate(ranked[:10])
            ]
        self.leaderboard_box.delete("1.0", "end")
        self.leaderboard_box.insert("end", "\n".join([title, *lines]))

    def _build_settings(self) -> None:
        frame = self.tabs["Settings"]
        row = ttk.Frame(frame)
        row.pack(fill="x", padx=10, pady=10)
        ttk.Label(row, text="Theme").pack(side="left")
        ttk.Combobox(row, textvariable=self.theme, values=["dark", "light"]).pack(side="left", padx=8)
        ttk.Button(row, text="Reload Config", command=self.reload_config).pack(side="left", padx=6)
        ttk.Button(row, text="Apply JSON", command=self.apply_json_config).pack(side="left", padx=6)

        err_frame = ttk.LabelFrame(frame, text="Error Reporting")
        err_frame.pack(fill="x", padx=10, pady=10)
        self.error_channel = StringVar(value=str(self.config.error_reporting.error_dump_channel_id))
        self.error_allow_mention = BooleanVar(value=self.config.error_reporting.error_dump_allow_mention)
        self.error_mention_tag = StringVar(value=self.config.error_reporting.error_dump_mention_tag)
        self.error_rate_limit = StringVar(value=str(self.config.error_reporting.error_dump_rate_limit_seconds))
        self.error_include_traceback = BooleanVar(value=self.config.error_reporting.error_dump_include_traceback)
        ttk.Label(err_frame, text="Channel ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(err_frame, textvariable=self.error_channel).grid(row=0, column=1, sticky="ew")
        ttk.Checkbutton(err_frame, text="Allow mention", variable=self.error_allow_mention).grid(row=1, column=0, sticky="w")
        ttk.Entry(err_frame, textvariable=self.error_mention_tag).grid(row=1, column=1, sticky="ew")
        ttk.Label(err_frame, text="Rate limit (sec)").grid(row=2, column=0, sticky="w")
        ttk.Entry(err_frame, textvariable=self.error_rate_limit).grid(row=2, column=1, sticky="ew")
        ttk.Checkbutton(err_frame, text="Include traceback", variable=self.error_include_traceback).grid(
            row=3, column=0, sticky="w"
        )
        err_frame.columnconfigure(1, weight=1)

        ttk.Button(frame, text="Save Config", command=self.save_config).pack(pady=8)
        self.settings_box = Text(frame)
        self.settings_box.pack(fill="both", expand=True, padx=10, pady=10)
        self._render_config()

    def _render_config(self) -> None:
        self.settings_box.delete("1.0", "end")
        self.settings_box.insert("end", json.dumps(self.config.to_dict(), indent=2))

    def save_config(self) -> None:
        if not self.enable_writes.get():
            messagebox.showwarning("Writes Disabled", "Enable writes first.")
            return
        confirm = messagebox.askyesno("Confirm", "Overwrite config.json with current settings?")
        if not confirm:
            return
        self.config.error_reporting.error_dump_channel_id = int(self.error_channel.get() or 0)
        self.config.error_reporting.error_dump_allow_mention = self.error_allow_mention.get()
        self.config.error_reporting.error_dump_mention_tag = self.error_mention_tag.get()
        self.config.error_reporting.error_dump_rate_limit_seconds = int(self.error_rate_limit.get() or 0)
        self.config.error_reporting.error_dump_include_traceback = self.error_include_traceback.get()
        self.config_loader.save(self.config)
        self._render_config()
        messagebox.showinfo("Config", "Config saved.")

    def apply_json_config(self) -> None:
        if not self.enable_writes.get():
            messagebox.showwarning("Writes Disabled", "Enable writes first.")
            return
        raw = self.settings_box.get("1.0", "end").strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid JSON", str(exc))
            return
        confirm = messagebox.askyesno("Confirm", "Apply JSON config? This overwrites config.json.")
        if not confirm:
            return
        self.config = AppConfig.from_dict(payload)
        self.config_loader.save(self.config)
        self._render_config()
        messagebox.showinfo("Config", "Config applied.")

    def reload_config(self) -> None:
        self.config = self.config_loader.load()
        self._render_config()
        messagebox.showinfo("Config", "Config reloaded.")

    def _build_danger_zone(self) -> None:
        frame = self.tabs["Danger Zone"]
        ttk.Button(frame, text="Wipe Database", command=self.wipe_database).pack(pady=12)
        ttk.Button(frame, text="Reset Cursor Cache", command=self.reset_cursors).pack(pady=12)

    def wipe_database(self) -> None:
        if not self.enable_writes.get():
            messagebox.showwarning("Writes Disabled", "Enable writes first.")
            return
        confirm = messagebox.askyesno("Confirm", "This will wipe the database. Continue?")
        if not confirm:
            return
        self.users_repo.store.save({})
        messagebox.showinfo("Complete", "Database wiped.")

    def reset_cursors(self) -> None:
        if not self.enable_writes.get():
            messagebox.showwarning("Writes Disabled", "Enable writes first.")
            return
        confirm = messagebox.askyesno("Confirm", "Reset all log cursors?")
        if not confirm:
            return
        cursor_path = Path(self.config.paths.cursor_cache_path)
        cursor_path.write_text("{}", encoding="utf-8")
        messagebox.showinfo("Complete", "Cursor cache reset.")

    def _build_user_tools(self) -> None:
        frame = self.tabs["User Tools"]
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=10, pady=10)
        self.user_lookup = StringVar()
        ttk.Label(top, text="Steam64 or Discord ID").pack(side="left")
        ttk.Entry(top, textvariable=self.user_lookup, width=30).pack(side="left", padx=6)
        ttk.Button(top, text="Lookup", command=self.lookup_user).pack(side="left")
        ttk.Button(top, text="Delete", command=self.delete_user).pack(side="left", padx=6)
        self.user_details = Text(frame)
        self.user_details.pack(fill="both", expand=True, padx=10, pady=10)

    def _find_user(self, identifier: str) -> Optional[UserRecord]:
        db = self.users_repo.load()
        if identifier in db.users:
            return db.users[identifier]
        for user in db.users.values():
            if user.discord_id == identifier:
                return user
        return None

    def lookup_user(self) -> None:
        identifier = self.user_lookup.get().strip()
        if not identifier:
            return
        user = self._find_user(identifier)
        self.user_details.delete("1.0", "end")
        if not user:
            self.user_details.insert("end", "User not found.")
            return
        self.user_details.insert("end", json.dumps(user.__dict__, indent=2))

    def delete_user(self) -> None:
        if not self.enable_writes.get():
            messagebox.showwarning("Writes Disabled", "Enable writes first.")
            return
        identifier = self.user_lookup.get().strip()
        if not identifier:
            return
        user = self._find_user(identifier)
        if not user:
            messagebox.showwarning("Not Found", "User not found.")
            return
        confirm = messagebox.askyesno("Confirm", f"Delete user {user.steam_id}?")
        if not confirm:
            return
        db = self.users_repo.load()
        db.users.pop(user.steam_id, None)
        self.users_repo.save(db)
        self.user_details.delete("1.0", "end")
        self.user_details.insert("end", "User deleted.")


def run_gui() -> None:
    root = Tk()
    app = DeathWatcherGUI(root, Path("config.json"))
    root.mainloop()
