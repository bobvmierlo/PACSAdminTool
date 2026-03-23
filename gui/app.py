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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.manager import load_config, save_config
from hl7_templates import load_templates as _load_hl7_templates

logger = logging.getLogger(__name__)

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


def _log_frame(parent, height=5, label="Activity Log"):
    lf = _lf(parent, label)
    box = LogBox(lf, height=height)
    sb = ttk.Scrollbar(lf, orient="vertical", command=box.yview)
    box.configure(yscrollcommand=sb.set)
    box.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return lf, box


class AESelector(ttk.LabelFrame):
    def __init__(self, parent, config, label="Remote AE", **kw):
        super().__init__(parent, text=label, padding=8, **kw)
        self.config = config
        top = ttk.Frame(self); top.pack(fill="x", pady=(0,6))
        _label(top, "Preset:", style="Card.TLabel").pack(side="left")
        self.preset_var = tk.StringVar(value="(manual)")
        self.preset_cb = ttk.Combobox(top, textvariable=self.preset_var, width=28, state="readonly")
        self.preset_cb.pack(side="left", padx=(4,6))
        self.preset_cb.bind("<<ComboboxSelected>>", self._load_preset)
        _btn(top, "Refresh", self.refresh_presets).pack(side="left")
        bot = ttk.Frame(self); bot.pack(fill="x")
        for col, (lbl, attr, val, w) in enumerate([
            ("AE Title:", "ae_var", "REMOTE_AE", 14),
            ("Host:", "host_var", "127.0.0.1", 22),
            ("Port:", "port_var", "104", 6),
        ]):
            _label(bot, lbl, style="Card.TLabel").grid(row=0, column=col*2, sticky="w", padx=(16 if col else 0, 4))
            var = tk.StringVar(value=val); setattr(self, attr, var)
            _entry(bot, textvariable=var, width=w).grid(row=0, column=col*2+1, padx=(0,4))
        self.refresh_presets()

    def refresh_presets(self):
        self.preset_cb["values"] = ["(manual)"] + [ae["name"] for ae in self.config.get("remote_aes", [])]

    def _load_preset(self, _=None):
        name = self.preset_var.get()
        for ae in self.config.get("remote_aes", []):
            if ae["name"] == name:
                self.ae_var.set(ae.get("ae_title","")); self.host_var.set(ae.get("host",""))
                self.port_var.set(str(ae.get("port",104))); return

    def get(self):
        return {"ae_title": self.ae_var.get().strip(), "host": self.host_var.get().strip(),
                "port": int(self.port_var.get().strip() or "104")}


def _show_dicom_detail(parent_win, dataset, title="DICOM Dataset"):
    win = tk.Toplevel(parent_win); win.title(title); win.geometry("860x580")
    win.configure(bg="#f5f5f5"); win.grab_set()
    sf = ttk.Frame(win); sf.pack(fill="x", padx=10, pady=(10,4))
    _label(sf, "Filter:").pack(side="left")
    search_var = tk.StringVar()
    _entry(sf, textvariable=search_var, width=36).pack(side="left", padx=(6,0))
    _label(sf, "  (tag, keyword, or value)", style="Dim.TLabel").pack(side="left")
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
    _label(bot, f"{len(all_rows)} tags returned", style="Dim.TLabel").pack(side="left")
    _btn(bot, "Close", win.destroy).pack(side="right"); win.focus_set()


class CFindTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._datasets = []; self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x", padx=10, pady=8)
        self.ae_sel = AESelector(top, self.app.config, "Query / Retrieve SCP"); self.ae_sel.pack(fill="x")
        qf = _lf(top, "Query Parameters"); qf.pack(fill="x", pady=(8,0))
        gf = ttk.Frame(qf); gf.pack(fill="x")
        for i, (lbl, attr) in enumerate([("Patient ID:","pid_var"),("Patient Name:","pname_var"),("Accession #:","acc_var"),("Study Date:","date_var"),("Modality:","mod_var"),("Study UID:","suid_var")]):
            r, c = divmod(i,3)
            fr = ttk.Frame(gf); fr.grid(row=r, column=c, sticky="w", padx=8, pady=3)
            _label(fr,lbl).pack(side="left")
            var = tk.StringVar(); setattr(self,attr,var)
            _entry(fr,textvariable=var,width=18).pack(side="left",padx=4)
        ctrl = ttk.Frame(top); ctrl.pack(fill="x", pady=(8,0))
        _label(ctrl,"Query Level:").pack(side="left")
        self.level_var = tk.StringVar(value="STUDY")
        ttk.Combobox(ctrl,textvariable=self.level_var,values=["PATIENT","STUDY","SERIES","IMAGE"],state="readonly",width=10).pack(side="left",padx=(4,12))
        _label(ctrl,"Model:").pack(side="left")
        self.model_var = tk.StringVar(value="STUDY")
        ttk.Combobox(ctrl,textvariable=self.model_var,values=["STUDY","PATIENT"],state="readonly",width=10).pack(side="left",padx=4)
        _sep(ctrl,"vertical").pack(side="left",fill="y",padx=12,pady=2)
        _btn(ctrl,"C-ECHO (Ping)",self._do_cecho).pack(side="left",padx=2)
        _btn(ctrl,"Run C-FIND",self._do_cfind,style="Primary.TButton").pack(side="left",padx=4)
        mf = ttk.Frame(top); mf.pack(fill="x", pady=(6,0))
        _label(mf,"C-MOVE Destination AE:").pack(side="left")
        self.move_dest_var = tk.StringVar(value=self.app.config.get("local_ae",{}).get("ae_title","PACSADMIN"))
        _entry(mf,textvariable=self.move_dest_var,width=16).pack(side="left",padx=4)
        _btn(mf,"C-MOVE Selected Study",self._do_cmove,style="Success.TButton").pack(side="left",padx=4)
        rf = _lf(self,"Results  (double-click a row to view all DICOM tags)"); rf.pack(fill="both",expand=True,padx=10,pady=6)
        cols = ("PatientID","PatientName","StudyDate","Modality","Accession","Description","StudyUID")
        self.tree = ttk.Treeview(rf,columns=cols,show="headings",height=12)
        for c, w in zip(cols,[110,150,90,80,120,200,300]):
            self.tree.heading(c,text=c); self.tree.column(c,width=w,minwidth=40)
        sb = ttk.Scrollbar(rf,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        self.tree.bind("<Double-1>",self._show_detail)
        lf2, self.log = _log_frame(self,height=5); lf2.pack(fill="x",padx=10,pady=(0,6))

    def _show_detail(self,_=None):
        sel = self.tree.selection()
        if not sel: return
        idx = self.tree.index(sel[0])
        if idx < len(self._datasets):
            _show_dicom_detail(self,self._datasets[idx],title=f"C-FIND Result - All DICOM Tags")

    def _do_cecho(self):
        ae = self.ae_sel.get(); local = self.app.local_ae
        self.log.append(f"C-ECHO -> {ae['ae_title']}@{ae['host']}:{ae['port']}")
        def run():
            try:
                from dicom.operations import c_echo
                ok, msg = c_echo(local, ae["host"], ae["port"], ae["ae_title"]); self.log.append(msg)
            except Exception as e: self.log.append(f"Error: {e}", "err")
        threading.Thread(target=run, daemon=True).start()

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
        if ds is None: self.log.append("pydicom not available","err"); return
        self.tree.delete(*self.tree.get_children()); self._datasets.clear()
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
            except Exception as e: self.log.append(f"Error: {e}","err")
        threading.Thread(target=run, daemon=True).start()

    def _do_cmove(self):
        sel = self.tree.selection()
        if not sel: messagebox.showwarning("C-MOVE","Select a result row first."); return
        ae = self.ae_sel.get(); local = self.app.local_ae
        dest = self.move_dest_var.get().strip()
        idx = self.tree.index(sel[0]); src = self._datasets[idx]
        try: from pydicom.dataset import Dataset
        except ImportError: self.log.append("pydicom not available","err"); return
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
        self.ae_sel = AESelector(top, self.app.config, "Storage SCP (destination)"); self.ae_sel.pack(fill="x")
        ctrl = ttk.Frame(self); ctrl.pack(fill="x", padx=10, pady=6)
        _btn(ctrl,"Add Files...",self._add_files).pack(side="left",padx=2)
        _btn(ctrl,"Add Folder...",self._add_folder).pack(side="left",padx=2)
        _btn(ctrl,"Clear List",self._clear).pack(side="left",padx=2)
        self.count_lbl = _label(ctrl,"0 files queued",style="Dim.TLabel"); self.count_lbl.pack(side="left",padx=12)
        _btn(ctrl,"Send All (C-STORE)",self._do_cstore,style="Primary.TButton").pack(side="right",padx=2)
        lf = _lf(self,"Files to Send"); lf.pack(fill="both",expand=True,padx=10,pady=4)
        self.listbox = tk.Listbox(lf,bg="white",fg="#1a1a1a",selectbackground="#dbeafe",selectforeground="#1e3a5f",font=FONT_MONO,bd=1,relief="solid",activestyle="none")
        sb = ttk.Scrollbar(lf,orient="vertical",command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        lf2, self.log = _log_frame(self,height=7); lf2.pack(fill="x",padx=10,pady=(0,6))

    def _add_files(self):
        files = filedialog.askopenfilenames(title="Select DICOM files",filetypes=[("DICOM","*.dcm *.DCM"),("All","*.*")])
        for f in files:
            if f not in self._files: self._files.append(f); self.listbox.insert("end",f)
        self.count_lbl.configure(text=f"{len(self._files)} files queued")

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Select folder with DICOM files")
        if not folder: return
        for root_dir, _, files in os.walk(folder):
            for f in files:
                path = os.path.join(root_dir,f)
                if path not in self._files: self._files.append(path); self.listbox.insert("end",path)
        self.count_lbl.configure(text=f"{len(self._files)} files queued")

    def _clear(self):
        self._files.clear(); self.listbox.delete(0,"end"); self.count_lbl.configure(text="0 files queued")

    def _do_cstore(self):
        if not self._files: messagebox.showwarning("C-STORE","No files added."); return
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
        self.ae_sel = AESelector(top, self.app.config, "Worklist SCP"); self.ae_sel.pack(fill="x")
        qf = _lf(top,"Query Filters  (leave blank = match all)"); qf.pack(fill="x",pady=(8,0))
        qf_grid = ttk.Frame(qf); qf_grid.pack(fill="x")
        for i, (lbl,attr) in enumerate([("Patient ID:","pid_var"),("Patient Name:","pname_var"),("Sched. Date:","date_var"),("Modality:","mod_var"),("Accession #:","acc_var"),("Station AET:","aet_var")]):
            r, c = divmod(i,3)
            fr = ttk.Frame(qf_grid); fr.grid(row=r,column=c,sticky="w",padx=8,pady=3)
            _label(fr,lbl).pack(side="left")
            var = tk.StringVar(); setattr(self,attr,var)
            _entry(fr,textvariable=var,width=18).pack(side="left",padx=4)
        ctrl = ttk.Frame(top); ctrl.pack(fill="x",pady=(8,0))
        _btn(ctrl,"Query Worklist",self._do_dmwl,style="Primary.TButton").pack(side="left",padx=2)
        _btn(ctrl,"Export to CSV...",self._export_csv).pack(side="left",padx=4)
        self.count_lbl = _label(ctrl,"",style="Dim.TLabel"); self.count_lbl.pack(side="left",padx=12)
        rf = _lf(self,"Worklist Results  (double-click a row to view all DICOM tags)"); rf.pack(fill="both",expand=True,padx=10,pady=6)
        cols = ("PatientID","PatientName","Accession","Modality","ScheduledDate","StationAET","Procedure")
        self.tree = ttk.Treeview(rf,columns=cols,show="headings",height=12)
        for c, w in zip(cols,[100,150,120,75,110,120,200]):
            self.tree.heading(c,text=c); self.tree.column(c,width=w,minwidth=40)
        sb = ttk.Scrollbar(rf,orient="vertical",command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        self.tree.bind("<Double-1>",self._show_detail)
        lf2, self.log = _log_frame(self,height=4); lf2.pack(fill="x",padx=10,pady=(0,6))

    def _show_detail(self,_=None):
        sel = self.tree.selection()
        if not sel: return
        idx = self.tree.index(sel[0])
        if idx >= len(self._datasets): return
        ds = self._datasets[idx]; pid = getattr(ds,"PatientID",""); pname = str(getattr(ds,"PatientName",""))
        _show_dicom_detail(self,ds,title=f"Worklist Item - {pname} ({pid}) - All DICOM Tags")

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
        if ds is None: self.log.append("pydicom not available","err"); return
        self.tree.delete(*self.tree.get_children()); self._datasets.clear()
        self.log.append(f"DMWL query -> {ae['ae_title']}@{ae['host']}:{ae['port']}")
        def run():
            try:
                from dicom.operations import dmwl_find
                station_aet = self.aet_var.get().strip()
                calling_ae = station_aet if station_aet else local
                ok, results, msg = dmwl_find(calling_ae, ae["host"], ae["port"], ae["ae_title"], ds, log_callback=lambda m: self.log.append(m))
                self.log.append(msg); self.count_lbl.configure(text=f"{len(results)} item(s) returned")
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
        if not self._datasets: messagebox.showinfo("Export","No results to export."); return
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
        self.ae_sel = AESelector(top,self.app.config,"Storage Commitment SCP"); self.ae_sel.pack(fill="x")
        ctrl = ttk.Frame(self); ctrl.pack(fill="x",padx=10,pady=6)
        _btn(ctrl,"Load UIDs from DICOM files...",self._load_from_files).pack(side="left",padx=2)
        _btn(ctrl,"Clear",self._clear_uids).pack(side="left",padx=4)
        self.uid_count = _label(ctrl,"0 UIDs",style="Dim.TLabel"); self.uid_count.pack(side="left",padx=12)
        _btn(ctrl,"Send N-ACTION (Commit)",self._do_commit,style="Primary.TButton").pack(side="right",padx=2)
        lf = _lf(self,"SOP Instance UIDs"); lf.pack(fill="both",expand=True,padx=10,pady=4)
        self.listbox = tk.Listbox(lf,bg="white",fg="#1a1a1a",selectbackground="#dbeafe",selectforeground="#1e3a5f",font=FONT_MONO,bd=1,relief="solid",activestyle="none")
        sb = ttk.Scrollbar(lf,orient="vertical",command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        lf2, self.log = _log_frame(self,height=7); lf2.pack(fill="x",padx=10,pady=(0,6))

    def _load_from_files(self):
        files = filedialog.askopenfilenames(title="Select DICOM files",filetypes=[("DICOM","*.dcm *.DCM"),("All","*.*")])
        if not files: return
        try:
            import pydicom
            for f in files:
                ds = pydicom.dcmread(f,stop_before_pixels=True); uid = str(getattr(ds,"SOPInstanceUID",""))
                if uid and uid not in self._uids: self._uids.append(uid); self.listbox.insert("end",uid)
            self.uid_count.configure(text=f"{len(self._uids)} UIDs")
        except Exception as e: messagebox.showerror("Error",str(e))

    def _clear_uids(self):
        self._uids.clear(); self.listbox.delete(0,"end"); self.uid_count.configure(text="0 UIDs")

    def _do_commit(self):
        if not self._uids: messagebox.showwarning("Storage Commitment","No UIDs loaded."); return
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
        self.ae_sel = AESelector(top,self.app.config,"IOCM SCP"); self.ae_sel.pack(fill="x")
        cf = _lf(top,"Instance Availability Notification (N-CREATE)"); cf.pack(fill="x",pady=(8,0))
        gf = ttk.Frame(cf); gf.pack(fill="x")
        for i,(lbl,attr,default) in enumerate([("Patient ID:","iocm_pid",""),("Study UID:","iocm_suid",""),("Series UID:","iocm_seruid",""),("SOP Class UID:","iocm_sopclass",""),("SOP Inst UID:","iocm_sopinst",""),("Availability:","iocm_avail","ONLINE")]):
            r, c = divmod(i,2)
            fr = ttk.Frame(gf); fr.grid(row=r,column=c,sticky="w",padx=8,pady=3)
            _label(fr,lbl).pack(side="left")
            var = tk.StringVar(value=default); setattr(self,attr,var)
            _entry(fr,textvariable=var,width=36).pack(side="left",padx=4)
        ctrl = ttk.Frame(top); ctrl.pack(fill="x",pady=(8,0))
        _btn(ctrl,"Send N-CREATE (Delete Notification)",self._do_iocm,style="Danger.TButton").pack(side="left",padx=2)
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
        send_tab = ttk.Frame(nb); nb.add(send_tab,text="  Send HL7  "); self._build_sender(send_tab)
        recv_tab = ttk.Frame(nb); nb.add(recv_tab,text="  Receive HL7  "); self._build_receiver(recv_tab)

    def _build_sender(self, parent):
        top = ttk.Frame(parent); top.pack(fill="x",padx=10,pady=8)
        conn_lf = _lf(top,"Destination"); conn_lf.pack(fill="x")
        row = ttk.Frame(conn_lf); row.pack(fill="x")
        for lbl,attr,val,w in [("Host:","hl7_host_var","127.0.0.1",22),("Port:","hl7_port_var","2575",6)]:
            _label(row,lbl).pack(side="left",padx=(0,4))
            var = tk.StringVar(value=val); setattr(self,attr,var)
            _entry(row,textvariable=var,width=w).pack(side="left",padx=(0,16))
        tmpl_lf = _lf(top,"Message Template"); tmpl_lf.pack(fill="x",pady=(8,0))
        tr = ttk.Frame(tmpl_lf); tr.pack(fill="x",pady=(0,6))
        _label(tr,"Template:").pack(side="left")

        # Load template names from disk and populate the dropdown
        self._template_data = self._load_templates_from_disk()
        tmpl_names = [t["name"] for t in self._template_data]
        self.tmpl_var = tk.StringVar(value=tmpl_names[0] if tmpl_names else "")
        self.tmpl_cb = ttk.Combobox(tr, textvariable=self.tmpl_var,
            values=tmpl_names, state="readonly", width=40)
        self.tmpl_cb.pack(side="left", padx=6)
        _btn(tr,"Load Template",self._load_template).pack(side="left",padx=4)
        _btn(tr,"Refresh",self._refresh_templates).pack(side="left",padx=2)

        # Description label shown below the dropdown
        self.tmpl_desc_lbl = _label(tmpl_lf,"",style="Dim.TLabel")
        self.tmpl_desc_lbl.pack(anchor="w",pady=(0,4))
        self.tmpl_cb.bind("<<ComboboxSelected>>", self._on_tmpl_selected)
        self._on_tmpl_selected()  # populate description for initial selection
        vf = ttk.Frame(tmpl_lf); vf.pack(fill="x")
        fill_fields = [("Patient ID:","tmpl_pid",""),("Name (LAST^FIRST):","tmpl_name",""),("DOB (YYYYMMDD):","tmpl_dob",""),("Sex (M/F/U):","tmpl_sex","M"),("Accession #:","tmpl_acc",""),("Proc Code:","tmpl_code",""),("Proc Description:","tmpl_desc",""),("Modality:","tmpl_mod","CT"),("Sending App:","tmpl_sa","RIS"),("Sending Facility:","tmpl_sf","HOSPITAL"),("Receiving App:","tmpl_ra","PACS"),("Receiving Facility:","tmpl_rf","HOSPITAL")]
        for i,(lbl,attr,default) in enumerate(fill_fields):
            r, c = divmod(i,2)
            fr = ttk.Frame(vf); fr.grid(row=r,column=c,sticky="w",padx=6,pady=2)
            _label(fr,lbl).pack(side="left")
            var = tk.StringVar(value=default); setattr(self,attr,var)
            _entry(fr,textvariable=var,width=22).pack(side="left",padx=4)
        self.send_debug_var = tk.BooleanVar(value=False)
        dbg_row = ttk.Frame(parent); dbg_row.pack(fill="x",padx=10,pady=(2,0))
        ttk.Checkbutton(dbg_row,text="Show raw MLLP bytes in log",variable=self.send_debug_var).pack(side="left")
        msg_lf = _lf(parent,"Message to Send  (edit directly)"); msg_lf.pack(fill="both",expand=True,padx=10,pady=(4,4))
        self.hl7_msg_text = tk.Text(msg_lf,bg="white",fg="#1a1a1a",font=FONT_MONO,height=8,wrap="none",bd=1,relief="solid")
        sb_msg = ttk.Scrollbar(msg_lf,orient="vertical",command=self.hl7_msg_text.yview)
        self.hl7_msg_text.configure(yscrollcommand=sb_msg.set)
        self.hl7_msg_text.pack(side="left",fill="both",expand=True); sb_msg.pack(side="right",fill="y")
        ctrl = ttk.Frame(parent); ctrl.pack(fill="x",padx=10,pady=4)
        _btn(ctrl,"Send via MLLP",self._do_hl7_send,style="Primary.TButton").pack(side="left",padx=2)
        _btn(ctrl,"Clear Message",lambda: self.hl7_msg_text.delete("1.0","end")).pack(side="left",padx=4)
        lf_log, self.hl7_send_log = _log_frame(parent,height=5); lf_log.pack(fill="x",padx=10,pady=(0,6))

    def _build_receiver(self, parent):
        top = ttk.Frame(parent); top.pack(fill="x",padx=10,pady=8)
        cfg_lf = _lf(top,"Listener Configuration"); cfg_lf.pack(fill="x")
        row = ttk.Frame(cfg_lf); row.pack(fill="x")
        _label(row,"Listen Port:").pack(side="left",padx=(0,4))
        self.hl7_listen_port_var = tk.StringVar(value=str(self.app.config.get("hl7",{}).get("listen_port",2575)))
        _entry(row,textvariable=self.hl7_listen_port_var,width=8).pack(side="left",padx=(0,16))
        self.recv_debug_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row,text="Show raw MLLP bytes in log",variable=self.recv_debug_var).pack(side="left",padx=8)
        self.recv_btn = _btn(top,">>  Start HL7 Listener",self._toggle_listener,style="Primary.TButton")
        self.recv_btn.pack(fill="x",pady=(8,0))
        self.recv_status = _label(top,"Listener not running",style="Dim.TLabel"); self.recv_status.pack(anchor="w",pady=(4,0))
        msg_lf = _lf(parent,"Received Messages"); msg_lf.pack(fill="both",expand=True,padx=10,pady=(4,4))
        ctrl_row = ttk.Frame(msg_lf); ctrl_row.pack(fill="x",pady=(0,4))
        _btn(ctrl_row,"Clear",self._clear_received).pack(side="right")
        self.recv_count_lbl = _label(ctrl_row,"0 messages received",style="Dim.TLabel"); self.recv_count_lbl.pack(side="left")
        self._recv_msg_count = 0
        self.hl7_recv_text = tk.Text(msg_lf,bg="white",fg="#1a1a1a",font=FONT_MONO,wrap="none",bd=1,relief="solid",state="disabled")
        sb_rv = ttk.Scrollbar(msg_lf,orient="vertical",command=self.hl7_recv_text.yview)
        sb_rh = ttk.Scrollbar(msg_lf,orient="horizontal",command=self.hl7_recv_text.xview)
        self.hl7_recv_text.configure(yscrollcommand=sb_rv.set,xscrollcommand=sb_rh.set)
        sb_rh.pack(side="bottom",fill="x"); self.hl7_recv_text.pack(side="left",fill="both",expand=True); sb_rv.pack(side="right",fill="y")
        lf_log, self.hl7_recv_log = _log_frame(parent,height=4); lf_log.pack(fill="x",padx=10,pady=(0,6))

    def _on_tmpl_selected(self, _=None):
        """Update the description label when the user picks a different template."""
        name = self.tmpl_var.get()
        tmpl = next((t for t in self._template_data if t["name"] == name), None)
        desc = tmpl["description"] if tmpl else ""
        self.tmpl_desc_lbl.configure(text=desc)

    def _refresh_templates(self):
        """Reload template files from disk and refresh the dropdown."""
        self._template_data = self._load_templates_from_disk()
        tmpl_names = [t["name"] for t in self._template_data]
        prev = self.tmpl_var.get()
        self.tmpl_cb["values"] = tmpl_names
        # Keep current selection if still available
        if prev in tmpl_names:
            self.tmpl_var.set(prev)
        elif tmpl_names:
            self.tmpl_var.set(tmpl_names[0])
        self._on_tmpl_selected()
        self.hl7_send_log.append(f"Templates refreshed ({len(tmpl_names)} loaded)")

    def _load_template(self):
        """Fill the message editor with the selected template, substituting placeholders."""
        name = self.tmpl_var.get()
        tmpl = next((t for t in self._template_data if t["name"] == name), None)
        if not tmpl:
            messagebox.showwarning("Load Template", "No template selected or template not found.")
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
        if not msg: messagebox.showwarning("HL7 Send","No message to send."); return
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
        except ValueError: messagebox.showerror("Error","Invalid port number."); return
        debug = self.recv_debug_var.get()
        self._listener_running = True
        self.recv_btn.configure(text="[]  Stop HL7 Listener",style="Danger.TButton")
        self.recv_status.configure(text=f"Listening on port {port}...")
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
                self.recv_btn.configure(text=">>  Start HL7 Listener",style="Primary.TButton")
                self.recv_status.configure(text="Listener failed")
        threading.Thread(target=run, daemon=True).start()

    def _stop_listener(self):
        self._listener_running = False
        self.recv_btn.configure(text=">>  Start HL7 Listener",style="Primary.TButton")
        self.recv_status.configure(text="Listener stopped")
        self.hl7_recv_log.append("Listener stopped")

    def _append_received(self, msg_str, addr):
        self._recv_msg_count += 1
        self.recv_count_lbl.configure(text=f"{self._recv_msg_count} message(s) received")
        ts = datetime.now().strftime("%H:%M:%S")
        display = f"{'─'*60}\n[{ts}]  From {addr[0]}:{addr[1]}\n{msg_str.replace(chr(13), chr(10))}\n"
        self.hl7_recv_text.configure(state="normal"); self.hl7_recv_text.insert("end",display)
        self.hl7_recv_text.see("end"); self.hl7_recv_text.configure(state="disabled")
        self.hl7_recv_log.append(f"Received message from {addr[0]}:{addr[1]}")

    def _clear_received(self):
        self.hl7_recv_text.configure(state="normal"); self.hl7_recv_text.delete("1.0","end")
        self.hl7_recv_text.configure(state="disabled")
        self._recv_msg_count = 0; self.recv_count_lbl.configure(text="0 messages received")


class SCPListenerTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._scp_running = False; self._build()

    def _build(self):
        top = ttk.Frame(self); top.pack(fill="x",padx=10,pady=8)
        cfg_lf = _lf(top,"Listener Configuration"); cfg_lf.pack(fill="x")
        row = ttk.Frame(cfg_lf); row.pack(fill="x")
        _label(row,"AE Title:").pack(side="left",padx=(0,4))
        self.scp_ae_var = tk.StringVar(value=self.app.config.get("local_ae",{}).get("ae_title","PACSADMIN"))
        _entry(row,textvariable=self.scp_ae_var,width=16).pack(side="left",padx=(0,20))
        _label(row,"Port:").pack(side="left",padx=(0,4))
        self.scp_port_var = tk.StringVar(value=str(self.app.config.get("local_ae",{}).get("port",11112)))
        _entry(row,textvariable=self.scp_port_var,width=8).pack(side="left",padx=(0,20))
        save_row = ttk.Frame(cfg_lf); save_row.pack(fill="x",pady=(6,0))
        _label(save_row,"Save received files to:").pack(side="left",padx=(0,6))
        self.save_dir_var = tk.StringVar(value=os.path.expanduser("~/DICOM_Received"))
        _entry(save_row,textvariable=self.save_dir_var,width=40).pack(side="left")
        _btn(save_row,"Browse...",self._browse_save_dir).pack(side="left",padx=4)
        self.scp_btn = _btn(top,">>  Start DICOM Storage Listener",self._toggle_scp,style="Primary.TButton")
        self.scp_btn.pack(fill="x",pady=(10,0))
        self.scp_status = _label(top,"Listener not running",style="Dim.TLabel"); self.scp_status.pack(anchor="w",pady=(4,0))
        lf = _lf(self,"Received DICOM Files"); lf.pack(fill="both",expand=True,padx=10,pady=(8,4))
        ctrl = ttk.Frame(lf); ctrl.pack(fill="x",pady=(0,4))
        _btn(ctrl,"Clear List",self._clear_list).pack(side="right")
        self.recv_file_count = _label(ctrl,"0 files received",style="Dim.TLabel"); self.recv_file_count.pack(side="left")
        self._file_count = 0
        self.recv_listbox = tk.Listbox(lf,bg="white",fg="#1a1a1a",selectbackground="#dbeafe",selectforeground="#1e3a5f",font=FONT_MONO,bd=1,relief="solid",activestyle="none")
        sb = ttk.Scrollbar(lf,orient="vertical",command=self.recv_listbox.yview)
        self.recv_listbox.configure(yscrollcommand=sb.set)
        self.recv_listbox.pack(side="left",fill="both",expand=True); sb.pack(side="right",fill="y")
        lf2, self.log = _log_frame(self,height=6); lf2.pack(fill="x",padx=10,pady=(0,6))

    def _browse_save_dir(self):
        d = filedialog.askdirectory(title="Select folder to save received DICOM files")
        if d: self.save_dir_var.set(d)

    def _clear_list(self):
        self.recv_listbox.delete(0,"end"); self._file_count = 0
        self.recv_file_count.configure(text="0 files received")

    def _toggle_scp(self):
        if self._scp_running: self._stop_scp()
        else: self._start_scp()

    def _start_scp(self):
        ae_title = self.scp_ae_var.get().strip()
        try: port = int(self.scp_port_var.get().strip())
        except ValueError: messagebox.showerror("Error","Invalid port."); return
        save_dir = self.save_dir_var.get().strip(); os.makedirs(save_dir,exist_ok=True)
        self._scp_running = True
        self.scp_btn.configure(text="[]  Stop DICOM Storage Listener",style="Danger.TButton")
        self.scp_status.configure(text=f"Listening as {ae_title} on port {port}")
        self.log.append(f"Starting DICOM Storage SCP: {ae_title}  port={port}  save to {save_dir}")
        def run():
            try:
                from dicom.operations import run_storage_scp
                run_storage_scp(ae_title,port,save_dir,on_received=self._on_file_received,on_log=lambda m: self.log.append(m),running_flag=lambda: self._scp_running)
            except Exception as e:
                self.log.append(f"SCP error: {e}","err"); self._scp_running = False
                self.scp_btn.configure(text=">>  Start DICOM Storage Listener",style="Primary.TButton")
                self.scp_status.configure(text="Listener stopped (error)")
        threading.Thread(target=run, daemon=True).start()

    def _stop_scp(self):
        self._scp_running = False
        self.scp_btn.configure(text=">>  Start DICOM Storage Listener",style="Primary.TButton")
        self.scp_status.configure(text="Listener stopping..."); self.log.append("Stopping DICOM Storage SCP...")

    def _on_file_received(self, path):
        self._file_count += 1
        self.recv_file_count.configure(text=f"{self._file_count} file(s) received")
        self.recv_listbox.insert("end",path); self.recv_listbox.see("end")


class SettingsTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._build()

    def _build(self):
        lf1 = _lf(self,"Local AE Configuration"); lf1.pack(fill="x",padx=10,pady=8)
        r1 = ttk.Frame(lf1); r1.pack(fill="x")
        _label(r1,"AE Title:").grid(row=0,column=0,sticky="w",padx=(0,6))
        self.local_ae_var = tk.StringVar(value=self.app.config.get("local_ae",{}).get("ae_title","PACSADMIN"))
        _entry(r1,textvariable=self.local_ae_var,width=20).grid(row=0,column=1,padx=(0,20))
        _label(r1,"Port:").grid(row=0,column=2,sticky="w",padx=(0,6))
        self.local_port_var = tk.StringVar(value=str(self.app.config.get("local_ae",{}).get("port",11112)))
        _entry(r1,textvariable=self.local_port_var,width=8).grid(row=0,column=3)
        lf2 = _lf(self,"Saved Remote AE Presets"); lf2.pack(fill="x",padx=10,pady=4)
        cols = ("name","ae_title","host","port")
        self.ae_tree = ttk.Treeview(lf2,columns=cols,show="headings",height=6)
        for c, w in zip(cols,[130,130,180,70]):
            self.ae_tree.heading(c,text=c); self.ae_tree.column(c,width=w)
        sb_ae = ttk.Scrollbar(lf2,orient="vertical",command=self.ae_tree.yview)
        self.ae_tree.configure(yscrollcommand=sb_ae.set)
        self.ae_tree.pack(side="left",fill="both",expand=True); sb_ae.pack(side="right",fill="y")
        self._reload_ae_tree()
        add_frame = ttk.Frame(lf2); add_frame.pack(fill="x",pady=4)
        for lbl,attr,w in [("Name:","new_name",14),("AE Title:","new_aet",12),("Host:","new_host",20),("Port:","new_port",6)]:
            _label(add_frame,lbl).pack(side="left",padx=(4,2))
            var = tk.StringVar(); setattr(self,attr,var)
            _entry(add_frame,textvariable=var,width=w).pack(side="left",padx=2)
        _btn(add_frame,"+ Add",self._add_ae,style="Primary.TButton").pack(side="left",padx=6)
        _btn(add_frame,"Delete Selected",self._del_ae,style="Danger.TButton").pack(side="left",padx=2)
        lf3 = _lf(self,"HL7 Settings"); lf3.pack(fill="x",padx=10,pady=4)
        r3 = ttk.Frame(lf3); r3.pack(fill="x")
        _label(r3,"Default HL7 Listen Port:").pack(side="left")
        self.hl7_port_var = tk.StringVar(value=str(self.app.config.get("hl7",{}).get("listen_port",2575)))
        _entry(r3,textvariable=self.hl7_port_var,width=6).pack(side="left",padx=4)
        btn_row = ttk.Frame(self); btn_row.pack(padx=10,pady=12,anchor="w")
        _btn(btn_row,"Save Settings",self._save,style="Primary.TButton").pack(side="left",padx=4)
        self.save_lbl = _label(btn_row,"",style="Dim.TLabel"); self.save_lbl.pack(side="left",padx=8)

    def _reload_ae_tree(self):
        self.ae_tree.delete(*self.ae_tree.get_children())
        for ae in self.app.config.get("remote_aes",[]):
            self.ae_tree.insert("","end",values=(ae.get("name",""),ae.get("ae_title",""),ae.get("host",""),ae.get("port",104)))

    def _add_ae(self):
        entry = {"name":self.new_name.get().strip(),"ae_title":self.new_aet.get().strip(),"host":self.new_host.get().strip(),"port":int(self.new_port.get().strip() or "104")}
        if not entry["name"]: messagebox.showwarning("Add AE","Name is required."); return
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
        save_config(self.app.config)
        self.save_lbl.configure(text=f"Saved  {datetime.now().strftime('%H:%M:%S')}")


class HelpTab(ttk.Frame):
    SECTIONS = [
        ("C-FIND / Query-Retrieve",
         "Query a remote PACS for patients and studies.\n\nC-ECHO (Ping) - tests connectivity.\nRun C-FIND - searches using any combination of Patient ID, Name, Accession, Date, Modality, or Study UID.\nDouble-click a result row to see all DICOM tags.\nC-MOVE - instructs the PACS to push the study to a destination AE.",
         [("DICOM PS3.4 §C – Query/Retrieve Service Class (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_C")]),
        ("C-STORE (Send Files)",
         "Send DICOM files from disk to a remote Storage SCP.\nAdd Files or Add Folder, then Send All.",
         [("DICOM PS3.4 §B – Storage Service Class (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_B")]),
        ("DMWL - Modality Worklist",
         "Query a Worklist SCP for scheduled procedures.\n\nStation AET - used as the CALLING AE title when set.\nSome PACS (e.g. Sectra) only return items for the modality AE that polls the worklist,\nso set Station AET to the modality's own AE title.\n\nDouble-click a row to see all DICOM tags including nested SPS sequences.",
         [("DICOM PS3.4 §K – Modality Worklist Management (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_K")]),
        ("Storage Commitment",
         "Verify that a PACS has permanently stored instances.\nLoad UIDs from DICOM files, then Send N-ACTION.\nThe PACS returns committed vs failed counts.",
         [("DICOM PS3.4 §J – Storage Commitment Service Class (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_J")]),
        ("IOCM - Instance Availability",
         "Send an Instance Availability Notification (N-CREATE).\nUsed for deletion or availability-change workflows.\nFollows DICOM PS 3.4 Annex KK.",
         [("DICOM PS3.4 §KK – Instance Availability Notification (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_KK")]),
        ("HL7 - Send",
         "Send HL7 v2 messages over MLLP.\n\nTemplates:\n  ORM^O01  - Radiology order (MSH/PID/PV1/ORC/OBR/ZDS)\n  ORU^R01  - Radiology report with OBX findings\n  ADT^A04  - Patient registration (EVN/PID/PV1/PV2)\n  ADT^A08  - Update patient information\n  ADT^A23  - Delete patient visit\n  SIU^S12  - Schedule appointment (SCH/AIS/AIP/AIL)\n  SIU^S15  - Cancel appointment\n  QBP^Q22  - IHE PDQ patient demographics query\n  OML^O21  - Lab order with SPM specimen segment\n\nShow raw MLLP bytes - logs every byte including 0x0B and 0x1C 0x0D framing.",
         [("ORM^O01 – Radiology Order (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ORM_O01"),
          ("ORU^R01 – Radiology Report (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ORU_R01"),
          ("ADT^A04 – Register Patient (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A04"),
          ("ADT^A08 – Update Patient (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A08"),
          ("ADT^A23 – Delete Visit (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/ADT_A23"),
          ("SIU^S12 – Schedule Appointment (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/SIU_S12"),
          ("SIU^S15 – Cancel Appointment (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/SIU_S15"),
          ("QBP^Q22 – Patient Demographics Query (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/QBP_Q22"),
          ("OML^O21 – Lab Order (Caristix HL7 v2.4)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents/OML_O21")]),
        ("HL7 - Receive",
         "Run an MLLP listener.\nAutomatic AA ACK sent for every message received.\nShow raw MLLP bytes - logs full raw packets.",
         [("HL7 v2.4 Message Definitions (Caristix)", "https://hl7-definition.caristix.com/v2/HL7v2.4/TriggerEvents")]),
        ("DICOM Storage Listener",
         "Runs a C-STORE SCP that accepts incoming DICOM objects and saves them to disk.\nAE Title and Port must match the sending device's configuration.\nAccepts all SOP classes including CT, MR, DX, XA, SR, PR, KO, RT, PDF.",
         [("DICOM PS3.4 §B – Storage Service Class (NEMA)", "https://dicom.nema.org/medical/dicom/current/output/html/part04.html#chapter_B")]),
        ("Settings",
         "Local AE Title / Port - how this tool identifies itself.\nRemote AE Presets - saved AEs available in all tab dropdowns.\nHL7 Listen Port - default port for the HL7 Receiver.\nSettings saved to: %USERPROFILE%\\.pacs_admin_tool\\config.json",
         []),
    ]

    def __init__(self, parent, app):
        super().__init__(parent); self.app = app; self._build()

    def _build(self):
        outer = ttk.Frame(self); outer.pack(fill="both",expand=True,padx=10,pady=10)
        left = ttk.Frame(outer); left.pack(side="left",fill="y",padx=(0,10))
        _label(left,"Topics",style="H1.TLabel").pack(anchor="w",pady=(0,6))
        self.topic_lb = tk.Listbox(left,bg="white",fg="#1a1a1a",selectbackground="#dbeafe",selectforeground="#1e3a5f",font=FONT,relief="solid",bd=1,activestyle="none",width=28)
        for title, *_ in self.SECTIONS: self.topic_lb.insert("end","  "+title)
        self.topic_lb.pack(fill="y",expand=True)
        self.topic_lb.bind("<<ListboxSelect>>",self._show_section); self.topic_lb.selection_set(0)
        right = ttk.Frame(outer); right.pack(side="left",fill="both",expand=True)
        self.title_lbl = _label(right,self.SECTIONS[0][0],style="H1.TLabel"); self.title_lbl.pack(anchor="w",pady=(0,8))
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
        title, content, links = self.SECTIONS[idx]; self.title_lbl.configure(text=title)
        self.text.configure(state="normal"); self.text.delete("1.0","end")
        self.text.insert("1.0", content.strip())
        if links:
            self.text.insert("end", "\n\nOfficial Documentation:\n", "refs_label")
            for label, url in links:
                tag = f"link_{url}"
                self.text.insert("end", f"  \u2197 {label}\n", ("link", tag))
                self.text.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
                self.text.tag_bind(tag, "<Enter>", lambda e: self.text.configure(cursor="hand2"))
                self.text.tag_bind(tag, "<Leave>", lambda e: self.text.configure(cursor=""))
        self.text.configure(state="disabled")


# ---------------------------------------------------------------------------
#  Main Application  -  this is the class that main.py imports
# ---------------------------------------------------------------------------
class PACSAdminApp:
    def __init__(self):
        self.config = load_config()
        self.root = tk.Tk()
        self.root.title("PACS Admin Tool")
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
        tk.Label(hdr,text="PACS Admin Tool",font=FONT_H1,bg="#ffffff",fg="#1a1a1a").pack(side="left",padx=16,pady=8)
        tk.Frame(hdr,bg="#e0e0e0",width=1).pack(side="left",fill="y",padx=0,pady=8)
        tk.Label(hdr,text="DICOM & HL7 Administration Utility",font=FONT,bg="#ffffff",fg="#888888").pack(side="left",padx=12)
        nb = ttk.Notebook(self.root); nb.pack(fill="both",expand=True,padx=0,pady=0)
        for label, cls in [
            ("  C-FIND / Q-R  ", CFindTab), ("  C-STORE  ", CStoreTab),
            ("  Worklist (DMWL)  ", DMWLTab), ("  Storage Commit  ", StorageCommitTab),
            ("  IOCM  ", IOCMTab), ("  HL7  ", HL7Tab),
            ("  DICOM Receiver  ", SCPListenerTab), ("  Settings  ", SettingsTab),
            ("  Help  ", HelpTab),
        ]:
            nb.add(cls(nb, self), text=label)
        sb = tk.Frame(self.root,bg="#e8e8e8",height=24)
        sb.pack(fill="x",side="bottom"); sb.pack_propagate(False)
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(sb,textvariable=self._status_var,font=("Segoe UI",8),bg="#e8e8e8",fg="#666666").pack(side="left",padx=10)

    def run(self):
        self.root.mainloop()


def main():
    app = PACSAdminApp()
    app.run()


if __name__ == "__main__":
    main()
