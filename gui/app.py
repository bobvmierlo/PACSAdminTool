"""
PACS Admin Tool - GUI
Clean, neutral, professional interface for PACS administrators.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import logging
import os
import sys
import socket
import csv
import webbrowser
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.manager import load_config, save_config
from hl7_templates import load_templates as _load_hl7_templates
from locales import t, set_language, current_language, available_languages

logger = logging.getLogger(__name__)

_APP_VERSION = "1.0"


def _setup_client_logging():
    """
    Add a daily-rotating log file handler for the desktop client.

    Uses logs/pacs_admin_client.log so it is separate from the web server's
    pacs_admin.log and both can run simultaneously without interleaving.
    The filename starts with 'pacs_admin' so the web server's existing
    cleanup pattern ('pacs_admin*.log*') covers client logs too.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir  = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    # Don't add a second file handler if one already exists (e.g. running
    # the web server and the GUI in the same process — unlikely but safe).
    if any(isinstance(h, TimedRotatingFileHandler) for h in root.handlers):
        return

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(name)-25s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = TimedRotatingFileHandler(
        os.path.join(log_dir, "pacs_admin_client.log"),
        when="midnight", utc=True, backupCount=7, encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    if root.level == logging.WARNING or root.level == 0:
        root.setLevel(logging.INFO)
    root.addHandler(fh)
    logging.getLogger(__name__).info("Client log file opened: %s",
                                     os.path.join(log_dir, "pacs_admin_client.log"))

FONT      = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_MONO = ("Consolas", 9)
FONT_H1   = ("Segoe UI", 11, "bold")


def _style_setup(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    BG = "#f5f5f5"; CARD = "#ffffff"; BORDER = "#d0d0d0"
    FG = "#1a1a1a"; FG2 = "#555555"; ACC = "#2b6cb0"
    style.configure(".", background=BG, foreground=FG, fieldbackground=CARD,
        selectbackground=ACC, selectforeground="white", font=FONT, relief="flat", borderwidth=0)
    style.configure("TNotebook", background=BG, tabmargins=[0,0,0,0])
    style.configure("TNotebook.Tab", background="#e8e8e8", foreground=FG2, padding=[16,7], font=FONT)
    style.map("TNotebook.Tab", background=[("selected", CARD), ("active","#efefef")], foreground=[("selected",ACC)])
    style.configure("TFrame", background=BG)
    style.configure("TLabelframe", background=CARD, bordercolor=BORDER, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=CARD, foreground=FG, font=FONT_BOLD)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("Card.TLabel", background=CARD, foreground=FG)
    style.configure("Dim.TLabel", background=BG, foreground=FG2)
    style.configure("H1.TLabel", background=BG, foreground=FG, font=FONT_H1)
    style.configure("TEntry", fieldbackground=CARD, foreground=FG, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure("TCombobox", fieldbackground=CARD, foreground=FG)
    style.configure("Treeview", background=CARD, foreground=FG, fieldbackground=CARD, rowheight=22, borderwidth=0)
    style.configure("Treeview.Heading", background="#eeeeee", foreground=FG2, font=FONT_BOLD, relief="flat", borderwidth=0)
    style.map("Treeview", background=[("selected","#dbeafe")], foreground=[("selected","#1e3a5f")])
    style.configure("TScrollbar", background="#e0e0e0", troughcolor=BG, arrowcolor=FG2, gripcount=0)
    style.configure("TCheckbutton", background=BG, foreground=FG)
    style.configure("TSeparator", background=BORDER)
    style.configure("TButton", background="#e8e8e8", foreground=FG, font=FONT, padding=[10,4], relief="flat", borderwidth=1, bordercolor=BORDER)
    style.map("TButton", background=[("active","#dcdcdc"),("pressed","#d0d0d0")])
    style.configure("Primary.TButton", background=ACC, foreground="white", font=FONT_BOLD, padding=[12,4])
    style.map("Primary.TButton", background=[("active","#245a99"),("pressed","#1d4f8a")])
    style.configure("Danger.TButton", background="#dc2626", foreground="white", font=FONT_BOLD, padding=[10,4])
    style.map("Danger.TButton", background=[("active","#b91c1c")])
    style.configure("Success.TButton", background="#16a34a", foreground="white", font=FONT_BOLD, padding=[10,4])
    style.map("Success.TButton", background=[("active","#15803d")])


def _btn(parent, text, command, style="TButton", **kw):
    return ttk.Button(parent, text=text, command=command, style=style, **kw)

def _entry(parent, width=20, **kw):
    return ttk.Entry(parent, width=width, **kw)

def _label(parent, text, style="TLabel", **kw):
    return ttk.Label(parent, text=text, style=style, **kw)

def _sep(parent, orient="horizontal"):
    return ttk.Separator(parent, orient=orient)

def _lf(parent, text):
    return ttk.LabelFrame(parent, text=text, padding=8)


class LogBox(tk.Text):
    MAX_LINES = 2000
    def __init__(self, parent, **kw):
        super().__init__(parent, bg="white", fg="#1a1a1a", insertbackground="#2b6cb0",
            font=FONT_MONO, relief="solid", bd=1, state="disabled", wrap="word", **kw)
        self.tag_configure("ok",   foreground="#15803d")
        self.tag_configure("err",  foreground="#dc2626")
        self.tag_configure("warn", foreground="#b45309")
        self.tag_configure("info", foreground="#2b6cb0")
        self.tag_configure("dim",  foreground="#888888")

    def _tag_for(self, msg):
        lo = msg.lower()
        if any(w in lo for w in ("error","fail","refused","reject","exception","abort")): return "err"
        if any(w in lo for w in ("warn","timeout")): return "warn"
        if any(w in lo for w in ("success","complete","stored","0x0000","received","sent","ok","started","listening","connected","accepted")): return "ok"
        return "dim"

    def append(self, msg, tag=None):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        tag = tag or self._tag_for(msg)
        self.configure(state="normal")
        self.insert("end", line, tag)
        lines = int(self.index("end-1c").split(".")[0])
        if lines > self.MAX_LINES:
            self.delete("1.0", f"{lines - self.MAX_LINES}.0")
        self.see("end")
        self.configure(state="disabled")

    def clear(self):
        self.configure(state="normal"); self.delete("1.0","end"); self.configure(state="disabled")


def _log_frame(parent, height=5, label=None):
    if label is None:
        label = t("common.log")
    lf = _lf(parent, label)
    box = LogBox(lf, height=height)
    sb = ttk.Scrollbar(lf, orient="vertical", command=box.yview)
    box.configure(yscrollcommand=sb.set)
    box.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return lf, box


class AESelector(ttk.LabelFrame):
    def __init__(self, parent, config, label=None, **kw):
        if label is None:
            label = t("common.remote_ae")
        super().__init__(parent, text=label, padding=8, **kw)
        self.config = config
        top = ttk.Frame(self); top.pack(fill="x", pady=(0,6))
        _label(top, t("common.preset"), style="Card.TLabel").pack(side="left")
        self.preset_var = tk.StringVar(value=t("common.manual"))
        self.preset_cb = ttk.Combobox(top, textvariable=self.preset_var, width=28, state="readonly")
        self.preset_cb.pack(side="left", padx=(4,6))
        self.preset_cb.bind("<<ComboboxSelected>>", self._load_preset)
        _btn(top, t("common.refresh"), self.refresh_presets).pack(side="left")
        bot = ttk.Frame(self); bot.pack(fill="x")
        for col, (lbl, attr, val, w) in enumerate([
            (t("common.ae_title"), "ae_var", "REMOTE_AE", 14),
            (t("common.host"), "host_var", "127.0.0.1", 22),
            (t("common.port"), "port_var", "104", 6),
        ]):
            _label(bot, lbl, style="Card.TLabel").grid(row=0, column=col*2, sticky="w", padx=(16 if col else 0, 4))
            var = tk.StringVar(value=val); setattr(self, attr, var)
            _entry(bot, textvariable=var, width=w).grid(row=0, column=col*2+1, padx=(0,4))
        self.refresh_presets()

    def refresh_presets(self):
        self.preset_cb["values"] = [t("common.manual")] + [ae["name"] for ae in self.config.get("remote_aes", [])]

    def _load_preset(self, _=None):
        name = self.preset_var.get()
        for ae in self.config.get("remote_aes", []):
            if ae["name"] == name:
                self.ae_var.set(ae.get("ae_title","")); self.host_var.set(ae.get("host",""))
                self.port_var.set(str(ae.get("port",104))); return

    def get(self):
        return {"ae_title": self.ae_var.get().strip(), "host": self.host_var.get().strip(),
                "port": int(self.port_var.get().strip() or "104")}


def _show_dicom_detail(parent_win, dataset, title=None):
    if title is None:
        title = t("dicom_detail.title")
    win = tk.Toplevel(parent_win); win.title(title); win.geometry("860x580")
    win.configure(bg="#f5f5f5"); win.grab_set()
    sf = ttk.Frame(win); sf.pack(fill="x", padx=10, pady=(10,4))
    _label(sf, t("common.filter")).pack(side="left")
    search_var = tk.StringVar()
    _entry(sf, textvariable=search_var, width=36).pack(side="left", padx=(6,0))
    _label(sf, "  " + t("common.filter_hint"), style="Dim.TLabel").pack(side="left")
    cols = ("Tag","Keyword","VR","Value")
    frame = ttk.Frame(win); frame.pack(fill="both", expand=True, padx=10, pady=4)
    tree = ttk.Treeview(frame, columns=cols, show="headings")
    sb_v = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    sb_h = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
    for c, w in zip(cols, [95,250,42,440]):
        tree.heading(c, text=c); tree.column(c, width=w, minwidth=30)
    tree.grid(row=0, column=0, sticky="nsew"); sb_v.grid(row=0,column=1,sticky="ns")
    sb_h.grid(row=1,column=0,sticky="ew"); frame.rowconfigure(0,weight=1); frame.columnconfigure(0,weight=1)
    all_rows = []
    def _collect(ds, prefix=""):
        for elem in ds:
            tag_str = f"({elem.tag.group:04X},{elem.tag.element:04X})"
            keyword = (prefix + elem.keyword) if elem.keyword else prefix + tag_str
            vr = elem.VR or ""
            try:
                if elem.VR == "SQ":
                    all_rows.append((tag_str, keyword, vr, f"<Sequence: {len(elem.value)} item(s)>"))
                    for i, item in enumerate(elem.value): _collect(item, prefix=f"  [{i}] ")
                elif elem.VR in ("OB","OW","OF","OD","OL","UN"):
                    all_rows.append((tag_str, keyword, vr, f"<Binary: {len(elem.value)} bytes>"))
                else:
                    all_rows.append((tag_str, keyword, vr, str(elem.value)))
            except Exception:
                all_rows.append((tag_str, keyword, vr, "<unreadable>"))
    try: _collect(dataset)
    except Exception as e: all_rows.append(("","ERROR","",str(e)))
    def _refresh(ft=""):
        tree.delete(*tree.get_children()); ftl = ft.lower()
        for row in all_rows:
            if not ftl or any(ftl in str(c).lower() for c in row): tree.insert("","end",values=row)
    _refresh()
    search_var.trace_add("write", lambda *_: _refresh(search_var.get()))
    bot = ttk.Frame(win); bot.pack(fill="x", padx=10, pady=(0,10))
    _label(bot, t("common.tags_returned", n=len(all_rows)), style="Dim.TLabel").pack(side="left")
    _btn(bot, t("common.close"), win.destroy).pack(side="right"); win.focus_set()


class CFindTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._datasets = []; self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=10, pady=8)
        self.ae_sel = AESelector(top, self.app.config, t("cfind.query_scp")); self.ae_sel.pack(fill="x")
        qf = _lf(top, t("cfind.query_params")); qf.pack(fill="x", pady=(8,0))
        gf = ttk.Frame(qf); gf.pack(fill="x")
        for i, (lbl, attr) in enumerate([(t("cfind.patient_id"),"pid_var"),(t("cfind.patient_name"),"pname_var"),(t("cfind.accession"),"acc_var"),(t("cfind.study_date"),"date_var"),(t("cfind.modality"),"mod_var"),(t("cfind.study_uid"),"suid_var")]):
            r, c = divmod(i,3)
            fr = ttk.Frame(gf); fr.grid(row=r, column=c, sticky="w", padx=8, pady=3)
            _label(fr,lbl).pack(side="left")
            var = tk.StringVar(); setattr(self,attr,var)
            _entry(fr,textvariable=var,width=18).pack(side="left",padx=4)
        ctrl = ttk.Frame(top); ctrl.pack(fill="x", pady=(8,0))
        _label(ctrl,t("cfind.query_level")).pack(side="left")
        self.level_var = tk.StringVar(value="STUDY")
        self._level_cb = ttk.Combobox(ctrl,textvariable=self.level_var,values=["PATIENT","STUDY","SERIES","IMAGE"],state="readonly",width=10)
        self._level_cb.pack(side="left",padx=(4,12))
        self._level_cb.bind("<<ComboboxSelected>>", self._on_level_change)
        _label(ctrl,t("cfind.model")).pack(side="left")
        self.model_var = tk.StringVar(value="STUDY")
        self._model_cb = ttk.Combobox(ctrl,textvariable=self.model_var,values=["STUDY","PATIENT"],state="readonly",width=10)
        self._model_cb.pack(side="left",padx=4)
        self._model_cb.bind("<<ComboboxSelected>>", self._on_model_change)
        _sep(ctrl,"vertical").pack(side="left",fill="y",padx=12,pady=2)
        _btn(ctrl,t("cfind.cecho"),self._do_cecho).pack(side="left",padx=2)
        _btn(ctrl,t("cfind.run"),self._do_cfind,style="Primary.TButton").pack(side="left",padx=4)
        _btn(ctrl,t("cfind.export_csv"),self._export_csv).pack(side="left",padx=4)
        self.count_lbl = _label(ctrl,"",style="Dim.TLabel"); self.count_lbl.pack(side="left",padx=12)
        mf = ttk.Frame(top); mf.pack(fill="x", pady=(6,0))
        _label(mf,t("cfind.cmove_dest")).pack(side="left")
        self.move_dest_var = tk.StringVar(value=self.app.config.get("local_ae",{}).get("ae_title","PACSADMIN"))
        _entry(mf,textvariable=self.move_dest_var,width=16).pack(side="left",padx=4)
        _btn(mf,t("cfind.cmove_btn"),self._do_cmove,style="Success.TButton").pack(side="left",padx=4)
        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=(0,6))
        rf = _lf(pw,t("cfind.results"))
        cols = ("PatientID","PatientName","StudyDate","Modality","Accession","Description","StudyUID")
        self.tree = ttk.Treeview(rf,columns=cols,show="headings",height=12)
        for c, w in zip(cols,[110,150,90,80,120,200,300]):
            self.tree.heading(c,text=c); self.tree.column(c,width=w,minwidth=40)
        sb = ttk.Scrollbar(rf,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        self.tree.bind("<Double-1>",self._show_detail)
        pw.add(rf, weight=3)
        lf2, self.log = _log_frame(pw, height=5)
        pw.add(lf2, weight=1)

    def _show_detail(self,_=None):
        sel = self.tree.selection()
        if not sel: return
        idx = self.tree.index(sel[0])
        if idx < len(self._datasets):
            _show_dicom_detail(self,self._datasets[idx],title=t("cfind.detail_title"))

    def _do_cecho(self):
        ae = self.ae_sel.get(); local = self.app.local_ae
        self.log.append(f"C-ECHO -> {ae['ae_title']}@{ae['host']}:{ae['port']}")
        def run():
            try:
                from dicom.operations import c_echo
                ok, msg = c_echo(local, ae["host"], ae["port"], ae["ae_title"]); self.log.append(msg)
            except Exception as e: self.log.append(f"Error: {e}", "err")
        threading.Thread(target=run, daemon=True).start()

    def _on_model_change(self, _=None):
        """
        Study Root model (STUDY) does not support PATIENT query level.
        When the user selects STUDY model with PATIENT level, auto-correct
        the level to STUDY and warn in the activity log.
        """
        if self.model_var.get() == "STUDY" and self.level_var.get() == "PATIENT":
            self.level_var.set("STUDY")
            self.log.append(t("cfind.warn_study_root"), "warn")

    def _on_level_change(self, _=None):
        """
        PATIENT query level is only valid with the Patient Root model.
        When the user picks PATIENT level with STUDY model, auto-switch
        the model to PATIENT and warn in the activity log.
        """
        if self.level_var.get() == "PATIENT" and self.model_var.get() == "STUDY":
            self.model_var.set("PATIENT")
            self.log.append(t("cfind.warn_patient_level"), "warn")

    def _build_query_ds(self):
        try: from pydicom.dataset import Dataset
        except ImportError: return None
        ds = Dataset()
        ds.QueryRetrieveLevel = self.level_var.get()
        ds.PatientID = self.pid_var.get(); ds.PatientName = self.pname_var.get()
        ds.AccessionNumber = self.acc_var.get(); ds.StudyDate = self.date_var.get()
        ds.ModalitiesInStudy = self.mod_var.get(); ds.StudyInstanceUID = self.suid_var.get()
        ds.StudyDescription = ""; ds.StudyTime = ""; ds.NumberOfStudyRelatedInstances = ""
        return ds

    def _do_cfind(self):
        ae = self.ae_sel.get(); local = self.app.local_ae
        ds = self._build_query_ds()
        if ds is None: self.log.append(t("cfind.pydicom_missing"),"err"); return
        self.tree.delete(*self.tree.get_children()); self._datasets.clear()
        self.count_lbl.configure(text="")
        self.log.append(f"C-FIND -> {ae['ae_title']}@{ae['host']}:{ae['port']}")
        def run():
            try:
                from dicom.operations import c_find
                ok, results, msg = c_find(local, ae["host"], ae["port"], ae["ae_title"], ds, self.model_var.get())
                self.log.append(msg)
                for r in results:
                    self._datasets.append(r)
                    self.tree.insert("","end",values=(
                        str(getattr(r,"PatientID","")), str(getattr(r,"PatientName","")),
                        str(getattr(r,"StudyDate","")), str(getattr(r,"ModalitiesInStudy","")),
                        str(getattr(r,"AccessionNumber","")), str(getattr(r,"StudyDescription","")),
                        str(getattr(r,"StudyInstanceUID",""))))
                self.count_lbl.configure(text=t("cfind.results_count", n=len(results)))
            except Exception as e: self.log.append(f"Error: {e}","err")
        threading.Thread(target=run, daemon=True).start()

    def _export_csv(self):
        if not self._datasets: messagebox.showinfo(t("cfind.export_csv"),t("cfind.no_results")); return
        path = filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if not path: return
        with open(path,"w",newline="",encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["PatientID","PatientName","StudyDate","Modality","Accession","Description","StudyUID"])
            for item in self.tree.get_children(): w.writerow(self.tree.item(item)["values"])
        self.log.append(f"Exported to {path}")

    def _do_cmove(self):
        sel = self.tree.selection()
        if not sel: messagebox.showwarning("C-MOVE","Select a result row first."); return
        ae = self.ae_sel.get(); local = self.app.local_ae
        dest = self.move_dest_var.get().strip()
        idx = self.tree.index(sel[0]); src = self._datasets[idx]
        try: from pydicom.dataset import Dataset
        except ImportError: self.log.append(t("cfind.pydicom_missing"),"err"); return
        move_ds = Dataset(); move_ds.QueryRetrieveLevel = "STUDY"
        move_ds.StudyInstanceUID = getattr(src,"StudyInstanceUID","")
        self.log.append(f"C-MOVE -> dest={dest}  study={move_ds.StudyInstanceUID}")
        def run():
            try:
                from dicom.operations import c_move
                ok, msg = c_move(local, ae["host"], ae["port"], ae["ae_title"], move_ds, dest, self.model_var.get(), callback=lambda m: self.log.append(m))
                self.log.append(msg)
            except Exception as e: self.log.append(f"Error: {e}","err")
        threading.Thread(target=run, daemon=True).start()


class CStoreTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._files = []; self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=10, pady=8)
        self.ae_sel = AESelector(top, self.app.config, t("cstore.storage_scp")); self.ae_sel.pack(fill="x")
        ctrl = ttk.Frame(self); ctrl.pack(fill="x", padx=10, pady=6)
        _btn(ctrl,t("cstore.add_files"),self._add_files).pack(side="left",padx=2)
        _btn(ctrl,t("cstore.add_folder"),self._add_folder).pack(side="left",padx=2)
        _btn(ctrl,t("cstore.clear_list"),self._clear).pack(side="left",padx=2)
        self.count_lbl = _label(ctrl,t("cstore.files_queued", n=0),style="Dim.TLabel"); self.count_lbl.pack(side="left",padx=12)
        _btn(ctrl,t("cstore.send_all"),self._do_cstore,style="Primary.TButton").pack(side="right",padx=2)
        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=(0,6))
        lf = _lf(pw,t("cstore.files_to_send"))
        self.listbox = tk.Listbox(lf,bg="white",fg="#1a1a1a",selectbackground="#dbeafe",selectforeground="#1e3a5f",font=FONT_MONO,bd=1,relief="solid",activestyle="none")
        sb = ttk.Scrollbar(lf,orient="vertical",command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        pw.add(lf, weight=3)
        lf2, self.log = _log_frame(pw, height=7)
        pw.add(lf2, weight=1)

    def _add_files(self):
        files = filedialog.askopenfilenames(title=t("cstore.select_dicom"),filetypes=[("DICOM","*.dcm *.DCM"),("All","*.*")])
        for f in files:
            if f not in self._files: self._files.append(f); self.listbox.insert("end",f)
        self.count_lbl.configure(text=t("cstore.files_queued", n=len(self._files)))

    def _add_folder(self):
        folder = filedialog.askdirectory(title=t("cstore.select_folder"))
        if not folder: return
        for root_dir, _, files in os.walk(folder):
            for f in files:
                path = os.path.join(root_dir,f)
                if path not in self._files: self._files.append(path); self.listbox.insert("end",path)
        self.count_lbl.configure(text=t("cstore.files_queued", n=len(self._files)))

    def _clear(self):
        self._files.clear(); self.listbox.delete(0,"end"); self.count_lbl.configure(text=t("cstore.files_queued", n=0))

    def _do_cstore(self):
        if not self._files: messagebox.showwarning("C-STORE",t("cstore.no_files")); return
        ae = self.ae_sel.get(); local = self.app.local_ae; files = list(self._files)
        self.log.append(f"C-STORE {len(files)} file(s) -> {ae['ae_title']}@{ae['host']}:{ae['port']}")
        def run():
            try:
                from dicom.operations import c_store
                ok, msg = c_store(local,ae["host"],ae["port"],ae["ae_title"],files,callback=lambda m: self.log.append(m))
                self.log.append(msg)
            except Exception as e: self.log.append(f"Error: {e}","err")
        threading.Thread(target=run, daemon=True).start()


class DMWLTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._datasets = []; self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=10, pady=8)
        self.ae_sel = AESelector(top, self.app.config, t("dmwl.worklist_scp")); self.ae_sel.pack(fill="x")
        qf = _lf(top,t("dmwl.query_filters")); qf.pack(fill="x",pady=(8,0))
        qf_grid = ttk.Frame(qf); qf_grid.pack(fill="x")
        for i, (lbl,attr) in enumerate([(t("dmwl.patient_id"),"pid_var"),(t("dmwl.patient_name"),"pname_var"),(t("dmwl.sched_date"),"date_var"),(t("dmwl.modality"),"mod_var"),(t("dmwl.accession"),"acc_var"),(t("dmwl.station_aet"),"aet_var")]):
            r, c = divmod(i,3)
            fr = ttk.Frame(qf_grid); fr.grid(row=r,column=c,sticky="w",padx=8,pady=3)
            _label(fr,lbl).pack(side="left")
            var = tk.StringVar(); setattr(self,attr,var)
            _entry(fr,textvariable=var,width=18).pack(side="left",padx=4)
        ctrl = ttk.Frame(top); ctrl.pack(fill="x",pady=(8,0))
        _btn(ctrl,t("dmwl.query"),self._do_dmwl,style="Primary.TButton").pack(side="left",padx=2)
        _btn(ctrl,t("dmwl.export_csv"),self._export_csv).pack(side="left",padx=4)
        self.count_lbl = _label(ctrl,"",style="Dim.TLabel"); self.count_lbl.pack(side="left",padx=12)
        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=(0,6))
        rf = _lf(pw,t("dmwl.results"))
        cols = ("PatientID","PatientName","Accession","Modality","ScheduledDate","StationAET","Procedure")
        self.tree = ttk.Treeview(rf,columns=cols,show="headings",height=12)
        for c, w in zip(cols,[100,150,120,75,110,120,200]):
            self.tree.heading(c,text=c); self.tree.column(c,width=w,minwidth=40)
        sb = ttk.Scrollbar(rf,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        self.tree.bind("<Double-1>",self._show_detail)
        pw.add(rf, weight=3)
        lf2, self.log = _log_frame(pw, height=4)
        pw.add(lf2, weight=1)

    def _show_detail(self,_=None):
        sel = self.tree.selection()
        if not sel: return
        idx = self.tree.index(sel[0])
        if idx >= len(self._datasets): return
        ds = self._datasets[idx]; pid = getattr(ds,"PatientID",""); pname = str(getattr(ds,"PatientName",""))
        _show_dicom_detail(self,ds,title=t("dmwl.detail_title", pname=pname, pid=pid))

    def _build_mwl_ds(self):
        try: from pydicom.dataset import Dataset; from pydicom.sequence import Sequence
        except ImportError: return None
        ds = Dataset()
        ds.PatientID = self.pid_var.get(); ds.PatientName = self.pname_var.get()
        ds.AccessionNumber = self.acc_var.get()
        ds.RequestedProcedureID = ""; ds.RequestedProcedureDescription = ""; ds.StudyInstanceUID = ""
        sps = Dataset()
        sps.Modality = self.mod_var.get().strip()
        sps.ScheduledStationAETitle = self.aet_var.get().strip()
        sps.ScheduledProcedureStepStartDate = self.date_var.get().strip()
        sps.ScheduledProcedureStepStartTime = ""
        sps.ScheduledProcedureStepDescription = ""
        sps.ScheduledPerformingPhysicianName = ""
        sps.ScheduledProcedureStepStatus = ""
        sps.ScheduledProcedureStepID = ""
        ds.ScheduledProcedureStepSequence = Sequence([sps])
        return ds

    def _do_dmwl(self):
        ae = self.ae_sel.get(); local = self.app.local_ae
        ds = self._build_mwl_ds()
        if ds is None: self.log.append(t("cfind.pydicom_missing"),"err"); return
        self.tree.delete(*self.tree.get_children()); self._datasets.clear()
        self.log.append(f"DMWL query -> {ae['ae_title']}@{ae['host']}:{ae['port']}")
        def run():
            try:
                from dicom.operations import dmwl_find
                station_aet = self.aet_var.get().strip()
                calling_ae = station_aet if station_aet else local
                ok, results, msg = dmwl_find(calling_ae, ae["host"], ae["port"], ae["ae_title"], ds, log_callback=lambda m: self.log.append(m))
                self.log.append(msg); self.count_lbl.configure(text=t("dmwl.items_returned", n=len(results)))
                for r in results:
                    self._datasets.append(r)
                    sps_seq = getattr(r,"ScheduledProcedureStepSequence",[])
                    sps = sps_seq[0] if sps_seq else None
                    self.tree.insert("","end",values=(
                        str(getattr(r,"PatientID","")), str(getattr(r,"PatientName","")),
                        str(getattr(r,"AccessionNumber","")),
                        str(getattr(sps,"Modality","")) if sps else "",
                        str(getattr(sps,"ScheduledProcedureStepStartDate","")) if sps else "",
                        str(getattr(sps,"ScheduledStationAETitle","")) if sps else "",
                        str(getattr(r,"RequestedProcedureDescription",""))))
            except Exception as e: self.log.append(f"Error: {e}","err")
        threading.Thread(target=run, daemon=True).start()

    def _export_csv(self):
        if not self._datasets: messagebox.showinfo(t("dmwl.export"),t("dmwl.no_results")); return
        path = filedialog.asksaveasfilename(defaultextension=".csv",filetypes=[("CSV","*.csv")])
        if not path: return
        with open(path,"w",newline="",encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["PatientID","PatientName","Accession","Modality","ScheduledDate","StationAET","Procedure"])
            for item in self.tree.get_children(): w.writerow(self.tree.item(item)["values"])
        self.log.append(f"Exported to {path}")


class StorageCommitTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._uids = []; self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x",padx=10,pady=8)
        self.ae_sel = AESelector(top,self.app.config,t("commit.commit_scp")); self.ae_sel.pack(fill="x")
        ctrl = ttk.Frame(self); ctrl.pack(fill="x",padx=10,pady=6)
        _btn(ctrl,t("commit.load_uids"),self._load_from_files).pack(side="left",padx=2)
        _btn(ctrl,t("common.clear"),self._clear_uids).pack(side="left",padx=4)
        self.uid_count = _label(ctrl,t("commit.uid_count", n=0),style="Dim.TLabel"); self.uid_count.pack(side="left",padx=12)
        _btn(ctrl,t("commit.send"),self._do_commit,style="Primary.TButton").pack(side="right",padx=2)
        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=(0,6))
        lf = _lf(pw,t("commit.sop_uids"))
        self.listbox = tk.Listbox(lf,bg="white",fg="#1a1a1a",selectbackground="#dbeafe",selectforeground="#1e3a5f",font=FONT_MONO,bd=1,relief="solid",activestyle="none")
        sb = ttk.Scrollbar(lf,orient="vertical",command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        pw.add(lf, weight=3)
        lf2, self.log = _log_frame(pw, height=7)
        pw.add(lf2, weight=1)

    def _load_from_files(self):
        files = filedialog.askopenfilenames(title=t("cstore.select_dicom"),filetypes=[("DICOM","*.dcm *.DCM"),("All","*.*")])
        if not files: return
        try:
            import pydicom
            for f in files:
                ds = pydicom.dcmread(f,stop_before_pixels=True); uid = str(getattr(ds,"SOPInstanceUID",""))
                if uid and uid not in self._uids: self._uids.append(uid); self.listbox.insert("end",uid)
            self.uid_count.configure(text=t("commit.uid_count", n=len(self._uids)))
        except Exception as e: messagebox.showerror(t("common.error"),str(e))

    def _clear_uids(self):
        self._uids.clear(); self.listbox.delete(0,"end"); self.uid_count.configure(text=t("commit.uid_count", n=0))

    def _do_commit(self):
        if not self._uids: messagebox.showwarning("Storage Commitment",t("commit.no_uids")); return
        ae = self.ae_sel.get(); local = self.app.local_ae; uids = list(self._uids)
        self.log.append(f"N-ACTION -> {ae['ae_title']}@{ae['host']}:{ae['port']}  ({len(uids)} UIDs)")
        def run():
            try:
                from dicom.operations import storage_commit
                ok, msg = storage_commit(local,ae["host"],ae["port"],ae["ae_title"],uids,callback=lambda m: self.log.append(m))
                self.log.append(msg)
            except Exception as e: self.log.append(f"Error: {e}","err")
        threading.Thread(target=run, daemon=True).start()


class IOCMTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x",padx=10,pady=8)
        self.ae_sel = AESelector(top,self.app.config,t("iocm.iocm_scp")); self.ae_sel.pack(fill="x")
        cf = _lf(top,t("iocm.notification")); cf.pack(fill="x",pady=(8,0))
        gf = ttk.Frame(cf); gf.pack(fill="x")
        for i,(lbl,attr,default) in enumerate([(t("iocm.patient_id"),"iocm_pid",""),(t("iocm.study_uid"),"iocm_suid",""),(t("iocm.series_uid"),"iocm_seruid",""),(t("iocm.sop_class"),"iocm_sopclass",""),(t("iocm.sop_inst"),"iocm_sopinst",""),(t("iocm.availability"),"iocm_avail","ONLINE")]):
            r, c = divmod(i,2)
            fr = ttk.Frame(gf); fr.grid(row=r,column=c,sticky="w",padx=8,pady=3)
            _label(fr,lbl).pack(side="left")
            var = tk.StringVar(value=default); setattr(self,attr,var)
            _entry(fr,textvariable=var,width=36).pack(side="left",padx=4)
        ctrl = ttk.Frame(top); ctrl.pack(fill="x",pady=(8,0))
        _btn(ctrl,t("iocm.send"),self._do_iocm,style="Danger.TButton").pack(side="left",padx=2)
        lf2, self.log = _log_frame(self,height=10); lf2.pack(fill="both",expand=True,padx=10,pady=6)

    def _do_iocm(self):
        ae = self.ae_sel.get(); local = self.app.local_ae
        params = {"patient_id":self.iocm_pid.get(),"study_uid":self.iocm_suid.get(),"series_uid":self.iocm_seruid.get(),"sop_class_uid":self.iocm_sopclass.get(),"sop_inst_uid":self.iocm_sopinst.get(),"availability":self.iocm_avail.get()}
        self.log.append(f"IOCM N-CREATE -> {ae['ae_title']}@{ae['host']}:{ae['port']}")
        def run():
            try:
                from dicom.operations import iocm_notify
                ok, msg = iocm_notify(local,ae["host"],ae["port"],ae["ae_title"],params,callback=lambda m: self.log.append(m))
                self.log.append(msg)
            except Exception as e: self.log.append(f"Error: {e}","err")
        threading.Thread(target=run, daemon=True).start()


class HL7Tab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app
        self._listener_running = False; self._build()

    # Templates are loaded from hl7_templates/*.hl7 files at runtime.
    # No hardcoding here — edit the files in that folder to change templates.

    @staticmethod
    def _load_templates_from_disk():
        """
        Load all .hl7 template files from the hl7_templates/ folder.
        Returns a list of dicts: [{name, description, body, filename}, ...]
        Sorted alphabetically by filename for a predictable dropdown order.
        """
        try:
            return _load_hl7_templates()
        except Exception as e:
            logger.warning(f"Could not load HL7 templates from disk: {e}")
            return []

    def _build(self):
        nb = ttk.Notebook(self); nb.pack(fill="both",expand=True,padx=8,pady=8)
        send_tab = ttk.Frame(nb); nb.add(send_tab,text="  "+t("hl7.send_tab")+"  "); self._build_sender(send_tab)
        recv_tab = ttk.Frame(nb); nb.add(recv_tab,text="  "+t("hl7.recv_tab")+"  "); self._build_receiver(recv_tab)

    def _build_sender(self, parent):
        top = ttk.Frame(parent); top.pack(fill="x",padx=10,pady=8)
        conn_lf = _lf(top,t("hl7.destination")); conn_lf.pack(fill="x")
        row = ttk.Frame(conn_lf); row.pack(fill="x")
        for lbl,attr,val,w in [(t("hl7.host"),"hl7_host_var","127.0.0.1",22),(t("hl7.port"),"hl7_port_var","2575",6)]:
            _label(row,lbl).pack(side="left",padx=(0,4))
            var = tk.StringVar(value=val); setattr(self,attr,var)
            _entry(row,textvariable=var,width=w).pack(side="left",padx=(0,16))
        tmpl_lf = _lf(top,t("hl7.template_section")); tmpl_lf.pack(fill="x",pady=(8,0))
        tr = ttk.Frame(tmpl_lf); tr.pack(fill="x",pady=(0,6))
        _label(tr,t("hl7.template")).pack(side="left")

        # Load template names from disk and populate the dropdown
        self._template_data = self._load_templates_from_disk()
        tmpl_names = [tmpl["name"] for tmpl in self._template_data]
        self.tmpl_var = tk.StringVar(value=tmpl_names[0] if tmpl_names else "")
        self.tmpl_cb = ttk.Combobox(tr, textvariable=self.tmpl_var,
            values=tmpl_names, state="readonly", width=40)
        self.tmpl_cb.pack(side="left", padx=6)
        _btn(tr,t("hl7.load_template"),self._load_template).pack(side="left",padx=4)
        _btn(tr,t("common.refresh"),self._refresh_templates).pack(side="left",padx=2)

        # Description label shown below the dropdown
        self.tmpl_desc_lbl = _label(tmpl_lf,"",style="Dim.TLabel")
        self.tmpl_desc_lbl.pack(anchor="w",pady=(0,4))
        self.tmpl_cb.bind("<<ComboboxSelected>>", self._on_tmpl_selected)
        self._on_tmpl_selected()  # populate description for initial selection
        vf = ttk.Frame(tmpl_lf); vf.pack(fill="x")
        fill_fields = [(t("hl7.patient_id"),"tmpl_pid",""),(t("hl7.patient_name"),"tmpl_name",""),(t("hl7.dob"),"tmpl_dob",""),(t("hl7.sex"),"tmpl_sex","M"),(t("hl7.accession"),"tmpl_acc",""),(t("hl7.proc_code"),"tmpl_code",""),(t("hl7.proc_desc"),"tmpl_desc",""),(t("hl7.modality"),"tmpl_mod","CT"),(t("hl7.sending_app"),"tmpl_sa","RIS"),(t("hl7.sending_facility"),"tmpl_sf","HOSPITAL"),(t("hl7.recv_app"),"tmpl_ra","PACS"),(t("hl7.recv_facility"),"tmpl_rf","HOSPITAL")]
        for i,(lbl,attr,default) in enumerate(fill_fields):
            r, c = divmod(i,2)
            fr = ttk.Frame(vf); fr.grid(row=r,column=c,sticky="w",padx=6,pady=2)
            _label(fr,lbl).pack(side="left")
            var = tk.StringVar(value=default); setattr(self,attr,var)
            _entry(fr,textvariable=var,width=22).pack(side="left",padx=4)
        self.send_debug_var = tk.BooleanVar(value=False)
        dbg_row = ttk.Frame(parent); dbg_row.pack(fill="x",padx=10,pady=(2,0))
        ttk.Checkbutton(dbg_row,text=t("hl7.show_mllp"),variable=self.send_debug_var).pack(side="left")
        ctrl = ttk.Frame(parent); ctrl.pack(fill="x",padx=10,pady=4)
        _btn(ctrl,t("hl7.send_mllp"),self._do_hl7_send,style="Primary.TButton").pack(side="left",padx=2)
        _btn(ctrl,t("hl7.clear_msg"),lambda: self.hl7_msg_text.delete("1.0","end")).pack(side="left",padx=4)
        pw = ttk.PanedWindow(parent, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=(0,6))
        msg_lf = _lf(pw,t("hl7.msg_to_send"))
        self.hl7_msg_text = tk.Text(msg_lf,bg="white",fg="#1a1a1a",font=FONT_MONO,height=8,wrap="none",bd=1,relief="solid")
        sb_msg = ttk.Scrollbar(msg_lf,orient="vertical",command=self.hl7_msg_text.yview)
        self.hl7_msg_text.configure(yscrollcommand=sb_msg.set)
        self.hl7_msg_text.pack(side="left",fill="both",expand=True); sb_msg.pack(side="right",fill="y")
        pw.add(msg_lf, weight=3)
        lf_log, self.hl7_send_log = _log_frame(pw, height=5)
        pw.add(lf_log, weight=1)

    def _build_receiver(self, parent):
        top = ttk.Frame(parent); top.pack(fill="x",padx=10,pady=8)
        cfg_lf = _lf(top,t("hl7.listener_config")); cfg_lf.pack(fill="x")
        row = ttk.Frame(cfg_lf); row.pack(fill="x")
        _label(row,t("hl7.listen_port")).pack(side="left",padx=(0,4))
        self.hl7_listen_port_var = tk.StringVar(value=str(self.app.config.get("hl7",{}).get("listen_port",2575)))
        _entry(row,textvariable=self.hl7_listen_port_var,width=8).pack(side="left",padx=(0,16))
        self.recv_debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row,text=t("hl7.show_mllp"),variable=self.recv_debug_var).pack(side="left",padx=8)
        self.recv_btn = _btn(top,t("hl7.start_hl7"),self._toggle_listener,style="Primary.TButton")
        self.recv_btn.pack(fill="x",pady=(8,0))
        self.recv_status = _label(top,t("hl7.listener_not_running"),style="Dim.TLabel"); self.recv_status.pack(anchor="w",pady=(4,0))
        pw = ttk.PanedWindow(parent, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=(0,6))
        msg_lf = _lf(pw,t("hl7.received_messages"))
        ctrl_row = ttk.Frame(msg_lf); ctrl_row.pack(fill="x",pady=(0,4))
        _btn(ctrl_row,t("common.clear"),self._clear_received).pack(side="right")
        self.recv_count_lbl = _label(ctrl_row,t("hl7.messages_received", n=0),style="Dim.TLabel"); self.recv_count_lbl.pack(side="left")
        self._recv_msg_count = 0
        self.hl7_recv_text = tk.Text(msg_lf,bg="white",fg="#1a1a1a",font=FONT_MONO,wrap="none",bd=1,relief="solid",state="disabled")
        sb_rv = ttk.Scrollbar(msg_lf,orient="vertical",command=self.hl7_recv_text.yview)
        sb_rh = ttk.Scrollbar(msg_lf,orient="horizontal",command=self.hl7_recv_text.xview)
        self.hl7_recv_text.configure(yscrollcommand=sb_rv.set,xscrollcommand=sb_rh.set)
        sb_rh.pack(side="bottom",fill="x"); self.hl7_recv_text.pack(side="left",fill="both",expand=True); sb_rv.pack(side="right",fill="y")
        pw.add(msg_lf, weight=3)
        lf_log, self.hl7_recv_log = _log_frame(pw, height=4)
        pw.add(lf_log, weight=1)

    def _on_tmpl_selected(self, _=None):
        """Update the description label when the user picks a different template."""
        name = self.tmpl_var.get()
        tmpl = next((t for t in self._template_data if t["name"] == name), None)
        desc = tmpl["description"] if tmpl else ""
        self.tmpl_desc_lbl.configure(text=desc)

    def _refresh_templates(self):
        """Reload template files from disk and refresh the dropdown."""
        self._template_data = self._load_templates_from_disk()
        tmpl_names = [tmpl["name"] for tmpl in self._template_data]
        prev = self.tmpl_var.get()
        self.tmpl_cb["values"] = tmpl_names
        # Keep current selection if still available
        if prev in tmpl_names:
            self.tmpl_var.set(prev)
        elif tmpl_names:
            self.tmpl_var.set(tmpl_names[0])
        self._on_tmpl_selected()
        self.hl7_send_log.append(t("hl7.templates_refreshed", n=len(tmpl_names)))

    def _load_template(self):
        """Fill the message editor with the selected template, substituting placeholders."""
        name = self.tmpl_var.get()
        tmpl = next((t for t in self._template_data if t["name"] == name), None)
        if not tmpl:
            messagebox.showwarning("Load Template", t("hl7.no_template_selected"))
            return

        body = tmpl["body"]   # raw text with {placeholders}

        ts    = datetime.now().strftime("%Y%m%d%H%M%S")
        msgid = f"MSG{datetime.now().strftime('%H%M%S%f')[:12]}"
        nm    = self.tmpl_name.get() or "PATIENT^TEST"
        parts = nm.split("^")

        subs = {
            "ts":             ts,
            "msgid":          msgid,
            "pid":            self.tmpl_pid.get()  or "PID001",
            "name":           nm,
            "name_last":      parts[0] if parts else "PATIENT",
            "name_first":     parts[1] if len(parts) > 1 else "TEST",
            "dob":            self.tmpl_dob.get()  or "19800101",
            "sex":            self.tmpl_sex.get()  or "U",
            "acc":            self.tmpl_acc.get()  or "ACC001",
            "proc_code":      self.tmpl_code.get() or "RADPROC",
            "proc_desc":      self.tmpl_desc.get() or "Radiology Procedure",
            "modality":       self.tmpl_mod.get()  or "CT",
            "study_uid":      "",
            "sending_app":    self.tmpl_sa.get()   or "RIS",
            "sending_fac":    self.tmpl_sf.get()   or "HOSPITAL",
            "recv_app":       self.tmpl_ra.get()   or "PACS",
            "recv_fac":       self.tmpl_rf.get()   or "HOSPITAL",
            "assigning_auth": "HOSP",
        }

        # Replace all {placeholder} occurrences
        msg = body
        for key, val in subs.items():
            msg = msg.replace("{" + key + "}", val)

        # Show \r as newlines so the editor is readable
        self.hl7_msg_text.delete("1.0", "end")
        self.hl7_msg_text.insert("1.0", msg.replace("\r", "\n"))

    def _do_hl7_send(self):
        host = self.hl7_host_var.get().strip(); port = int(self.hl7_port_var.get().strip() or "2575")
        msg = self.hl7_msg_text.get("1.0","end").strip().replace("\n","\r")
        if not msg: messagebox.showwarning("HL7 Send",t("hl7.no_message")); return
        debug = self.send_debug_var.get()
        self.hl7_send_log.append(f"Sending to {host}:{port}")
        def run():
            try:
                from hl7_module.messaging import send_mllp
                dbg = (lambda m: self.hl7_send_log.append(m,"info")) if debug else None
                ok, resp = send_mllp(host, port, msg, debug_callback=dbg)
                self.hl7_send_log.append(f"{'OK' if ok else 'FAIL'}  Response: {resp[:300]}")
            except Exception as e: self.hl7_send_log.append(f"Error: {e}","err")
        threading.Thread(target=run, daemon=True).start()

    def _toggle_listener(self):
        if self._listener_running: self._stop_listener()
        else: self._start_listener()

    def _start_listener(self):
        try: port = int(self.hl7_listen_port_var.get().strip() or "2575")
        except ValueError: messagebox.showerror(t("common.error"),t("hl7.invalid_port")); return
        debug = self.recv_debug_var.get()
        self._listener_running = True
        self.recv_btn.configure(text=t("hl7.stop_hl7"),style="Danger.TButton")
        self.recv_status.configure(text=t("hl7.listening_on", port=port))
        self.hl7_recv_log.append(f"Starting MLLP listener on port {port}")
        def on_message(msg, addr): self._append_received(msg, addr)
        def on_debug(raw_str): self.hl7_recv_log.append(raw_str, "info")
        def run():
            try:
                from hl7_module.messaging import HL7Listener
                import time
                dbg = on_debug if debug else None
                listener = HL7Listener(port=port, callback=on_message, debug_callback=dbg)
                listener.start()
                while self._listener_running: time.sleep(0.5)
                listener.stop()
            except Exception as e:
                self.hl7_recv_log.append(f"Listener error: {e}","err")
                self._listener_running = False
                self.recv_btn.configure(text=t("hl7.start_hl7"),style="Primary.TButton")
                self.recv_status.configure(text=t("hl7.listener_failed"))
        threading.Thread(target=run, daemon=True).start()

    def _stop_listener(self):
        self._listener_running = False
        self.recv_btn.configure(text=t("hl7.start_hl7"),style="Primary.TButton")
        self.recv_status.configure(text=t("hl7.listener_stopped"))
        self.hl7_recv_log.append(t("hl7.listener_stopped"))

    def _append_received(self, msg_str, addr):
        self._recv_msg_count += 1
        self.recv_count_lbl.configure(text=t("hl7.messages_received", n=self._recv_msg_count))
        ts = datetime.now().strftime("%H:%M:%S")
        display = f"{'─'*60}\n[{ts}]  From {addr[0]}:{addr[1]}\n{msg_str.replace(chr(13), chr(10))}\n"
        self.hl7_recv_text.configure(state="normal"); self.hl7_recv_text.insert("end",display)
        self.hl7_recv_text.see("end"); self.hl7_recv_text.configure(state="disabled")
        self.hl7_recv_log.append(f"Received message from {addr[0]}:{addr[1]}")

    def _clear_received(self):
        self.hl7_recv_text.configure(state="normal"); self.hl7_recv_text.delete("1.0","end")
        self.hl7_recv_text.configure(state="disabled")
        self._recv_msg_count = 0; self.recv_count_lbl.configure(text=t("hl7.messages_received", n=0))


class SCPListenerTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._scp_running = False; self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x",padx=10,pady=8)
        cfg_lf = _lf(top,t("scp.listener_config")); cfg_lf.pack(fill="x")
        row = ttk.Frame(cfg_lf); row.pack(fill="x")
        _label(row,t("scp.ae_title")).pack(side="left",padx=(0,4))
        self.scp_ae_var = tk.StringVar(value=self.app.config.get("local_ae",{}).get("ae_title","PACSADMIN"))
        _entry(row,textvariable=self.scp_ae_var,width=16).pack(side="left",padx=(0,20))
        _label(row,t("scp.port")).pack(side="left",padx=(0,4))
        self.scp_port_var = tk.StringVar(value=str(self.app.config.get("local_ae",{}).get("port",11112)))
        _entry(row,textvariable=self.scp_port_var,width=8).pack(side="left",padx=(0,20))
        save_row = ttk.Frame(cfg_lf); save_row.pack(fill="x",pady=(6,0))
        _label(save_row,t("scp.save_to")).pack(side="left",padx=(0,6))
        self.save_dir_var = tk.StringVar(value=os.path.expanduser("~/DICOM_Received"))
        _entry(save_row,textvariable=self.save_dir_var,width=40).pack(side="left")
        _btn(save_row,t("common.browse"),self._browse_save_dir).pack(side="left",padx=4)
        self.scp_btn = _btn(top,t("scp.start_scp"),self._toggle_scp,style="Primary.TButton")
        self.scp_btn.pack(fill="x",pady=(10,0))
        self.scp_status = _label(top,t("scp.not_running"),style="Dim.TLabel"); self.scp_status.pack(anchor="w",pady=(4,0))
        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=(0,6))
        lf = _lf(pw,t("scp.received_files"))
        ctrl = ttk.Frame(lf); ctrl.pack(fill="x",pady=(0,4))
        _btn(ctrl,t("scp.clear_list"),self._clear_list).pack(side="right")
        self.recv_file_count = _label(ctrl,t("scp.files_received", n=0),style="Dim.TLabel"); self.recv_file_count.pack(side="left")
        self._file_count = 0
        self.recv_listbox = tk.Listbox(lf,bg="white",fg="#1a1a1a",selectbackground="#dbeafe",selectforeground="#1e3a5f",font=FONT_MONO,bd=1,relief="solid",activestyle="none")
        sb = ttk.Scrollbar(lf,orient="vertical",command=self.recv_listbox.yview)
        self.recv_listbox.configure(yscrollcommand=sb.set)
        self.recv_listbox.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        pw.add(lf, weight=3)
        lf2, self.log = _log_frame(pw, height=6)
        pw.add(lf2, weight=1)

    def _browse_save_dir(self):
        d = filedialog.askdirectory(title=t("scp.select_save_folder"))
        if d: self.save_dir_var.set(d)

    def _clear_list(self):
        self.recv_listbox.delete(0,"end"); self._file_count = 0
        self.recv_file_count.configure(text=t("scp.files_received", n=0))

    def _toggle_scp(self):
        if self._scp_running: self._stop_scp()
        else: self._start_scp()

    def _start_scp(self):
        ae_title = self.scp_ae_var.get().strip()
        try: port = int(self.scp_port_var.get().strip())
        except ValueError: messagebox.showerror(t("common.error"),t("scp.invalid_port")); return
        save_dir = self.save_dir_var.get().strip(); os.makedirs(save_dir,exist_ok=True)
        self._scp_running = True
        self.scp_btn.configure(text=t("scp.stop_scp"),style="Danger.TButton")
        self.scp_status.configure(text=t("scp.listening_as", ae_title=ae_title, port=port))
        self.log.append(f"Starting DICOM Storage SCP: {ae_title}  port={port}  save to {save_dir}")
        def run():
            try:
                from dicom.operations import run_storage_scp
                run_storage_scp(ae_title,port,save_dir,on_received=self._on_file_received,on_log=lambda m: self.log.append(m),running_flag=lambda: self._scp_running)
            except Exception as e:
                self.log.append(f"SCP error: {e}","err"); self._scp_running = False
                self.scp_btn.configure(text=t("scp.start_scp"),style="Primary.TButton")
                self.scp_status.configure(text=t("scp.stopped_error"))
        threading.Thread(target=run, daemon=True).start()

    def _stop_scp(self):
        self._scp_running = False
        self.scp_btn.configure(text=t("scp.start_scp"),style="Primary.TButton")
        self.scp_status.configure(text=t("scp.stopping")); self.log.append(t("scp.stopping"))

    def _on_file_received(self, path):
        self._file_count += 1
        self.recv_file_count.configure(text=t("scp.files_received", n=self._file_count))
        self.recv_listbox.insert("end",path); self.recv_listbox.see("end")


