import os
import vdf
import requests
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
import zlib
import ctypes
import subprocess
import threading
from PIL import Image, ImageTk
from io import BytesIO

DEFAULT_STEAM_PATH = "C:\\Program Files (x86)\\Steam"
DEFAULT_JSON_URL = "https://raw.githubusercontent.com/v7upSln/Add2Steam/refs/heads/main/data.json"

PREVIEW_SIZES = {
    "grid":     (230, 107),
    "vertical": (140, 210),
    "hero":     (230, 103),
    "logo":     (230, 115),
}

ART_KEYS  = ["grid", "vertical", "hero", "logo"]
JSON_KEYS = {
    "grid":     "wider_screen",
    "vertical": "artwork",
    "hero":     "hero",
    "logo":     "logo",
}


def load_shortcuts(vdf_path):
    if not os.path.exists(vdf_path):
        return {"shortcuts": {}}
    try:
        with open(vdf_path, "rb") as f:
            return vdf.binary_loads(f.read())
    except Exception:
        return {"shortcuts": {}}


def save_shortcuts(vdf_path, shortcuts_dict):
    with open(vdf_path, "wb") as f:
        f.write(vdf.binary_dumps(shortcuts_dict))


class SteamShortcutApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Add2Steam")
        self.root.geometry("900x960")
        self.root.resizable(False, False)

        self.games_data      = {}
        self.preview_images  = {}
        self.preview_labels  = {}
        self._preview_thread = None
        self._preview_cancel = False

        self.json_url_var      = tk.StringVar(value=DEFAULT_JSON_URL)
        self.steam_path_var    = tk.StringVar(value=DEFAULT_STEAM_PATH)
        self.user_id_var       = tk.StringVar()
        self.exe_path_var      = tk.StringVar()
        self.selected_game_var = tk.StringVar()

        self.setup_ui()

        self.log("[*] Application initialized.")
        self.auto_detect_userid()

    def setup_ui(self):
        pad = {"padx": 10, "pady": 5}

        frame_json = tk.LabelFrame(self.root, text="Game Source")
        frame_json.pack(fill="x", padx=12, pady=(10, 4))
        tk.Entry(frame_json, textvariable=self.json_url_var, width=100).pack(side="left", **pad)
        tk.Button(
            frame_json,
            text="Fetch Games",
            command=self.fetch_json,
            bg="#0078D7",
            fg="white",
            relief="raised"
        ).pack(side="right", padx=10, pady=5)

        frame_game = tk.LabelFrame(self.root, text="Game Details")
        frame_game.pack(fill="x", padx=12, pady=4)

        tk.Label(frame_game, text="Select Game").grid(row=0, column=0, **pad)
        self.game_dropdown = ttk.Combobox(
            frame_game, textvariable=self.selected_game_var,
            state="readonly", width=52,
        )
        self.game_dropdown.grid(row=0, column=1, **pad)
        self.game_dropdown.bind("<<ComboboxSelected>>", self.update_preview)

        tk.Label(frame_game, text="Executable").grid(row=1, column=0, **pad)
        tk.Entry(frame_game, textvariable=self.exe_path_var, width=55).grid(row=1, column=1, **pad)
        tk.Button(
            frame_game,
            text="Browse",
            command=self.browse_exe,
            bg="#0078D7",
            fg="white",
            relief="raised"
        ).grid(row=1, column=2, padx=6)

        frame_preview = tk.LabelFrame(self.root, text="Artwork Preview")
        frame_preview.pack(fill="x", padx=12, pady=4)

        art_configs = [
            ("Grid",     "grid",     "Horizontal  460x215"),
            ("Vertical", "vertical", "Portrait  300x450"),
            ("Hero",     "hero",     "Banner  956x430"),
            ("Logo",     "logo",     "Logo / icon"),
        ]

        for col, (display_name, key, hint) in enumerate(art_configs):
            w, h = PREVIEW_SIZES[key]

            tk.Label(frame_preview, text=display_name, font=("TkDefaultFont", 9, "bold")).grid(
                row=0, column=col, padx=8, pady=(8, 2)
            )

            container = tk.Frame(frame_preview, width=w, height=h, relief="sunken", bd=1)
            container.grid(row=1, column=col, padx=8, pady=4)
            container.pack_propagate(False)

            img_lbl = tk.Label(container, text="No Image")
            img_lbl.pack(expand=True)

            tk.Label(frame_preview, text=hint, font=("TkDefaultFont", 7)).grid(
                row=2, column=col, padx=8, pady=(0, 6)
            )

            self.preview_labels[key] = img_lbl

        frame_steam = tk.LabelFrame(self.root, text="Steam Settings")
        frame_steam.pack(fill="x", padx=12, pady=4)

        tk.Label(frame_steam, text="Steam Path").grid(row=0, column=0, **pad)
        tk.Entry(frame_steam, textvariable=self.steam_path_var, width=68).grid(row=0, column=1, **pad)

        tk.Label(frame_steam, text="User ID").grid(row=1, column=0, **pad)
        self.user_dropdown = ttk.Combobox(frame_steam, textvariable=self.user_id_var, width=28)
        self.user_dropdown.grid(row=1, column=1, sticky="w", **pad)
        tk.Button(
            frame_steam,
            text="Auto Detect",
            command=self.auto_detect_userid,
            bg="#0078D7",
            fg="white",
            relief="raised"
        ).grid(row=1, column=2, padx=6)

        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "blue.Horizontal.TProgressbar",
            troughcolor="#e0e0e0",
            bordercolor="#e0e0e0",
            background="#0078D7",
            lightcolor="#4da3ff",
            darkcolor="#005a9e",
        )
        self.progress = ttk.Progressbar(
            self.root,
            style="blue.Horizontal.TProgressbar",
            mode="indeterminate",
            length=876
        )
        self.progress.pack(padx=12, pady=(4, 0))

        self.action_btn = tk.Button(
            self.root,
            text="Add2Steam",
            font=("TkDefaultFont", 11, "bold"),
            bg="#0078D7",
            fg="white",
            activebackground="#106ebe",
            activeforeground="white",
            relief="raised",
            command=self.process_game,
        )
        self.action_btn.pack(fill="x", padx=12, pady=10, ipady=9)

        frame_log = tk.LabelFrame(self.root, text="Log")
        frame_log.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self.log_text = scrolledtext.ScrolledText(
            frame_log, height=9,
            font=("Consolas", 9),
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")
        self.root.update_idletasks()

    def fetch_json(self):
        try:
            url = self.json_url_var.get().strip()
            self.log(f"[*] Fetching game list from {url} ...")
            self.progress.start(12)

            r = requests.get(url, timeout=10)
            r.raise_for_status()

            self.games_data = r.json()
            names = list(self.games_data.keys())
            self.game_dropdown["values"] = names

            if names:
                self.game_dropdown.current(0)
                self.update_preview()

            self.log(f"[+] Loaded {len(names)} games.")
        except Exception as e:
            self.log(f"[x] JSON fetch failed: {e}")
            messagebox.showerror("Network Error", f"Failed to fetch games data:\n{e}")
        finally:
            self.progress.stop()

    def update_preview(self, event=None):
        game = self.selected_game_var.get()
        if game not in self.games_data:
            return

        self._preview_cancel = True
        if self._preview_thread and self._preview_thread.is_alive():
            self._preview_thread.join(timeout=0.1)

        for key, lbl in self.preview_labels.items():
            lbl.config(image="", text="Loading...")
            self.preview_images.pop(key, None)

        self._preview_cancel = False
        self._preview_thread = threading.Thread(
            target=self._load_previews_thread,
            args=(game,),
            daemon=True,
        )
        self._preview_thread.start()

    def _load_previews_thread(self, game):
        art = self.games_data.get(game, {})

        for key in ART_KEYS:
            if self._preview_cancel:
                return

            json_key = JSON_KEYS[key]
            url      = art.get(json_key)
            if url: url = url.strip()
            lbl      = self.preview_labels[key]
            w, h     = PREVIEW_SIZES[key]

            if not url:
                self.root.after(0, lambda l=lbl: l.config(image="", text="Missing"))
                continue

            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()

                img = Image.open(BytesIO(r.content)).convert("RGBA")
                img.thumbnail((w, h), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)

                def _apply(l=lbl, p=photo, k=key):
                    self.preview_images[k] = p
                    l.config(image=p, text="")

                self.root.after(0, _apply)

            except Exception as e:
                self.root.after(0, lambda l=lbl: l.config(image="", text="Error"))
                self.log(f"[!] Preview failed ({json_key}): {e}")

    def browse_exe(self):
        path = filedialog.askopenfilename(filetypes=[("Executable Files", "*.exe")])
        if path:
            self.exe_path_var.set(os.path.normpath(path))
            self.log(f"[*] Executable: {path}")

    def auto_detect_userid(self):
        base = os.path.join(self.steam_path_var.get(), "userdata")
        if not os.path.exists(base):
            self.log("[x] Steam userdata folder not found. Check your Steam path.")
            return

        ids = [d for d in os.listdir(base) if d.isdigit() and d != "0"]

        if ids:
            self.user_dropdown["values"] = ids
            self.user_dropdown.current(0)
            self.log(f"[*] Found {len(ids)} User ID(s).")
        else:
            self.log("[!] No valid User IDs found.")

    def restart_steam(self, steam_path):
        steam_exe = os.path.join(steam_path, "steam.exe")
        try:
            self.log("[*] Closing Steam...")
            subprocess.run(
                ["taskkill", "/f", "/im", "steam.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            subprocess.run(
                ["taskkill", "/f", "/im", "steamwebhelper.exe"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.log("[*] Waiting for Steam to close...")
            import time
            time.sleep(3)
            self.log("[*] Restarting Steam...")
            subprocess.Popen([steam_exe])
            self.log("[+] Steam restarted successfully.")
        except Exception as e:
            self.log(f"[!] Steam restart failed: {e}")

    def clear_cache(self, steam_path, uid):
        cache = os.path.join(steam_path, "userdata", uid, "config", "librarycache")
        if not os.path.exists(cache):
            self.log("[*] Library cache folder not found — skipping.")
            return
        removed = 0
        for f in os.listdir(cache):
            if f.endswith(".json"):
                try:
                    os.remove(os.path.join(cache, f))
                    removed += 1
                except Exception:
                    pass
        self.log(f"[*] Cleared {removed} cache file(s).")

    def process_game(self):
        if self.action_btn["state"] == "disabled":
            return

        name  = self.selected_game_var.get()
        exe   = self.exe_path_var.get()
        steam = self.steam_path_var.get()
        uid   = self.user_id_var.get()

        if not name:
            messagebox.showerror("Error", "Please select a game first.")
            return
        if not os.path.exists(os.path.join(steam, "steam.exe")):
            self.log("[x] Invalid Steam path.")
            messagebox.showerror("Error", "Invalid Steam path. Check settings.")
            return
        if not os.path.exists(exe):
            self.log("[x] Executable not found.")
            messagebox.showerror("Error", "Executable not found. Please browse for the .exe file.")
            return
        if not uid:
            messagebox.showerror("Error", "User ID is empty. Please detect or enter it manually.")
            return

        self.action_btn.config(state="disabled")

        self.log("-" * 60)
        self.log(f"[*] Processing: {name}")

        self.progress.start(8)

        threading.Thread(
            target=self._process_thread,
            args=(name, exe, steam, uid),
            daemon=True
        ).start()

    def _process_thread(self, name, exe, steam, uid):
        try:
            self._do_process(name, exe, steam, uid)
        finally:
            self.root.after(0, self._process_done)

    def _process_done(self):
        self.progress.stop()
        self.action_btn.config(state="normal")

    def _do_process(self, name, exe, steam, uid):
        vdf_path = os.path.join(steam, "userdata", uid, "config", "shortcuts.vdf")
        grid_dir = os.path.join(steam, "userdata", uid, "config", "grid")

        try:
            os.makedirs(grid_dir, exist_ok=True)
        except Exception as e:
            self.log(f"[x] Could not create grid directory: {e}")
            return

        shortcuts = load_shortcuts(vdf_path)
        data      = shortcuts.get("shortcuts", {})
        exe_q     = f'"{exe}"'

        for v in data.values():
            if v.get("Exe") == exe_q:
                self.log("[*] Game already in shortcuts.vdf — skipping entry creation.")
                break
        else:
            crc   = zlib.crc32(f"{exe}{name}".encode())
            appid = ctypes.c_int32(crc | 0x80000000).value
            index = str(len(data))
            data[index] = {
                "appid":              appid,
                "AppName":            name,
                "Exe":                exe_q,
                "StartDir":           f'"{os.path.dirname(exe)}"',
                "icon":               "",
                "ShortcutPath":       "",
                "LaunchOptions":      "",
                "IsHidden":           0,
                "AllowDesktopConfig": 1,
                "AllowOverlay":       1,
                "OpenVR":             0,
                "Devkit":             0,
                "DevkitGameID":       "",
                "LastPlayTime":       0,
                "tags":               {},
            }
            shortcuts["shortcuts"] = data
            try:
                save_shortcuts(vdf_path, shortcuts)
                self.log(f"[+] Shortcut added to VDF (AppID {appid})")
            except Exception as e:
                self.log(f"[x] Failed writing shortcuts.vdf: {e}")
                return

        crc            = zlib.crc32(f"{exe}{name}".encode())
        appid          = ctypes.c_int32(crc | 0x80000000).value
        unsigned_appid = ctypes.c_uint32(appid).value

        art     = self.games_data.get(name, {})
        art_map = [
            ("wider_screen", f"{unsigned_appid}.png",      "Grid"),
            ("artwork",      f"{unsigned_appid}p.png",     "Vertical"),
            ("hero",         f"{unsigned_appid}_hero.png", "Hero"),
            ("logo",         f"{unsigned_appid}_logo.png", "Logo"),
        ]

        self.log("[*] Downloading artwork ...")
        for key, filename, desc in art_map:
            url = art.get(key)
            if not url:
                self.log(f"[!] No URL for {desc} — skipped.")
                continue
            url = url.strip()
            try:
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                path = os.path.join(grid_dir, filename)
                with open(path, "wb") as f:
                    f.write(r.content)
                size = os.path.getsize(path)
                if size < 5000:
                    self.log(f"[!] {desc} saved but suspiciously small ({size} B).")
                else:
                    self.log(f"[+] {desc} saved ({size // 1024} KB).")
            except Exception as e:
                self.log(f"[x] {desc} download failed: {e}")

        self.clear_cache(steam, uid)
        self.restart_steam(steam)

        self.log("[+] Done. Steam has been restarted.")
        messagebox.showinfo("Done", f"'{name}' added successfully.\n\nRestart Steam to see the new artwork.")


if __name__ == "__main__":
    root = tk.Tk()
    app  = SteamShortcutApp(root)
    root.mainloop()