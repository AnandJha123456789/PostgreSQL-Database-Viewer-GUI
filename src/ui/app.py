import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
import threading
import itertools
import csv
import json
import logging
import os
import copy
from datetime import datetime
from typing import Any, List, Tuple, Optional

from ..config import DatabaseConfig
from ..database import DatabaseConnection
from ..models import Filter, FilterState, SortCriterion, AppState
from .components import FlowFrame

class DatabaseQueryGUI:
    def __init__(self, root: tk.Tk, db_connection: DatabaseConnection):
        self.root = root
        self.db = db_connection
        self.logger = logging.getLogger(__name__)
        
        # Application state variables
        self.current_schema = ""
        self.current_table = ""
        self.row_limit = 50
        self.column_names: List[str] = []
        self.data_rows: List[List[Any]] = []
        self.available_tables: List[str] = []
        self.last_query_results: Optional[List[List[Any]]] = None
        
        # State for manual query editing
        self._programmatic_update = False
        
        # Filter and sorting management
        self._filter_id_counter = itertools.count()
        self.filters: List[Filter] = []
        self.sorting: List[SortCriterion] = []

        # State for fuzzy table search
        self.all_tables_cache: List[Tuple[str, str]] = []
        self.is_fuzzy_finding = False
        
        # --- History Management ---
        self.history: List[AppState] = []
        self.history_index = -1 # Points to current state
        self.max_history = 100
        self.is_navigating_history = False # Flag to prevent loops

        self.setup_ui()
        
        # Connect on startup if config is present
        if self.db.connect():
             self.load_schemas()

    def get_saved_queries_dir(self):
        """
        Returns the directory one level up from the script's location
        and ensures a specified folder exists within that parent directory.
        """
        folder_name = "saved_queries"

        # 1. Get the directory where the script is running
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # 2. Go one directory up (the parent directory)
        parent_dir = os.path.dirname(script_dir)

        # 3. Define the path for the new folder inside the parent directory
        target_folder_path = os.path.join(parent_dir, folder_name)

        # 4. Create the folder if it doesn't exist
        os.makedirs(target_folder_path, exist_ok=True)

        # 5. Return the path to the ensured folder
        return target_folder_path

    def setup_ui(self):
        self.root.title("DB_GUI_Viewer")
                
        self.root.geometry("1600x900")
        self.setup_treeview_style()
        
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)

        # --- Table Selection Frame ---
        table_frame = ttk.LabelFrame(main_frame, text="Table Selection & Actions", padding="5")
        table_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        
        # History Buttons
        history_frame = ttk.Frame(table_frame)
        history_frame.grid(row=0, column=0, padx=(0, 10))
        self.btn_back = ttk.Button(history_frame, text="<", width=3, command=self.go_back, state=tk.DISABLED)
        self.btn_back.pack(side=tk.LEFT, padx=1)
        self.btn_fwd = ttk.Button(history_frame, text=">", width=3, command=self.go_forward, state=tk.DISABLED)
        self.btn_fwd.pack(side=tk.LEFT, padx=1)

        ttk.Label(table_frame, text="Schema:").grid(row=0, column=1, padx=(0, 5))
        self.schema_var = tk.StringVar()
        self.schema_combo = ttk.Combobox(table_frame, textvariable=self.schema_var, state="readonly", width=20)
        self.schema_combo.grid(row=0, column=2, padx=(0, 10))
        self.schema_combo.bind('<<ComboboxSelected>>', self.on_schema_selected)
        
        ttk.Label(table_frame, text="Table:").grid(row=0, column=3, padx=(10, 5))
        self.table_var = tk.StringVar()
        self.table_combo = ttk.Combobox(table_frame, textvariable=self.table_var, state="normal", width=30)
        self.table_combo.grid(row=0, column=4, sticky="ew")
        table_frame.columnconfigure(4, weight=1) # Make table combo expand
        self.table_combo.bind('<<ComboboxSelected>>', self.on_table_selected)
        self.table_combo.bind('<KeyRelease>', self.on_table_search)
        self.table_combo.bind('<Return>', self.on_table_enter_key)
        self.table_combo.bind('<FocusIn>', self.on_table_focus_in)
        self.table_combo.bind('<FocusOut>', self.on_table_focus_out)

        ttk.Label(table_frame, text="Limit:").grid(row=0, column=5, padx=(10, 5))
        self.limit_var = tk.StringVar(value="50")
        limit_entry = ttk.Entry(table_frame, textvariable=self.limit_var, width=8)
        limit_entry.grid(row=0, column=6, padx=(0, 10))
        limit_entry.bind('<Return>', lambda event: self.on_limit_changed())

        self.refresh_table_btn = ttk.Button(table_frame, text="Refresh Data", command=self.refresh_current_table)
        self.refresh_table_btn.grid(row=0, column=7)

        self.get_count_btn = ttk.Button(table_frame, text="Get Total Count", command=self.get_total_count)
        self.get_count_btn.grid(row=0, column=8, padx=(5, 0))
        
        self.save_csv_btn = ttk.Button(table_frame, text="Save as CSV", command=self.save_to_csv, state=tk.DISABLED)
        self.save_csv_btn.grid(row=0, column=9, padx=(5, 0))

        self.toggle_json_btn = ttk.Button(table_frame, text="Show Query & JSON Tools", command=self.toggle_middle_frame)
        self.toggle_json_btn.grid(row=0, column=10, padx=(10, 0))
        
        # --- NEW SAVED QUERY BUTTONS ---
        self.load_query_btn = ttk.Button(table_frame, text="Load Query", command=self.load_query_state)
        self.load_query_btn.grid(row=0, column=11, padx=(10, 0))

        self.save_query_btn = ttk.Button(table_frame, text="Save Query", command=self.save_query_state)
        self.save_query_btn.grid(row=0, column=12, padx=(5, 0))
        # -------------------------------

        self.copy_query_btn = ttk.Button(table_frame, text="Copy Query", command=self.copy_query_to_clipboard)
        self.copy_query_btn.grid(row=0, column=13, padx=(10, 0))
        
        self.copy_results_btn = ttk.Button(table_frame, text="Copy Query & Results", command=self.copy_query_and_results_to_clipboard, state=tk.DISABLED)
        self.copy_results_btn.grid(row=0, column=14, padx=(5, 0))

        # --- Middle Frame (Query/JSON) ---
        self.middle_frame = ttk.Frame(main_frame)
        self.middle_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.middle_frame.columnconfigure((0, 1, 2), weight=1)
        self.middle_frame.grid_remove()

        # Query Frame
        query_frame = ttk.LabelFrame(self.middle_frame, text="Current Query (Editable)", padding="5")
        query_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        query_frame.columnconfigure(0, weight=1)
        query_frame.rowconfigure(0, weight=1)
        
        self.query_text = tk.Text(query_frame, height=24, wrap=tk.WORD, undo=True)
        self.query_text.grid(row=0, column=0, sticky="nsew")
        self.query_text.bind("<KeyRelease>", self.on_query_text_modified)
        
        query_scrollbar = ttk.Scrollbar(query_frame, orient=tk.VERTICAL, command=self.query_text.yview)
        query_scrollbar.grid(row=0, column=1, sticky="ns")
        self.query_text.configure(yscrollcommand=query_scrollbar.set)
        
        query_button_frame = ttk.Frame(query_frame)
        query_button_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(5,0))
        self.run_custom_query_btn = ttk.Button(query_button_frame, text="Run Custom Query", command=self.run_custom_query, state=tk.DISABLED)
        self.run_custom_query_btn.pack(side=tk.RIGHT)
        
        # JSON Input Frame
        json_input_frame = ttk.LabelFrame(self.middle_frame, text="JSON Input", padding="5")
        json_input_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 5))
        json_input_frame.rowconfigure(0, weight=1)
        json_input_frame.columnconfigure(0, weight=1)   
        self.json_input_text = tk.Text(json_input_frame, height=24, wrap=tk.WORD, undo=True)
        self.json_input_text.grid(row=0, column=0, sticky="nsew")
        json_in_scroll = ttk.Scrollbar(json_input_frame, command=self.json_input_text.yview)
        json_in_scroll.grid(row=0, column=1, sticky="ns")
        self.json_input_text['yscrollcommand'] = json_in_scroll.set
        self.json_input_text.bind("<<Modified>>", self.on_json_input_modified)

        # JSON Output Frame
        json_output_frame = ttk.LabelFrame(self.middle_frame, text="Formatted JSON Output", padding="5")
        json_output_frame.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        json_output_frame.rowconfigure(0, weight=1)
        json_output_frame.columnconfigure(0, weight=1)
        self.json_output_text = tk.Text(json_output_frame, height=24, wrap=tk.WORD, state=tk.DISABLED, background="#fdfdfd")
        self.json_output_text.grid(row=0, column=0, sticky="nsew")
        json_out_scroll = ttk.Scrollbar(json_output_frame, command=self.json_output_text.yview)
        json_out_scroll.grid(row=0, column=1, sticky="ns")
        self.json_output_text['yscrollcommand'] = json_out_scroll.set
        self.configure_json_highlight_tags()

        # --- Filters & Sorting ---
        self._setup_controls_ui(main_frame)

        # --- Results Treeview ---
        results_frame = ttk.LabelFrame(main_frame, text="Results", padding="5")
        results_frame.grid(row=3, column=0, sticky="nsew")
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)
        
        tree_frame = ttk.Frame(results_frame)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        self.tree = ttk.Treeview(tree_frame, show='headings', style='Custom.Treeview')
        self.tree.grid(row=0, column=0, sticky="nsew")
        
        v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=v_scrollbar.set)
        
        h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=h_scrollbar.set)
        
        self.tree.bind('<Button-1>', self.on_tree_click)
        self.tree.bind('<Button-3>', self.on_tree_right_click)
        # --- NEW BINDINGS FOR JSON INSPECTION ---
        self.tree.bind('<Button-2>', self.on_tree_inspect_json) # Middle Click
        self.tree.bind('<Double-Button-3>', self.on_tree_inspect_json) # Double Right Click
        # ----------------------------------------
        self.configure_tree_tags()

        # --- Status Bar ---
        self.status_var = tk.StringVar(value="Connecting to database...")
        status_bar = ttk.Label(main_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.grid(row=4, column=0, sticky="ew", pady=(10, 0))

    def _setup_controls_ui(self, parent_frame: ttk.Frame):
        controls_frame = ttk.LabelFrame(parent_frame, text="Active Filters & Sorting", padding="10")
        controls_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        # Filter Section
        filter_header_frame = ttk.Frame(controls_frame)
        filter_header_frame.pack(fill="x", expand=True)
        filter_header_frame.columnconfigure(0, weight=1)

        ttk.Label(filter_header_frame, text="Filters:", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(filter_header_frame, text="Clear All Filters", command=self.on_clear_all_filters).grid(row=0, column=1, sticky="e")
        
        self.filters_flow_frame = FlowFrame(controls_frame)
        self.filters_flow_frame.pack(fill="x", expand=True, pady=(5, 15))

        # Sorting Section
        sorting_header_frame = ttk.Frame(controls_frame)
        sorting_header_frame.pack(fill="x", expand=True)
        sorting_header_frame.columnconfigure(0, weight=1)

        ttk.Label(sorting_header_frame, text="Sorting:", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(sorting_header_frame, text="Clear All Sorting", command=self.on_clear_all_sorting).grid(row=0, column=1, sticky="e")
        
        self.sorting_flow_frame = FlowFrame(controls_frame)
        self.sorting_flow_frame.pack(fill="x", expand=True, pady=(5, 0))

    def setup_treeview_style(self):
        style = ttk.Style()
        style.configure('Custom.Treeview', background='white', foreground='black', rowheight=25, fieldbackground='white', borderwidth=1, relief='solid')
        style.map('Custom.Treeview', background=[('selected', 'lightblue')])
        style.configure('Custom.Treeview.Heading', background='lightgray', foreground='black', borderwidth=1, relief='solid', font=("TkDefaultFont", 10, "bold"))
        style.configure('Pill.TFrame', background='#e0e0e0')
        self.tree_tags = ['evenrow', 'oddrow']

    def configure_tree_tags(self):
        self.tree.tag_configure('evenrow', background='white')
        self.tree.tag_configure('oddrow', background='#f0f8ff')

    def configure_json_highlight_tags(self):
        self.json_output_text.tag_configure("key", foreground="black", font=("TkDefaultFont", 9, "bold"))
        self.json_output_text.tag_configure("string", foreground="#008000")
        self.json_output_text.tag_configure("number", foreground="#FF0000")
        self.json_output_text.tag_configure("boolean", foreground="#FF00FF")
        self.json_output_text.tag_configure("null", foreground="#DAA520")
        self.json_output_text.tag_configure("error", foreground="red", font=("TkDefaultFont", 10, "bold"))

    # --- HISTORY MANAGEMENT METHODS ---

    def _get_current_state_object(self) -> AppState:
        is_manual = (self.table_var.get() == "[Custom Query]")
        manual_text = self.query_text.get("1.0", tk.END).strip()
        
        return AppState(
            schema=self.current_schema,
            table=self.current_table,
            filters=copy.deepcopy(self.filters),
            sorting=copy.deepcopy(self.sorting),
            row_limit=self.row_limit,
            is_manual_mode=is_manual,
            manual_query_text=manual_text
        )

    def record_current_state(self):
        """
        Snapshot the current application state and push it to history.
        Only records if we are NOT currently navigating via back/forward buttons.
        """
        if self.is_navigating_history:
            return

        state = self._get_current_state_object()

        # Check if the new state is identical to the current tip of history (deduplication)
        if self.history_index >= 0 and self.history_index < len(self.history):
            current_tip = self.history[self.history_index]
            # Manual comparison to avoid issues with timestamps
            if (current_tip.schema == state.schema and
                current_tip.table == state.table and
                current_tip.row_limit == state.row_limit and
                current_tip.is_manual_mode == state.is_manual_mode and
                str(current_tip.filters) == str(state.filters) and 
                str(current_tip.sorting) == str(state.sorting) and
                current_tip.manual_query_text == state.manual_query_text):
                return

        # If we are in the middle of the stack and do a new action, truncate future history
        if self.history_index < len(self.history) - 1:
            self.history = self.history[:self.history_index + 1]

        self.history.append(state)
        
        # Enforce max history size
        if len(self.history) > self.max_history:
            self.history.pop(0)
        else:
            self.history_index += 1

        self.update_history_buttons()

    def update_history_buttons(self):
        """Enable/Disable Back and Forward buttons based on current index."""
        if self.history_index > 0:
            self.btn_back.config(state=tk.NORMAL)
        else:
            self.btn_back.config(state=tk.DISABLED)

        if self.history_index < len(self.history) - 1:
            self.btn_fwd.config(state=tk.NORMAL)
        else:
            self.btn_fwd.config(state=tk.DISABLED)

    def go_back(self):
        """Navigate to the previous state."""
        if self.history_index > 0:
            self.history_index -= 1
            self.restore_state(self.history[self.history_index])
            self.update_history_buttons()

    def go_forward(self):
        """Navigate to the next state."""
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.restore_state(self.history[self.history_index])
            self.update_history_buttons()

    def restore_state(self, state: AppState):
        """
        Restore the application to the provided state.
        Sets a flag to prevent this restoration from recording a new history entry.
        """
        self.is_navigating_history = True
        try:
            # Restore variables
            self.current_schema = state.schema
            self.current_table = state.table
            self.row_limit = state.row_limit
            # Restore deep copies to prevent reference issues
            self.filters = copy.deepcopy(state.filters)
            self.sorting = copy.deepcopy(state.sorting)
            
            # Update UI Controls
            self.schema_var.set(state.schema if state.schema else "")
            self.limit_var.set(str(state.row_limit))

            # Handle Schema Loading if needed (visual only, data loading happens later)
            if state.schema and state.schema not in self.schema_combo['values']:
                pass
            
            if state.is_manual_mode:
                # Manual Mode Restoration
                self.table_var.set("[Custom Query]")
                self.schema_var.set("[Manual]")
                
                # Update Query Box
                self._programmatic_update = True
                self.query_text.config(state=tk.NORMAL, background='white') # Reset highlight
                self.query_text.delete(1.0, tk.END)
                self.query_text.insert(1.0, state.manual_query_text)
                self._programmatic_update = False
                
                # Visuals for manual mode
                self.filters.clear() # Clear visual filters for manual mode (though we stored them)
                self.sorting.clear()
                self.update_controls_display()
                self.run_custom_query_btn.config(state=tk.NORMAL)
                self.get_count_btn.config(state=tk.DISABLED) # Disable Count in Manual
                
                # Execute
                self.execute_query(state.manual_query_text)
                
            else:
                # GUI Mode Restoration
                self.table_var.set(state.table)
                self.run_custom_query_btn.config(state=tk.DISABLED)
                self.get_count_btn.config(state=tk.NORMAL) # Enable Count in GUI mode
                
                self.update_controls_display()
                
                # Rebuild and run query
                query = self.build_query()
                self.update_query_display(query)
                self.execute_query(query)

        finally:
            self.is_navigating_history = False

    # --------------------------------

    def save_query_state(self):
        """Saves the current AppState to a JSON file in the script directory."""
        state = self._get_current_state_object()
        
        default_name = f"query_save_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if state.table:
            default_name = f"{state.table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        filepath = filedialog.asksaveasfilename(
            initialdir=self.get_saved_queries_dir(),
            initialfile=default_name,
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Save Query Configuration"
        )
        
        if not filepath:
            return
            
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(state.to_dict(), f, indent=4)
            self.status_var.set(f"Query configuration saved to {os.path.basename(filepath)}")
        except Exception as e:
            self.logger.error(f"Failed to save query state: {e}")
            messagebox.showerror("Save Error", f"Could not save query:\n{e}")

    def load_query_state(self):
        """Loads an AppState from a JSON file in the script directory."""
        filepath = filedialog.askopenfilename(
            initialdir=self.get_saved_queries_dir(),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            title="Load Query Configuration"
        )
        
        if not filepath:
            return
            
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            state = AppState.from_dict(data)
            
            # Record current state before jumping, so users can hit 'Back' to return to where they were
            self.record_current_state()
            
            self.restore_state(state)
            self.status_var.set(f"Loaded query configuration from {os.path.basename(filepath)}")
        except Exception as e:
            self.logger.error(f"Failed to load query state: {e}")
            messagebox.showerror("Load Error", f"Could not load query:\n{e}")

    def toggle_middle_frame(self, force_show=False):
        if force_show:
            self.show_middle_frame = True
        else:
            self.show_middle_frame = not self.show_middle_frame
            
        if self.show_middle_frame:
            self.middle_frame.grid()
            self.toggle_json_btn.config(text="Hide Query & JSON Tools")
        else:
            self.middle_frame.grid_remove()
            self.toggle_json_btn.config(text="Show Query & JSON Tools")
        
    def on_json_input_modified(self, event=None):
        if self.json_input_text.edit_modified():
            self.format_and_highlight_json()
        self.json_input_text.edit_modified(False)

    def format_and_highlight_json(self):
        input_text = self.json_input_text.get("1.0", tk.END).strip()
        
        self.json_output_text.config(state=tk.NORMAL)
        self.json_output_text.delete("1.0", tk.END)

        if not input_text:
            self.json_output_text.config(state=tk.DISABLED)
            return

        try:
            json_obj = json.loads(input_text)
            self._recursive_highlight(json_obj)
        except json.JSONDecodeError as e:
            error_message = f"Invalid JSON:\n\n{e}"
            self.json_output_text.insert("1.0", error_message)
            self.json_output_text.tag_add("error", "1.0", tk.END)
        
        self.json_output_text.config(state=tk.DISABLED)

    def _recursive_highlight(self, data, indent=0):
        widget = self.json_output_text
        space = ' ' * indent

        def insert_with_tag(text, tag_name):
            start = widget.index(f"{tk.END}-1c")
            widget.insert(tk.END, text)
            if tag_name:
                end = widget.index(f"{tk.END}-1c")
                widget.tag_add(tag_name, start, end)

        if isinstance(data, dict):
            widget.insert(tk.END, '{\n')
            items = list(data.items())
            for i, (key, value) in enumerate(items):
                widget.insert(tk.END, ' ' * (indent + 4))
                insert_with_tag(f'"{key}"', 'key')
                widget.insert(tk.END, ': ')
                self._recursive_highlight(value, indent + 4)
                if i < len(items) - 1:
                    widget.insert(tk.END, ',\n')
            widget.insert(tk.END, f'\n{space}' + '}')

        elif isinstance(data, list):
            if not data:
                widget.insert(tk.END, '[]')
                return

            widget.insert(tk.END, '[\n')
            for i, item in enumerate(data):
                widget.insert(tk.END, ' ' * (indent + 4))
                self._recursive_highlight(item, indent + 4)
                if i < len(data) - 1:
                    widget.insert(tk.END, ',\n')
            widget.insert(tk.END, f'\n{space}' + ']')

        elif isinstance(data, str):
            insert_with_tag(json.dumps(data), 'string')
        
        elif isinstance(data, bool):
            insert_with_tag(str(data).lower(), 'boolean')
            
        elif isinstance(data, (int, float)):
            insert_with_tag(str(data), 'number')

        elif data is None:
            insert_with_tag('null', 'null')

    def on_schema_selected(self, event=None):
        selected_schema = self.schema_var.get()
        if selected_schema and selected_schema != self.current_schema and selected_schema != "[Manual]":
            self.current_schema = selected_schema
            self.current_table = ""
            self.table_var.set("")
            self.table_combo['values'] = []
            self.filters.clear()
            self.sorting.clear()
            self.clear_results()
            self.load_tables_for_schema(auto_select=True)

    def on_table_selected(self, event=None):
        selected_item = self.table_var.get()
        if not selected_item or selected_item == "[Custom Query]":
            return

        new_schema = self.current_schema
        new_table = selected_item

        if '.' in selected_item and self.is_fuzzy_finding:
            try:
                new_schema, new_table = selected_item.split('.', 1)
            except ValueError:
                self.logger.warning(f"Invalid fuzzy selection format: {selected_item}")
                return

        if new_schema == self.current_schema and new_table == self.current_table:
            self.table_var.set(self.current_table)
            self.is_fuzzy_finding = False
            return

        schema_changed = (new_schema != self.current_schema)
        self.current_schema = new_schema
        self.current_table = new_table

        if schema_changed:
            self.schema_var.set(self.current_schema)
            self.load_tables_for_schema(auto_select=False)
        
        self.table_var.set(self.current_table)
        
        self.is_fuzzy_finding = False
        self.filters.clear()
        self.sorting.clear()
        self.save_csv_btn.config(state=tk.DISABLED)
        self.get_count_btn.config(state=tk.NORMAL) # Enable count button for valid table
        self.load_table_data()

    def build_query(self) -> str:
        if not self.current_schema or not self.current_table:
            return ""

        inner_sorting = [s for s in self.sorting if s.column != "row"]
        outer_sorting = [s for s in self.sorting if s.column == "row"]

        inner_query = f'SELECT * FROM "{self.current_schema}"."{self.current_table}"'
        
        active_filters = [f.to_sql() for f in self.filters if f.state == FilterState.ACTIVE]
        if active_filters:
            inner_query += "\nWHERE\n"
            inner_query += " AND\n  ".join(active_filters)
        
        if inner_sorting:
            sort_clauses = [s.to_sql() for s in inner_sorting]
            inner_query += f"\nORDER BY\n  {', '.join(sort_clauses)}"
            
        inner_query += f"\nLIMIT {self.row_limit}"
        
        inner_query_indented = "    " + inner_query.replace("\n", "\n    ")

        query = f"""WITH sorted_results AS (
{inner_query_indented}
)
SELECT
    ROW_NUMBER() OVER () AS "row",
    *
FROM sorted_results"""

        if outer_sorting:
            sort_clauses = [s.to_sql() for s in outer_sorting]
            query += f"\nORDER BY\n  {', '.join(sort_clauses)}"
            
        query += ";"
        return query
    
    def on_header_click(self, event):
        column_id = self.tree.identify_column(event.x)
        if not column_id:
            return

        try:
            col_index = int(column_id.replace('#', '')) - 1
            if not (0 <= col_index < len(self.column_names)):
                return
        except ValueError:
            return

        column_name = self.column_names[col_index]
        existing_sort = next((s for s in self.sorting if s.column == column_name), None)
        if existing_sort:
            existing_sort.direction = "DESC" if existing_sort.direction == "ASC" else "ASC"
        else:
            self.sorting.append(SortCriterion(column=column_name, direction="ASC"))

        self.load_table_data()

    def create_filter_dialog(self, column_name: str, value: str, filter_to_edit: Optional[Filter] = None):
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit Filter" if filter_to_edit else "Add Filter")
        dialog.geometry("450x480")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        
        dialog.wait_visibility()
        dialog.grab_set()

        dialog.geometry(f"+{self.root.winfo_rootx()+50}+{self.root.winfo_rooty()+50}")
        
        initial_op = filter_to_edit.operator if filter_to_edit else "="
        initial_val = filter_to_edit.value if filter_to_edit else value
        initial_force_string = filter_to_edit.force_string if filter_to_edit else False
        
        main_frame = ttk.Frame(dialog, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text=f"Column: {column_name}", font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W, pady=(0,5))
        
        operator_frame = ttk.LabelFrame(main_frame, text="Filter Operator", padding="10")
        operator_frame.pack(fill=tk.X, pady=(0, 10))
        operator_var = tk.StringVar(value=initial_op)
        
        col1_frame = ttk.Frame(operator_frame)
        col1_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
        col2_frame = ttk.Frame(operator_frame)
        col2_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        operators = [
            ("Equal to", "="), 
            ("Not equal to", "!="), 
            ("Contains (ilike)", "ILIKE"), 
            ("Does not contain (not ilike)", "NOT ILIKE"),
            ("In list (comma-sep)", "IN"), 
            ("Not in list", "NOT IN"),
            ("Greater than", ">"), 
            ("Less than", "<"), 
            ("Greater than or equal to", ">="), 
            ("Less than or equal to", "<=")
        ]
        
        for i, (text, op) in enumerate(operators):
            frame = col1_frame if i < 5 else col2_frame
            ttk.Radiobutton(frame, text=text, variable=operator_var, value=op).pack(anchor=tk.W, pady=2)
            
        value_frame = ttk.LabelFrame(main_frame, text="Filter Value (for IN, use comma-separated list)", padding="10")
        value_frame.pack(fill=tk.X, pady=(0, 10))
        value_var = tk.StringVar(value=initial_val)
        value_entry = ttk.Entry(value_frame, textvariable=value_var, width=40, font=("TkDefaultFont", 10))
        value_entry.pack(fill=tk.X)
        value_entry.select_range(0, tk.END)
        value_entry.focus()
        
        force_string_var = tk.BooleanVar(value=initial_force_string)
        force_string_check = ttk.Checkbutton(main_frame, text="Treat value as string (e.g., for numeric IDs)", variable=force_string_var)
        force_string_check.pack(anchor=tk.W, pady=(0, 15))
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, side="bottom")

        def apply_filter():
            operator = operator_var.get()
            filter_value_str = value_var.get().strip()
            force_string = force_string_var.get()
            
            if (value == "NULL" or filter_value_str.upper() == "NULL") and operator not in ["=", "!="]:
                messagebox.showerror("Error", "Only '=' (IS NULL) or '!=' (IS NOT NULL) can be used with NULL values.")
                return

            if filter_to_edit:
                filter_to_edit.operator = operator
                filter_to_edit.value = filter_value_str
                filter_to_edit.force_string = force_string
                filter_to_edit.state = FilterState.ACTIVE
            else:
                new_filter = Filter(
                    id=next(self._filter_id_counter), 
                    column=column_name, 
                    operator=operator, 
                    value=filter_value_str,
                    force_string=force_string
                )
                self.filters.append(new_filter)
            
            dialog.destroy()
            self.load_table_data()

        dialog.bind('<Return>', lambda e: apply_filter())
        value_entry.bind('<Return>', lambda e: apply_filter())
        
        ttk.Button(btn_frame, text="Apply Filter", command=apply_filter).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
    
    def update_controls_display(self):
        self._update_filters_display()
        self._update_sorting_display()

    def _update_filters_display(self):
        for widget in self.filters_flow_frame.winfo_children():
            widget.destroy()
            
        if not self.filters:
            ttk.Label(self.filters_flow_frame, text="No filters applied. Click a cell to add one.").pack()
        else:
            for f in self.filters:
                pill_frame = ttk.Frame(self.filters_flow_frame, style='Pill.TFrame', borderwidth=1, relief="solid")
                
                is_active_var = tk.BooleanVar(value=(f.state == FilterState.ACTIVE))
                ttk.Checkbutton(pill_frame, variable=is_active_var, 
                               command=lambda flt=f: self.toggle_filter_active(flt)).pack(side="left")
                
                style = {} if f.state == FilterState.ACTIVE else {'foreground': 'gray'}
                text_to_display = str(f) if len(str(f)) < 50 else f"{str(f)[:47]}..."
                ttk.Label(pill_frame, text=text_to_display, **style).pack(side="left", padx=(0, 5))
                
                ttk.Button(pill_frame, text="edit", width=4, 
                          command=lambda flt=f: self.create_filter_dialog(flt.column, flt.value, flt)).pack(side="left")
                ttk.Button(pill_frame, text="X", width=2, 
                          command=lambda flt=f: self.remove_filter(flt)).pack(side="left", padx=(2,0))
                
        self.filters_flow_frame.reorganize()

    def _update_sorting_display(self):
        for widget in self.sorting_flow_frame.winfo_children():
            widget.destroy()
            
        if not self.sorting:
            ttk.Label(self.sorting_flow_frame, text="No sorting applied. Click a column header to sort.").pack()
        else:
            for i, s in enumerate(self.sorting):
                pill_frame = ttk.Frame(self.sorting_flow_frame, style='Pill.TFrame', borderwidth=1, relief="solid")
                
                ttk.Label(pill_frame, text=f"{i+1}. {s}").pack(side="left", padx=(5,5))
                
                ttk.Button(pill_frame, text="X", width=2, 
                          command=lambda srt=s: self.remove_sort_criterion(srt)).pack(side="left", padx=(0,2))
                
        self.sorting_flow_frame.reorganize()

    def load_table_data(self):
        """Load data for the currently selected table, resetting to GUI-driven mode."""
        if not self.current_table or not self.current_schema: 
            return
        
        # RECORD STATE BEFORE LOADING
        self.record_current_state()

        self.schema_var.set(self.current_schema)
        self.table_var.set(self.current_table)
        
        query = self.build_query()
        self.update_query_display(query)
        self.update_controls_display()
        self.execute_query(query)

    def refresh_current_table(self):
        if self.current_table: 
            self.load_table_data()

    def get_total_count(self):
        """
        Calculates the total number of rows matching the current filters
        (ignoring limit and sort) and displays it in the status bar.
        Does NOT change the visible result set or the query box.
        """
        if not self.current_schema or not self.current_table:
            return

        # Build SQL strictly for counting (ignores sort/limit)
        query = f'SELECT count(*) FROM "{self.current_schema}"."{self.current_table}"'
        
        active_filters = [f.to_sql() for f in self.filters if f.state == FilterState.ACTIVE]
        if active_filters:
            query += "\nWHERE\n"
            query += " AND\n  ".join(active_filters)
        
        query += ";"

        self.status_var.set("Calculating total count...")
        
        def run_count_query():
            results = self.db.execute_query(query)
            
            count_val = "Error"
            if results and len(results) > 1 and results[0][0] != 'Error':
                # results[1][0] contains the actual count value
                count_val = results[1][0]
            
            # Update UI from the main thread
            self.root.after(0, lambda: self.status_var.set(f"Total Count (matching filters): {count_val}"))
                
        # Run in background to prevent UI freeze
        thread = threading.Thread(target=run_count_query, daemon=True)
        thread.start()

    def update_query_display(self, query: str):
        self._programmatic_update = True
        try:
            self.query_text.config(state=tk.NORMAL)
            self.query_text.config(background='white')
            self.query_text.delete(1.0, tk.END)
            self.query_text.insert(1.0, query if query else "Select a schema and table to begin.")
            self.run_custom_query_btn.config(state=tk.DISABLED)
        finally:
            self._programmatic_update = False

    def on_query_text_modified(self, event=None):
        if self._programmatic_update:
            return

        self.query_text.config(background='#fffacd') 
        self.status_var.set("Query modified. Click 'Run Custom Query' or press 'Refresh Data' to reset.")
        self.run_custom_query_btn.config(state=tk.NORMAL)

    def run_custom_query(self):
        """Executes the SQL query manually entered into the query text box."""
        custom_query = self.query_text.get("1.0", tk.END).strip()
        if not custom_query:
            messagebox.showwarning("Empty Query", "Cannot execute an empty query.")
            return

        self.filters.clear()
        self.sorting.clear()
        self.update_controls_display()

        self.schema_var.set("[Manual]")
        self.table_var.set("[Custom Query]")
        self.query_text.config(background='white')
        self.run_custom_query_btn.config(state=tk.DISABLED)
        self.get_count_btn.config(state=tk.DISABLED) # Disable auto-count for custom queries
        
        # RECORD STATE FOR MANUAL QUERY
        self.record_current_state()

        self.execute_query(custom_query)

    def on_limit_changed(self):
        try:
            new_limit = int(self.limit_var.get())
            if new_limit <= 0:
                self.status_var.set("Limit must be greater than 0.")
                self.limit_var.set(str(self.row_limit))
                return
            if new_limit != self.row_limit:
                self.row_limit = new_limit
                self.load_table_data()
        except ValueError:
            self.status_var.set("Invalid limit. Please enter a number.")
            self.limit_var.set(str(self.row_limit))
            
    def execute_query(self, query: str):
        if not query.strip(): 
            return
        
        self.status_var.set("Executing query...")
        self.root.update_idletasks()
        
        def query_thread():
            results = self.db.execute_query(query)
            self.last_query_results = results
            self.root.after(0, lambda: self.display_results(results))
                
        thread = threading.Thread(target=query_thread, daemon=True)
        thread.start()

    def display_results(self, results: Optional[List[List[Any]]]):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.tree['columns'] = []
        self.save_csv_btn.config(state=tk.DISABLED)
        self.copy_results_btn.config(state=tk.DISABLED)

        if not results or not results[0]:
            self.status_var.set("Query failed or returned no data. Check logs.")
            self.column_names = []
            self.data_rows = []
            return

        raw_column_names = results[0]
        raw_data_rows = results[1:]
        
        if raw_column_names[0] == 'Error':
            self.column_names, self.data_rows = raw_column_names, raw_data_rows
            self.tree['columns'] = self.column_names
            self.tree.heading(self.column_names[0], text=self.column_names[0])
            self.tree.column(self.column_names[0], width=1200)
            if self.data_rows:
                 self.tree.insert('', tk.END, values=self.data_rows[0])
                 self.status_var.set(f"Query Error: {self.data_rows[0][0]}")
            return

        self.column_names, self.data_rows = raw_column_names, raw_data_rows
        row_num_col_name = "row"
        
        if not self.column_names:
            self.status_var.set("Query returned no displayable columns.")
            return
        
        self.tree['columns'] = self.column_names
        for col in self.column_names:
            self.tree.heading(col, text=col)
            if col == row_num_col_name:
                self.tree.column(col, width=60, minwidth=50, anchor=tk.E, stretch=tk.NO)
            else:
                self.tree.column(col, width=120, minwidth=100, anchor=tk.W)
            
        for i, row in enumerate(self.data_rows):
            tag = self.tree_tags[i % 2]
            self.tree.insert('', tk.END, values=row, tags=(tag,))
        
        if self.data_rows:
            self.save_csv_btn.config(state=tk.NORMAL)
            self.copy_results_btn.config(state=tk.NORMAL)
            self.status_var.set(f"Loaded {len(self.data_rows)} rows.")
        else:
             self.status_var.set(f"Query executed successfully, 0 rows returned.")
    
    def clear_results(self):
        self.save_csv_btn.config(state=tk.DISABLED) 
        self.copy_results_btn.config(state=tk.DISABLED)
        for item in self.tree.get_children(): 
            self.tree.delete(item)
        self.tree['columns'] = []
        self.column_names = []
        self.data_rows = []
        self.last_query_results = None
        
    def on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        
        if region == "heading":
            self.on_header_click(event)
        elif region == "cell":
            item = self.tree.identify('item', event.x, event.y)
            column = self.tree.identify('column', event.x, event.y)
            
            if item and column:
                col_index = int(column.replace('#', '')) - 1
                if 0 <= col_index < len(self.column_names):
                    column_name = self.column_names[col_index]
                    if column_name == 'Error' or column_name == 'row': 
                        return
                    values = self.tree.item(item, 'values')
                    if col_index < len(values):
                        value = values[col_index]
                        self.create_filter_dialog(column_name, value)
    
    def on_tree_right_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        column_id = self.tree.identify_column(event.x)
        
        if not column_id or not self.column_names:
            return

        try:
            col_index = int(column_id.replace('#', '')) - 1
            if not (0 <= col_index < len(self.column_names)):
                return
            
            column_name = self.column_names[col_index]

            if region == "heading":
                if not self.data_rows: return
                column_values = [row[col_index] for row in self.data_rows]
                clipboard_text = ",".join(map(str, column_values))
                self.root.clipboard_clear()
                self.root.clipboard_append(clipboard_text)
                self.status_var.set(f"Copied {len(column_values)} values from column '{column_name}'")

            elif region == "cell":
                item_id = self.tree.identify_row(event.y)
                if not item_id: return
                values = self.tree.item(item_id, 'values')
                cell_value = values[col_index]
                self.root.clipboard_clear()
                self.root.clipboard_append(cell_value)
                display_value = (str(cell_value)[:50] + '...') if len(str(cell_value)) > 50 else cell_value
                self.status_var.set(f"Copied '{display_value}' to clipboard.")

        except (IndexError, ValueError) as e:
            self.logger.warning(f"Could not copy content: {e}")

    def on_tree_inspect_json(self, event):
        """
        Handles Middle Click or Double Right Click to check if cell content is JSON.
        If valid JSON, opens the tool pane and formats it.
        """
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        column_id = self.tree.identify_column(event.x)
        item_id = self.tree.identify_row(event.y)

        if not column_id or not item_id or not self.column_names:
            return

        try:
            col_index = int(column_id.replace('#', '')) - 1
            if not (0 <= col_index < len(self.column_names)):
                return
            
            values = self.tree.item(item_id, 'values')
            if col_index < len(values):
                cell_value = values[col_index]
                
                # Check if it looks like JSON before processing
                if not cell_value or cell_value == "NULL":
                    return

                try:
                    # Attempt to parse. We specifically look for lists or dicts
                    # because parsing a simple integer as JSON isn't useful here.
                    parsed = json.loads(cell_value)
                    if isinstance(parsed, (dict, list)):
                        # It is valid complex JSON.
                        self.toggle_middle_frame(force_show=True)
                        
                        # Set text
                        self.json_input_text.delete("1.0", tk.END)
                        self.json_input_text.insert("1.0", cell_value)
                        
                        # Trigger formatter
                        self.format_and_highlight_json()
                        self.status_var.set("JSON detected and formatted.")
                    else:
                        self.status_var.set("Cell value is valid primitive JSON, but not an object or array.")

                except json.JSONDecodeError:
                    self.status_var.set("Cell content is not valid JSON.")

        except (IndexError, ValueError) as e:
            self.logger.warning(f"Error inspecting JSON: {e}")

    def save_to_csv(self):
        if not self.data_rows or not self.column_names:
            messagebox.showwarning("No Data", "There is no data to save.")
            return
        
        default_filename_table = self.current_table if self.current_table and self.table_var.get() != "[Custom Query]" else "custom_query"
        try:
            default_filename = f"{default_filename_table}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            filepath = filedialog.asksaveasfilename(
                initialfile=default_filename,
                defaultextension=".csv",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )

            if not filepath:
                self.status_var.set("Save operation cancelled.")
                return

            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(self.column_names)
                writer.writerows(self.data_rows)

            self.status_var.set(f"Successfully saved {len(self.data_rows)} rows to {os.path.basename(filepath)}")
            self.logger.info(f"Data saved to {filepath}")

        except Exception as e:
            self.logger.error(f"Failed to save CSV file: {e}")
            messagebox.showerror("Save Error", f"An error occurred while saving the file:\n{e}")
            self.status_var.set("Error saving file.")

    def copy_query_to_clipboard(self):
        query = self.query_text.get("1.0", tk.END).strip()
        if not query or query == "Select a schema and table to begin.":
            self.status_var.set("Nothing to copy. Query box is empty or contains default text.")
            return
        
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(query)
            self.status_var.set("Query copied to clipboard.")
        except tk.TclError:
            self.logger.warning("Could not access clipboard.")
            self.status_var.set("Error: Could not access clipboard.")

    def copy_query_and_results_to_clipboard(self):
        if not self.data_rows or not self.column_names or self.column_names[0] == 'Error':
            messagebox.showwarning("No Data", "There is no data to copy.")
            self.status_var.set("No results to copy.")
            return

        query = self.query_text.get("1.0", tk.END).strip()
        
        formatted_table = self._format_results_as_text_table()
        
        row_count_footer = f"\n({len(self.data_rows)} rows)"

        full_text = f"{query}\n{formatted_table}{row_count_footer}"

        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(full_text)
            self.status_var.set(f"Query and {len(self.data_rows)} results copied to clipboard.")
        except tk.TclError:
            self.logger.warning("Could not access clipboard.")
            self.status_var.set("Error: Could not access clipboard.")
        except Exception as e:
            self.logger.error(f"Failed to copy to clipboard: {e}")
            messagebox.showerror("Clipboard Error", f"Could not copy to clipboard:\n{e}")
            self.status_var.set("Error copying to clipboard.")

    def _format_results_as_text_table(self) -> str:
        headers = self.column_names
        data = self.data_rows

        if not headers:
            return ""

        str_data = [[str(item) for item in row] for row in data]
        
        col_widths = [len(h) for h in headers]
        for row in str_data:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = max(col_widths[i], len(cell))
        
        header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        separator_line = "-+-".join("-" * w for w in col_widths)

        data_lines = []
        for row in str_data:
            padded_row = row + [''] * (len(headers) - len(row))
            data_lines.append(" | ".join(cell.ljust(w) for cell, w in zip(padded_row, col_widths)))
            
        return "\n".join([header_line, separator_line] + data_lines)

    def toggle_filter_active(self, filter_to_toggle: Filter):
        filter_to_toggle.state = FilterState.ACTIVE if filter_to_toggle.state == FilterState.INACTIVE else FilterState.INACTIVE
        self.load_table_data()

    def remove_filter(self, filter_to_remove: Filter):
        self.filters = [f for f in self.filters if f.id != filter_to_remove.id]
        self.load_table_data()

    def remove_sort_criterion(self, sort_to_remove: SortCriterion):
        self.sorting = [s for s in self.sorting if s is not sort_to_remove]
        self.load_table_data()

    def on_clear_all_filters(self):
        if self.filters:
            self.filters.clear()
            self.load_table_data()

    def on_clear_all_sorting(self):
        if self.sorting:
            self.sorting.clear()
            self.load_table_data()
    
    def load_schemas(self):
        self.status_var.set("Loading schemas...")
        
        def load_thread():
            schemas = self.db.get_schemas()
            self.root.after(0, lambda: self.update_schema_list(schemas))
                
        thread = threading.Thread(target=load_thread, daemon=True)
        thread.start()

    def update_schema_list(self, schemas: List[str]):
        self.schema_combo['values'] = schemas
        if schemas:
            self.cache_all_tables()
            self.schema_combo.set(schemas[0])
            self.on_schema_selected()
        else:
            self.status_var.set("No schemas found in the database.")

    def load_tables_for_schema(self, auto_select=True):
        if not self.current_schema:
            return
        self.status_var.set(f"Loading tables for schema '{self.current_schema}'...")
        
        def load_thread():
            tables = self.db.get_tables(self.current_schema)
            self.root.after(0, lambda: self.update_available_tables(tables, auto_select=auto_select))

        thread = threading.Thread(target=load_thread, daemon=True)
        thread.start()

    def update_available_tables(self, tables: List[str], auto_select=True):
        self.available_tables = tables
        if not self.is_fuzzy_finding:
            self.table_combo['values'] = tables
        
        if auto_select:
            if tables:
                self.table_combo.set(tables[0])
                self.on_table_selected()
                self.status_var.set(f"Found {len(tables)} tables in '{self.current_schema}'. Auto-selected '{tables[0]}'.")
            else:
                self.table_combo.set('')
                self.current_table = ''
                self.clear_results()
                self.update_query_display("")
                self.status_var.set(f"No tables found in schema '{self.current_schema}'.")

    # --- FUZZY FINDER METHODS ---

    def cache_all_tables(self):
        self.status_var.set("Caching all tables for fuzzy search...")
        
        def cache_thread():
            all_tables = self.db.get_all_tables()
            self.root.after(0, self.update_all_tables_cache, all_tables)

        thread = threading.Thread(target=cache_thread, daemon=True)
        thread.start()

    def update_all_tables_cache(self, table_list: List[Tuple[str, str]]):
        self.all_tables_cache = table_list
        if "Loading" not in self.status_var.get():
             self.status_var.set(f"Ready. Cached {len(self.all_tables_cache)} tables for searching.")
        self.logger.info(f"Cached {len(self.all_tables_cache)} tables from all schemas.")

    def on_table_enter_key(self, event=None):
        self.table_combo.event_generate('<Down>')
        return "break"

    def on_table_search(self, event=None):
        search_term = self.table_var.get().strip().lower()

        if not search_term:
            self.is_fuzzy_finding = False
            self.table_combo['values'] = self.available_tables
            return

        self.is_fuzzy_finding = True
        
        filtered_results = [
            f"{schema}.{table}" 
            for schema, table in self.all_tables_cache 
            if search_term in table.lower()
        ]

        current_schema_prefix = f"{self.current_schema}."
        filtered_results.sort(key=lambda item: (
            0 if search_term == item.split('.', 1)[1].lower() else 1,
            0 if item.startswith(current_schema_prefix) else 1,
            0 if item.startswith("public.") else 1,
            item
        ))
        
        self.table_combo['values'] = filtered_results

    def on_table_focus_in(self, event=None):
        if not self.is_fuzzy_finding:
            self.table_combo['values'] = self.available_tables

    def on_table_focus_out(self, event=None):
        self.root.after(100, self._check_focus_out)
    
    def _check_focus_out(self):
        try:
            if self.root.focus_get() is not self.table_combo:
                self.is_fuzzy_finding = False
                self.table_var.set(self.current_table if self.current_table else "")
                self.table_combo['values'] = self.available_tables
        except KeyError:
            pass