# ---------------------------------------------------------------------------
#  SR Viewer Tab  –  parse and display DICOM Structured Reports
# ---------------------------------------------------------------------------
class SRViewerTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app
        self._current_dataset = None
        self._build()

    def _build(self):
        # ── Top: file picker ───────────────────────────────────────────────
        top = ttk.Frame(self); top.pack(fill="x", padx=10, pady=8)
        lf_load = _lf(top, t("sr_viewer.load_file")); lf_load.pack(fill="x")
        row = ttk.Frame(lf_load); row.pack(fill="x")
        self.file_var = tk.StringVar()
        _entry(row, textvariable=self.file_var, width=60).pack(side="left", fill="x", expand=True, padx=(0, 6))
        _btn(row, t("common.browse"), self._browse_file).pack(side="left")
        ctrl = ttk.Frame(lf_load); ctrl.pack(fill="x", pady=(6, 0))
        _btn(ctrl, t("sr_viewer.parse_btn"), self._parse_sr, style="Primary.TButton").pack(side="left")
        _btn(ctrl, t("sr_viewer.view_tags"), self._view_raw_tags).pack(side="left", padx=(6, 0))
        self.meta_lbl = _label(ctrl, "", style="Dim.TLabel"); self.meta_lbl.pack(side="left", padx=12)

        # ── Bottom: paned view – SR report text + log ─────────────────────
        pw = ttk.PanedWindow(self, orient="vertical")
        pw.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        rf = _lf(pw, t("sr_viewer.report")); pw.add(rf, weight=4)
        self.sr_text = tk.Text(
            rf, bg="white", fg="#1a1a1a", font=FONT_MONO,
            relief="solid", bd=1, state="disabled", wrap="word",
            height=22,
        )
        sb_v = ttk.Scrollbar(rf, orient="vertical",   command=self.sr_text.yview)
        sb_h = ttk.Scrollbar(rf, orient="horizontal", command=self.sr_text.xview)
        self.sr_text.configure(yscrollcommand=sb_v.set, xscrollcommand=sb_h.set)
        self.sr_text.grid(row=0, column=0, sticky="nsew")
        sb_v.grid(row=0, column=1, sticky="ns")
        sb_h.grid(row=1, column=0, sticky="ew")
        rf.rowconfigure(0, weight=1); rf.columnconfigure(0, weight=1)

        lf_log, self.log = _log_frame(pw, height=4); pw.add(lf_log, weight=1)

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title=t("sr_viewer.select_file"),
            filetypes=[("DICOM", "*.dcm *.DCM"), ("All files", "*.*")],
        )
        if path:
            self.file_var.set(path)

    def _parse_sr(self):
        path = self.file_var.get().strip()
        if not path:
            messagebox.showwarning(t("sr_viewer.parse_btn"), t("sr_viewer.no_file"))
            return
        self.log.append(f"Parsing: {os.path.basename(path)}")
        self._current_dataset = None
        self.meta_lbl.configure(text="")

        def run():
            try:
                import pydicom
                from dicom.sr_reader import parse_sr, sr_to_text
                ds = pydicom.dcmread(path)
                self._current_dataset = ds
                parsed = parse_sr(ds)
                report_text = sr_to_text(parsed)
                meta = parsed.get("meta", {})
                label = (
                    f"{meta.get('SOPClassName','')}"
                    f"  |  {meta.get('PatientName','')} [{meta.get('PatientID','')}]"
                    f"  |  {meta.get('StudyDate','')}"
                )
                self.sr_text.configure(state="normal")
                self.sr_text.delete("1.0", "end")
                self.sr_text.insert("end", report_text)
                self.sr_text.configure(state="disabled")
                self.meta_lbl.configure(text=label)
                n = len(parsed.get("flat", []))
                self.log.append(t("sr_viewer.parsed_ok", n=n), "ok")
            except Exception as e:
                self.log.append(f"Error: {e}", "err")

        threading.Thread(target=run, daemon=True).start()

    def _view_raw_tags(self):
        if self._current_dataset is None:
            messagebox.showinfo(t("sr_viewer.view_tags"), t("sr_viewer.no_parsed"))
            return
        _show_dicom_detail(self, self._current_dataset, title=t("sr_viewer.tags_title"))


# ---------------------------------------------------------------------------
#  KOS Creator Tab  –  build a Key Object Selection DICOM document
# ---------------------------------------------------------------------------
class KOSCreatorTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app
        self._loaded_files: list = []
        self._build()

    def _build(self):
        outer = ttk.Frame(self); outer.pack(fill="both", expand=True)

        # ── Left column: form ──────────────────────────────────────────────
        canvas = tk.Canvas(outer, bg="#f5f5f5", highlightthickness=0)
        vsb    = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win_id, width=canvas.winfo_width())
        inner.bind("<Configure>", _on_configure)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))

        # ── Load from DICOM files ─────────────────────────────────────────
        lf_load = _lf(inner, t("kos_creator.load_files")); lf_load.pack(fill="x", padx=10, pady=8)
        row = ttk.Frame(lf_load); row.pack(fill="x")
        self.file_count_lbl = _label(row, t("kos_creator.no_files_loaded"), style="Dim.TLabel")
        self.file_count_lbl.pack(side="left")
        _btn(row, t("common.browse"), self._browse_dicom_files).pack(side="right")
        _btn(row, t("kos_creator.extract_btn"), self._extract_from_files,
             style="Primary.TButton").pack(side="right", padx=(0, 4))

        # ── Study / Patient info ──────────────────────────────────────────
        lf_study = _lf(inner, t("kos_creator.study_info")); lf_study.pack(fill="x", padx=10, pady=(0, 4))
        for i, (lbl, attr, val, w) in enumerate([
            (t("kos_creator.study_uid"),    "study_uid_var",  "",         48),
            (t("kos_creator.patient_id"),   "pat_id_var",     "",         20),
            (t("kos_creator.patient_name"), "pat_name_var",   "",         24),
            (t("kos_creator.accession"),    "accession_var",  "",         20),
            (t("kos_creator.study_date"),   "study_date_var", "",         12),
            (t("kos_creator.institution"),  "institution_var","",         24),
        ]):
            r, c = divmod(i, 2)
            fr = ttk.Frame(lf_study); fr.grid(row=r, column=c, sticky="w", padx=8, pady=3)
            _label(fr, lbl).pack(side="left")
            var = tk.StringVar(value=val); setattr(self, attr, var)
            _entry(fr, textvariable=var, width=w).pack(side="left", padx=4)

        # ── Referenced instances ──────────────────────────────────────────
        lf_inst = _lf(inner, t("kos_creator.instances")); lf_inst.pack(fill="x", padx=10, pady=(0, 4))
        _label(lf_inst, t("kos_creator.instances_hint"), style="Dim.TLabel").pack(anchor="w")
        self.inst_text = tk.Text(
            lf_inst, height=8, font=FONT_MONO, bg="white", fg="#1a1a1a",
            relief="solid", bd=1, wrap="none",
        )
        inst_vsb = ttk.Scrollbar(lf_inst, orient="vertical", command=self.inst_text.yview)
        inst_hsb = ttk.Scrollbar(lf_inst, orient="horizontal", command=self.inst_text.xview)
        self.inst_text.configure(yscrollcommand=inst_vsb.set, xscrollcommand=inst_hsb.set)
        self.inst_text.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        inst_vsb.grid(row=1, column=1, sticky="ns")
        inst_hsb.grid(row=2, column=0, sticky="ew")
        lf_inst.columnconfigure(0, weight=1)

        # ── KOS options ───────────────────────────────────────────────────
        lf_opt = _lf(inner, t("kos_creator.options")); lf_opt.pack(fill="x", padx=10, pady=(0, 4))
        opt_row = ttk.Frame(lf_opt); opt_row.pack(fill="x")
        _label(opt_row, t("kos_creator.doc_title")).pack(side="left")
        from dicom.kos_creator import KO_DOCUMENT_TITLES
        self.title_var = tk.StringVar(value="of_interest")
        title_cb = ttk.Combobox(
            opt_row, textvariable=self.title_var,
            values=list(KO_DOCUMENT_TITLES.keys()),
            state="readonly", width=20,
        )
        title_cb.pack(side="left", padx=(4, 16))

        # ── Action buttons ────────────────────────────────────────────────
        lf_act = ttk.Frame(inner); lf_act.pack(fill="x", padx=10, pady=(0, 4))
        _btn(lf_act, t("kos_creator.create_save"), self._create_kos, style="Primary.TButton").pack(side="left")
        _btn(lf_act, t("kos_creator.create_send"), self._create_and_send, style="Success.TButton").pack(side="left", padx=(8, 0))

        # ── AE selector (for C-STORE) ─────────────────────────────────────
        self.ae_sel = AESelector(inner, self.app.config, t("kos_creator.storage_scp"))
        self.ae_sel.pack(fill="x", padx=10, pady=(0, 4))

        # ── Log ───────────────────────────────────────────────────────────
        lf_log, self.log = _log_frame(inner, height=5); lf_log.pack(fill="x", padx=10, pady=(0, 8))

    # ── Actions ───────────────────────────────────────────────────────────

    def _browse_dicom_files(self):
        files = filedialog.askopenfilenames(
            title=t("kos_creator.select_files"),
            filetypes=[("DICOM", "*.dcm *.DCM"), ("All files", "*.*")],
        )
        if files:
            self._loaded_files = list(files)
            self.file_count_lbl.configure(
                text=t("kos_creator.files_loaded", n=len(self._loaded_files))
            )

    def _extract_from_files(self):
        if not self._loaded_files:
            messagebox.showwarning(t("kos_creator.extract_btn"), t("kos_creator.no_files_loaded_msg"))
            return
        self.log.append(t("kos_creator.extracting"))

        def run():
            try:
                from dicom.kos_creator import extract_study_info_from_dicom
                info = extract_study_info_from_dicom(self._loaded_files)
                self.study_uid_var.set(info.get("study_instance_uid", ""))
                self.pat_id_var.set(info.get("patient_id", ""))
                self.pat_name_var.set(info.get("patient_name", ""))
                self.accession_var.set(info.get("accession_number", ""))
                self.study_date_var.set(info.get("study_date", ""))
                self.institution_var.set(info.get("institution_name", ""))
                # Populate instances textarea
                lines = [t("kos_creator.instances_fmt_comment")]
                for series_uid, series_data in info.get("series", {}).items():
                    for inst in series_data.get("instances", []):
                        lines.append(
                            f"{series_uid}|{inst['sop_class_uid']}|{inst['sop_instance_uid']}"
                        )
                self.inst_text.delete("1.0", "end")
                self.inst_text.insert("end", "\n".join(lines))
                n_inst = sum(len(s["instances"]) for s in info.get("series", {}).values())
                self.log.append(
                    t("kos_creator.extracted_ok",
                      n_series=len(info.get("series", {})), n_inst=n_inst), "ok"
                )
                for err in info.get("errors", []):
                    self.log.append(f"Warning: {err}", "warn")
            except Exception as e:
                self.log.append(f"Error: {e}", "err")

        threading.Thread(target=run, daemon=True).start()

    def _build_referenced_series(self):
        """Parse the instances textarea into a referenced_series list."""
        text = self.inst_text.get("1.0", "end").strip()
        series_map: dict = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) == 3:
                series_uid, sop_class_uid, sop_inst_uid = parts
            elif len(parts) == 2:
                series_uid, sop_inst_uid = parts
                sop_class_uid = "1.2.840.10008.5.1.4.1.1.2"
            else:
                continue
            if series_uid not in series_map:
                series_map[series_uid] = []
            series_map[series_uid].append(
                {"sop_instance_uid": sop_inst_uid, "sop_class_uid": sop_class_uid}
            )
        return [
            {"series_uid": s_uid, "instances": insts}
            for s_uid, insts in series_map.items()
        ]

    def _create_kos_dataset(self):
        from dicom.kos_creator import create_kos
        refs = self._build_referenced_series()
        return create_kos(
            study_instance_uid = self.study_uid_var.get().strip(),
            patient_id         = self.pat_id_var.get().strip(),
            patient_name       = self.pat_name_var.get().strip(),
            accession_number   = self.accession_var.get().strip(),
            study_date         = self.study_date_var.get().strip(),
            referenced_series  = refs,
            study_description  = "",
            institution_name   = self.institution_var.get().strip(),
            doc_title_key      = self.title_var.get(),
            local_ae_title     = self.app.local_ae.get("ae_title", "PACSADMIN"),
        )

    def _create_kos(self):
        path = filedialog.asksaveasfilename(
            title=t("kos_creator.save_as"),
            defaultextension=".dcm",
            filetypes=[("DICOM KOS", "*.dcm"), ("All files", "*.*")],
            initialfile="KOS.dcm",
        )
        if not path:
            return
        self.log.append(t("kos_creator.creating"))

        def run():
            try:
                ds = self._create_kos_dataset()
                try:
                    ds.save_as(path, enforce_file_format=True)
                except TypeError:
                    ds.save_as(path, write_like_original=False)
                self.log.append(t("kos_creator.saved_ok", path=path), "ok")
            except Exception as e:
                self.log.append(f"Error: {e}", "err")

        threading.Thread(target=run, daemon=True).start()

    def _create_and_send(self):
        ae = self.ae_sel.get()
        local = self.app.local_ae
        self.log.append(
            f"Creating KOS and sending to {ae['ae_title']}@{ae['host']}:{ae['port']}"
        )

        def run():
            try:
                import tempfile, os as _os
                ds = self._create_kos_dataset()
                with tempfile.NamedTemporaryFile(suffix=".dcm", delete=False) as f:
                    tmp_path = f.name
                try:
                    ds.save_as(tmp_path, enforce_file_format=True)
                except TypeError:
                    ds.save_as(tmp_path, write_like_original=False)
                from dicom.operations import c_store
                ok, msg = c_store(
                    local["ae_title"] if isinstance(local, dict) else local,
                    ae["host"], ae["port"], ae["ae_title"],
                    [tmp_path],
                    callback=lambda m: self.log.append(m),
                )
                self.log.append(msg, "ok" if ok else "err")
            except Exception as e:
                self.log.append(f"Error: {e}", "err")
            finally:
                try:
                    _os.unlink(tmp_path)
                except Exception:
                    pass

        threading.Thread(target=run, daemon=True).start()


class SettingsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._build()

    def _build(self):
        lf1 = _lf(self,t("settings.local_ae")); lf1.pack(fill="x",padx=10,pady=8)
        r1 = ttk.Frame(lf1); r1.pack(fill="x")
        _label(r1,t("settings.ae_title")).grid(row=0,column=0,sticky="w",padx=(0,6))
        self.local_ae_var = tk.StringVar(value=self.app.config.get("local_ae",{}).get("ae_title","PACSADMIN"))
        _entry(r1,textvariable=self.local_ae_var,width=20).grid(row=0,column=1,padx=(0,20))
        _label(r1,t("settings.port")).grid(row=0,column=2,sticky="w",padx=(0,6))
        self.local_port_var = tk.StringVar(value=str(self.app.config.get("local_ae",{}).get("port",11112)))
        _entry(r1,textvariable=self.local_port_var,width=8).grid(row=0,column=3)
        lf2 = _lf(self,t("settings.remote_presets")); lf2.pack(fill="x",padx=10,pady=4)
        cols = ("name","ae_title","host","port")
        self.ae_tree = ttk.Treeview(lf2,columns=cols,show="headings",height=6)
        for c, w in zip(cols,[130,130,180,70]):
            self.ae_tree.heading(c,text=c); self.ae_tree.column(c,width=w)
        sb_ae = ttk.Scrollbar(lf2,orient="vertical",command=self.ae_tree.yview)
        self.ae_tree.configure(yscrollcommand=sb_ae.set)
        self.ae_tree.pack(side="left",fill="both",expand=True); sb_ae.pack(side="right",fill="y")
        self._reload_ae_tree()
        add_frame = ttk.Frame(lf2); add_frame.pack(fill="x",pady=4)
        for lbl,attr,w in [(t("settings.add_name"),"new_name",14),(t("settings.add_ae"),"new_aet",12),(t("settings.add_host"),"new_host",20),(t("settings.add_port"),"new_port",6)]:
            _label(add_frame,lbl).pack(side="left",padx=(4,2))
            var = tk.StringVar(); setattr(self,attr,var)
            _entry(add_frame,textvariable=var,width=w).pack(side="left",padx=2)
        _btn(add_frame,t("settings.add_btn"),self._add_ae,style="Primary.TButton").pack(side="left",padx=6)
        _btn(add_frame,t("settings.delete_selected"),self._del_ae,style="Danger.TButton").pack(side="left",padx=2)
        lf3 = _lf(self,t("settings.hl7_settings")); lf3.pack(fill="x",padx=10,pady=4)
        r3 = ttk.Frame(lf3); r3.pack(fill="x")
        _label(r3,t("settings.hl7_port")).pack(side="left")
        self.hl7_port_var = tk.StringVar(value=str(self.app.config.get("hl7",{}).get("listen_port",2575)))
        _entry(r3,textvariable=self.hl7_port_var,width=6).pack(side="left",padx=4)
        # Language selector
        lf4 = _lf(self,t("settings.language")); lf4.pack(fill="x",padx=10,pady=4)
        r4 = ttk.Frame(lf4); r4.pack(fill="x")
        _label(r4,t("settings.language_label")).pack(side="left")
        self.lang_var = tk.StringVar(value=current_language())
        langs = available_languages()
        lang_names = [name for _, name in langs]
        lang_codes = [code for code, _ in langs]
        self._lang_codes = lang_codes
        self._lang_names = lang_names
        self.lang_cb = ttk.Combobox(r4,textvariable=self.lang_var,values=lang_codes,state="readonly",width=10)
        self.lang_cb.pack(side="left",padx=4)
        # Show display name next to code
        self._lang_display = _label(r4,dict(langs).get(current_language(),""),style="Dim.TLabel")
        self._lang_display.pack(side="left",padx=4)
        self.lang_cb.bind("<<ComboboxSelected>>", self._on_lang_change)
        _label(lf4,t("settings.language_note"),style="Dim.TLabel").pack(anchor="w",pady=(4,0))
        btn_row = ttk.Frame(self); btn_row.pack(padx=10,pady=12,anchor="w")
        _btn(btn_row,t("settings.save"),self._save,style="Primary.TButton").pack(side="left",padx=4)
        self.save_lbl = _label(btn_row,"",style="Dim.TLabel"); self.save_lbl.pack(side="left",padx=8)

    def _on_lang_change(self, _=None):
        code = self.lang_var.get()
        langs = dict(available_languages())
        self._lang_display.configure(text=langs.get(code, ""))

    def _reload_ae_tree(self):
        self.ae_tree.delete(*self.ae_tree.get_children())
        for ae in self.app.config.get("remote_aes",[]):
            self.ae_tree.insert("","end",values=(ae.get("name",""),ae.get("ae_title",""),ae.get("host",""),ae.get("port",104)))

    def _add_ae(self):
        entry = {"name":self.new_name.get().strip(),"ae_title":self.new_aet.get().strip(),"host":self.new_host.get().strip(),"port":int(self.new_port.get().strip() or "104")}
        if not entry["name"]: messagebox.showwarning("Add AE",t("settings.name_required")); return
        self.app.config.setdefault("remote_aes",[]).append(entry); self._reload_ae_tree()
        for attr in ("new_name","new_aet","new_host","new_port"): getattr(self,attr).set("")

    def _del_ae(self):
        sel = self.ae_tree.selection()
        if not sel: return
        idx = self.ae_tree.index(sel[0]); aes = self.app.config.get("remote_aes",[])
        if idx < len(aes): aes.pop(idx); self._reload_ae_tree()

    def _save(self):
        self.app.config.setdefault("local_ae",{})
        self.app.config["local_ae"]["ae_title"] = self.local_ae_var.get().strip()
        self.app.config["local_ae"]["port"] = int(self.local_port_var.get().strip() or "11112")
        self.app.config.setdefault("hl7",{})
        self.app.config["hl7"]["listen_port"] = int(self.hl7_port_var.get().strip() or "2575")
        self.app.config["language"] = self.lang_var.get()
        save_config(self.app.config)
        self.save_lbl.configure(text=t("settings.saved", ts=datetime.now().strftime('%H:%M:%S')))


class HelpTab(ttk.Frame):
    SECTIONS = [
        ("help.section_cfind", "help.body_cfind",
         [("DICOM PS3.4 §C – Query/Retrieve Service Class (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_C"),
          ("PS3.4 Table C.6-1 – Study Root Attributes", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#table_C.6-1"),
          ("PS3.4 Table C.6-2 – Patient Root Attributes", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#table_C.6-2")]),

        ("help.section_cstore", "help.body_cstore",
         [("DICOM PS3.4 §B – Storage Service Class (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_B")]),

        ("help.section_dmwl", "help.body_dmwl",
         [("DICOM PS3.4 §K – Modality Worklist Management (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_K")]),

        ("help.section_commit", "help.body_commit",
         [("DICOM PS3.4 §J – Storage Commitment Service Class (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_J")]),

        ("help.section_iocm", "help.body_iocm",
         [("DICOM PS3.4 §KK – Instance Availability Notification (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_KK")]),

        ("help.section_hl7_send", "help.body_hl7_send",
         [("ORM^O01 – Radiology Order (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ORM_O01"),
          ("ORU^R01 – Radiology Report (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ORU_R01"),
          ("ADT^A04 – Register Patient (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A04"),
          ("ADT^A08 – Update Patient (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A08"),
          ("ADT^A23 – Delete Visit (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A23"),
          ("SIU^S12 – Schedule Appointment (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/SIU_S12"),
          ("SIU^S15 – Cancel Appointment (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/SIU_S15"),
          ("QBP^Q22 – Patient Demographics Query (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/QBP_Q22"),
          ("OML^O21 – Lab Order (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/OML_O21")]),

        ("help.section_hl7_recv", "help.body_hl7_recv",
         [("HL7 v2.4 Message Definitions (Caristix)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents"),
          ("MLLP Transport Specification (HL7 TN)", "https://www.hl7.org/documentcenter/public/wg/inm/mllp_transport_specification.PDF")]),

        ("help.section_receiver", "help.body_receiver",
         [("DICOM PS3.4 §B – Storage Service Class (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_B")]),

        ("help.section_settings", "help.body_settings",
         []),

        ("help.section_sr_viewer", "help.body_sr_viewer",
         [("DICOM PS3.3 §C.17 – Structured Reporting IODs (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#chapter_C"),
          ("DICOM PS3.3 §A.35 – SR Document Storage SOP Classes (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#sect_A.35")]),

        ("help.section_kos_creator", "help.body_kos_creator",
         [("DICOM PS3.3 §C.17.6 – Key Object Selection Document IOD (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part03.html#sect_C.17.6"),
          ("IHE RAD TF Vol. 1 – XDS-I.b Integration Profile (IHE)", "https://www.ihe.net/uploadedFiles/Documents/Radiology/IHE_RAD_TF_Vol1.pdf")]),
    ]

    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._build()

    def _build(self):
        outer = ttk.Frame(self); outer.pack(fill="both",expand=True,padx=10,pady=10)
        left = ttk.Frame(outer); left.pack(side="left",fill="y",padx=(0,10))
        _label(left,t("help.topics"),style="H1.TLabel").pack(anchor="w",pady=(0,6))
        self.topic_lb = tk.Listbox(left,bg="white",fg="#1a1a1a",selectbackground="#dbeafe",selectforeground="#1e3a5f",font=FONT,relief="solid",bd=1,activestyle="none",width=28)
        for key, *_ in self.SECTIONS: self.topic_lb.insert("end","  "+t(key))
        self.topic_lb.pack(fill="y",expand=True)
        self.topic_lb.bind("<<ListboxSelect>>",self._show_section); self.topic_lb.selection_set(0)
        right = ttk.Frame(outer); right.pack(side="left",fill="both",expand=True)
        self.title_lbl = _label(right,t(self.SECTIONS[0][0]),style="H1.TLabel"); self.title_lbl.pack(anchor="w",pady=(0,8))
        _sep(right).pack(fill="x",pady=(0,8))
        self.text = tk.Text(right,bg="white",fg="#1a1a1a",font=FONT,wrap="word",relief="solid",bd=1,state="disabled",padx=10,pady=8,spacing1=2,spacing2=2)
        self.text.tag_configure("refs_label", foreground="#555555", font=(FONT[0], FONT[1], "bold"))
        self.text.tag_configure("link", foreground="#2b6cb0", underline=True)
        sb = ttk.Scrollbar(right,orient="vertical",command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        self._show_section()

    def _show_section(self,_=None):
        sel = self.topic_lb.curselection(); idx = sel[0] if sel else 0
        key, body_key, links = self.SECTIONS[idx]; self.title_lbl.configure(text=t(key))
        self.text.configure(state="normal"); self.text.delete("1.0","end")
        self.text.insert("1.0", t(body_key).strip())
        if links:
            self.text.insert("end", "\n\n" + t("help.official_docs") + "\n", "refs_label")
            for label, url in links:
                tag = f"link_{url}"
                self.text.insert("end", f"  \u2197 {label}\n", ("link", tag))
                self.text.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
                self.text.tag_bind(tag, "<Enter>", lambda e: self.text.configure(cursor="hand2"))
                self.text.tag_bind(tag, "<Leave>", lambda e: self.text.configure(cursor=""))
        self.text.configure(state="disabled")


# ---------------------------------------------------------------------------
#  About Tab
# ---------------------------------------------------------------------------
class AboutTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._build()

    def _build(self):
        outer = ttk.Frame(self); outer.pack(expand=True, anchor="center", pady=40, padx=60)

        # App title and version
        _label(outer, t("about.title"), style="H1.TLabel").pack(pady=(0, 4))
        _label(outer, t("app.version", version=_APP_VERSION), style="Dim.TLabel").pack()
        _sep(outer).pack(fill="x", pady=20)

        # Description
        desc = t("about.description") + "\n\n" + t("about.supports")
        _label(outer, desc, style="Dim.TLabel", justify="center").pack()
        _sep(outer).pack(fill="x", pady=20)

        # Credits
        credit_frame = ttk.Frame(outer); credit_frame.pack()
        _label(credit_frame, t("about.created_by"), style="Dim.TLabel").grid(row=0, column=0, sticky="e", padx=(0, 8))
        _label(credit_frame, "Bob van Mierlo", style="TLabel").grid(row=0, column=1, sticky="w")

        _label(credit_frame, t("about.built_with"), style="Dim.TLabel").grid(row=1, column=0, sticky="e", padx=(0, 8), pady=(8, 0))
        claude_lbl = _label(credit_frame, "Claude by Anthropic  ↗", style="TLabel")
        claude_lbl.grid(row=1, column=1, sticky="w", pady=(8, 0))
        claude_url = "https://www.anthropic.com/claude"
        claude_lbl.configure(foreground="#2b6cb0", cursor="hand2")
        claude_lbl.bind("<Button-1>", lambda e: webbrowser.open(claude_url))
        _label(credit_frame, t("about.claude_credit"),
               style="Dim.TLabel", justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0))

        _sep(outer).pack(fill="x", pady=20)

        # Tech stack
        _label(outer, t("about.tech_stack"), style="Dim.TLabel").pack()

        # Links row
        links_frame = ttk.Frame(outer); links_frame.pack(pady=(16, 0))
        for text, url in [
            (t("about.github"), "https://github.com/bobvmierlo/PACSAdminTool"),
            (t("about.dicom_standard"), "https://dicom.nema.org/medical/dicom/current/output/html/"),
            (t("about.hl7_reference"), "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents"),
        ]:
            lbl = _label(links_frame, text, style="TLabel")
            lbl.pack(side="left", padx=12)
            lbl.configure(foreground="#2b6cb0", cursor="hand2")
            lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))


# ---------------------------------------------------------------------------
#  Main Application  -  this is the class that main.py imports
# ---------------------------------------------------------------------------
class PACSAdminApp:
    def __init__(self):
        _setup_client_logging()
        self.config = load_config()
        set_language(self.config.get("language", "en"))
        self.root = tk.Tk()
        self.root.title(t("app.title"))
        self.root.geometry("1100x760")
        self.root.minsize(900, 600)
        self.root.configure(bg="#f5f5f5")
        _style_setup(self.root)
        self._build_ui()

    @property
    def local_ae(self):
        return {
            "ae_title": self.config.get("local_ae",{}).get("ae_title","PACSADMIN"),
            "port":     self.config.get("local_ae",{}).get("port",11112),
        }

    def _build_ui(self):
        hdr = tk.Frame(self.root,bg="#ffffff",height=42)
        hdr.pack(fill="x",side="top"); hdr.pack_propagate(False)
        tk.Label(hdr,text=t("app.title"),font=FONT_H1,bg="#ffffff",fg="#1a1a1a").pack(side="left",padx=16,pady=8)
        tk.Frame(hdr,bg="#e0e0e0",width=1).pack(side="left",fill="y",padx=0,pady=8)
        tk.Label(hdr,text=t("app.subtitle"),font=FONT,bg="#ffffff",fg="#888888").pack(side="left",padx=12)
        nb = ttk.Notebook(self.root); nb.pack(fill="both",expand=True,padx=0,pady=0)
        for label, cls in [
            ("  "+t("tabs.cfind")+"  ", CFindTab), ("  "+t("tabs.cstore")+"  ", CStoreTab),
            ("  "+t("tabs.dmwl")+"  ", DMWLTab), ("  "+t("tabs.commit")+"  ", StorageCommitTab),
            ("  "+t("tabs.iocm")+"  ", IOCMTab), ("  "+t("tabs.hl7")+"  ", HL7Tab),
            ("  "+t("tabs.scp")+"  ", SCPListenerTab),
            ("  "+t("tabs.sr_viewer")+"  ", SRViewerTab),
            ("  "+t("tabs.kos_creator")+"  ", KOSCreatorTab),
            ("  "+t("tabs.settings")+"  ", SettingsTab),
            ("  "+t("tabs.help")+"  ", HelpTab), ("  "+t("tabs.about")+"  ", AboutTab),
        ]:
            nb.add(cls(nb, self), text=label)
        sb = tk.Frame(self.root,bg="#e8e8e8",height=24)
        sb.pack(fill="x",side="bottom"); sb.pack_propagate(False)
        self._status_var = tk.StringVar(value=t("app.ready"))
        tk.Label(sb,textvariable=self._status_var,font=("Segoe UI",8),bg="#e8e8e8",fg="#666666").pack(side="left",padx=10)

    def run(self):
        self.root.mainloop()


def main():
    app = PACSAdminApp()
    app.run()


if __name__ == "__main__":
    main()
