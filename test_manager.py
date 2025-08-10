from _datetime import datetime
import re
import importlib.util
import json
import os
import pandas as pd
from io import BytesIO
from PIL import Image
from collections import defaultdict
from openpyxl.drawing.image import Image as XLImage

SCRIPTS_DIR = "test_scripts"

class TestManager:
    def __init__(self, socketio):
        self.socketio = socketio
        self.running = False
        self.test_data = []
        self.details = {}
        self.script_name = ""
        self.selected_units = []
        self.run_timestamp = None

    def get_tests(self, script_name):
        script_path = os.path.join(SCRIPTS_DIR, f"{script_name}.py")
        if not os.path.exists(script_path):
            return {}
        spec = importlib.util.spec_from_file_location(script_name, script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        raw = getattr(mod, "AVAILABLE_TESTS", {})
        # Strip functions, leave only hierarchy
        def strip(tree):
            cleaned = {}
            for k, v in tree.items():
                # drop our execution‐order metadata (and the funcs list)
                if k in ('funcs', 'exec_order'):
                    continue
                # only recurse into real dicts
                if isinstance(v, dict):
                    cleaned[k] = strip(v)
                else:
                    # leaf‐node guard: we expect subtests to be dicts
                    cleaned[k] = {}
            return cleaned
        return strip(raw)

    def get_max_unit_support(self, script_name):
        script_path = os.path.join(SCRIPTS_DIR, f"{script_name}.py")
        if not os.path.exists(script_path):
            return {}
        spec = importlib.util.spec_from_file_location(script_name, script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        max_units = getattr(mod, "MULTI_UNIT_SUPPORTED_NUMBER", 1)
        return max_units

    def run_tests(self, script_name, selected_tests, details, selected_units):
        """Runs selected tests from the chosen script in the proper exec_order for multiple units."""
        self.running = True
        self.test_data = []
        self.details = details
        self.script_name = script_name
        self.selected_units = selected_units

        self.run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("results", exist_ok=True)

        # Pre-create a file per enabled unit with a Details sheet (if missing)
        serials = self.details.get("serials", [])
        comments = self.details.get("comments", [])
        op = (self.details.get("operatorName") or "").strip() or "Tester"

        for unit_idx in sorted(self.selected_units):
            # map unit_idx → index in details arrays
            serial = ""
            comment = ""
            if unit_idx in self.selected_units:
                di = self.selected_units.index(unit_idx)
                if di < len(serials):
                    serial = (str(serials[di]).strip() or "88888888")
                else:
                    serial = "88888888"
                if di < len(comments):
                    comment = (comments[di] or "No comment")
                else:
                    comment = "No comment"
            else:
                serial = "88888888"
                comment = "No comment"

            fn = f"{self.script_name}_{serial}_{self.run_timestamp}_{op}_unit{unit_idx}.xlsx"
            out_path = os.path.join("results", fn)
            if not os.path.exists(out_path):
                with pd.ExcelWriter(out_path, engine="openpyxl", mode="w") as writer:
                    info = {
                        "Script Name": self.script_name,
                        "Device Serial No.": serial,
                        "Operator Name": op or "Tester",
                        "Date/Time": datetime.now().isoformat(sep=" "),
                        "Additional Comments": comment or "No comment",
                        "Unit Index": unit_idx,
                    }
                    pd.DataFrame([info]).to_excel(writer, sheet_name="Details", index=False)

        # 1) Dynamically load the test script module
        script_path = os.path.join(SCRIPTS_DIR, f"{script_name}.py")
        if not os.path.exists(script_path):
            self.running = False
            return
        spec = importlib.util.spec_from_file_location(script_name, script_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        raw = getattr(mod, "AVAILABLE_TESTS", {})

        # 2) Flatten the entire raw tree into ordered_tests_full, funcs_map_full, exec_order_full
        ordered_tests_full = []
        funcs_map_full = {}
        exec_order_full = {}

        def extract(tree, parent=""):
            for name, subtree in tree.items():
                if name in ("funcs", "exec_order"):
                    continue
                full = f"{parent}/{name}" if parent else name
                ordered_tests_full.append(full)
                funcs_map_full[full] = subtree.get("funcs", [])
                exec_order_full[full] = subtree.get("exec_order", 0)
                extract(subtree, full)

        extract(raw)

        # 3) Filter down to only those tests the user actually selected
        ordered_tests = [t for t in ordered_tests_full if t in selected_tests]

        # 4) Build our pruned maps for only the selected tests
        funcs_map = {t: funcs_map_full[t] for t in ordered_tests}
        exec_order_map = {t: exec_order_full[t] for t in ordered_tests}

        # 5) Initialize per-test/per-unit tracker
        # 5) Only track the *enabled* units
        unit_numbers = sorted(selected_units)
        num_units = len(unit_numbers)
        tracker = {t: [False] * num_units for t in ordered_tests}
        # 6) Build executed_once only for tests with exec_order == -1
        executed_once = {t: False for t, o in exec_order_map.items() if o == -1}

        # 7) Helper to emit & record each callback
        def report_callback(result):
            self.socketio.emit("test_update", result)
            self.test_data.append(result)
            if result.get("message type") == "test end":
                self.save_results(
                    unit_idx=result.get("unit index"),
                    test_name=result.get("test name")
                )

        # 8) Determine max positive exec_order
        max_exec = max((o for o in exec_order_map.values() if o > 0), default=0)

        # 9) Main multi-unit/exec_order loop
        unit_idx = 0  # 0-based index of unit under test
        exec_loop = 1  # current exec_order we’re processing

        while True:
            # walk entire test list in tree order
            for idx, t in enumerate(ordered_tests):
                if not self.running:
                    return

                order = exec_order_map[t]

                if order == -1:
                    # once-only test: only when all prior selected tests done on every unit
                    if not executed_once[t]:
                        prev_done = True
                        for prev in ordered_tests[:idx]:
                            prev_order = exec_order_map[prev]
                            if prev_order == -1:
                                if not executed_once[prev]:
                                    prev_done = False
                                    break
                            else:
                                if not all(tracker[prev]):
                                    prev_done = False
                                    break
                        if prev_done:
                            for fn in funcs_map[t]:
                                fn(report_callback, t, unit_numbers, None)
                            executed_once[t] = True

                elif order == exec_loop:
                    # per‐unit test on each selected unit
                    if not tracker[t][unit_idx]:
                        current_unit = unit_numbers[unit_idx]
                        for fn in funcs_map[t]:
                            fn(report_callback, t, unit_numbers, current_unit)
                        tracker[t][unit_idx] = True

                # skip any test whose order < exec_loop or > exec_loop

            # 10) Check for overall completion
            if exec_loop > max_exec and all(executed_once.values()):
                break

            # 11) Advance unit or exec_loop
            if unit_idx < num_units - 1:
                unit_idx += 1
            else:
                unit_idx = 0
                exec_loop += 1

        # 12) All done ⇒ notify frontend and save
        self.socketio.emit("test_complete", {"message": "Test execution complete."})
        self.save_results()
        self.running = False

    def save_results(self, unit_idx: int | None = None, test_name: str | None = None) -> None:
        """
        Persist results to Excel.
        - If unit_idx and test_name are provided: append/replace only that test's sheet in that unit's file.
        - Otherwise (legacy): write everything currently in self.test_data.
        The workbook filename uses the per-run timestamp (self.run_timestamp).
        """
        os.makedirs("results", exist_ok=True)

        ts = self.run_timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
        operator = (self.details.get("operatorName") or "").strip() or "Tester"
        serials = self.details.get("serials", []) or []
        comments = self.details.get("comments", []) or []

        # Group all collected events by unit index
        by_unit: dict[int, list[dict]] = defaultdict(list)
        for entry in self.test_data:
            u = entry.get("unit index", 0)
            if u:
                by_unit[u].append(entry)

        # Decide which units to write
        unit_items = by_unit.items() if unit_idx is None else [(unit_idx, by_unit.get(unit_idx, []))]

        for u_idx, entries in unit_items:
            if not entries:
                continue

            # Map enabled unit number -> index in details arrays, then pull serial/comment with defaults
            serial = "88888888"
            comment = "No comment"
            if u_idx in self.selected_units:
                di = self.selected_units.index(u_idx)
                if di < len(serials) and str(serials[di]).strip():
                    serial = str(serials[di]).strip()
                if di < len(comments) and (comments[di] or "").strip():
                    comment = comments[di]

            # Build file name and ensure a Details sheet exists
            fn = f"{self.script_name}_{serial}_{ts}_{operator}_unit{u_idx}.xlsx"
            out_path = os.path.join("results", fn)

            if not os.path.exists(out_path):
                with pd.ExcelWriter(out_path, engine="openpyxl", mode="w") as w0:
                    info_row = [{
                        "Script Name": self.script_name,
                        "Device Serial No.": serial,
                        "Operator Name": operator,
                        "Date/Time": datetime.now().isoformat(sep=" "),
                        "Additional Comments": comment or "No comment",
                        "Unit Index": u_idx,
                    }]
                    pd.DataFrame(info_row).to_excel(w0, sheet_name="Details", index=False)

            # Group this unit's entries by test name (optionally filter to one test)
            tests = defaultdict(list)
            for e in entries:
                tests[e["test name"]].append(e)
            if test_name is not None:
                tests = {test_name: tests.get(test_name, [])}

            # Append/replace sheets as needed
            with pd.ExcelWriter(out_path, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
                for tname, evts in tests.items():
                    if not evts:
                        continue

                    # Sheet name (Excel-safe)
                    sheet = tname[:31]
                    for ch in r'[]:?*\/':
                        sheet = sheet.replace(ch, "_")

                    rtype = (evts[0].get("result type") or "").lower()

                    if rtype == "boolean":
                        # final state row: test name, result type, result (pass/fail)
                        end = next((e for e in evts if e["message type"] == "test end"), evts[-1])
                        df = pd.DataFrame([{
                            "test name": tname,
                            "result type": end.get("result type"),
                            "result": end.get("pass"),
                        }])
                        df.to_excel(writer, sheet_name=sheet, index=False)

                    elif rtype == "number":
                        # single summary row with unit, expected range, final value, pass
                        new = next((e for e in evts if e["message type"] == "new test"), evts[0])
                        end = next((e for e in evts if e["message type"] == "test end"), evts[-1])
                        df = pd.DataFrame([{
                            "test name": tname,
                            "result type": end.get("result type"),
                            "result unit": new.get("result unit"),
                            "expected range": new.get("expected range"),
                            "result value": end.get("result"),
                            "pass": end.get("pass"),
                        }], columns=[
                            "test name", "result type", "result unit",
                            "expected range", "result value", "pass"
                        ])
                        df.to_excel(writer, sheet_name=sheet, index=False)

                    elif rtype == "vector":
                        # rows: (metadata only on first row) + x,y for each update
                        new = next((e for e in evts if e["message type"] == "new test"), evts[0])
                        end = next((e for e in evts if e["message type"] == "test end"), evts[-1])

                        updates = [
                            u for u in evts
                            if u.get("message type") == "update"
                               and isinstance(u.get("result"), (list, tuple))
                               and len(u.get("result")) >= 2
                        ]

                        rows = []
                        for i, u in enumerate(updates):
                            x_val, y_val = u["result"]
                            rows.append({
                                "test name": tname if i == 0 else None,
                                "result unit": new.get("result unit") if i == 0 else None,
                                "expected range": new.get("expected range") if i == 0 else None,
                                "pass": end.get("pass") if i == 0 else None,
                                "x": x_val,
                                "y": y_val,
                            })

                        df = pd.DataFrame(rows, columns=[
                            "test name", "result unit", "expected range", "pass", "x", "y"
                        ])
                        df.to_excel(writer, sheet_name=sheet, index=False)

                    elif rtype == "image":
                        # header row + embed the image found in the last image event
                        end_evt = next((e for e in evts if e["message type"] == "test end"), evts[-1])
                        header_df = pd.DataFrame([{
                            "test name": tname,
                            "result type": end_evt.get("result type"),
                            "pass": end_evt.get("pass"),
                        }], columns=["test name", "result type", "pass"])
                        header_df.to_excel(writer, sheet_name=sheet, index=False)

                        # Try to embed the image (expects a /images/... URL)
                        img_url = next(
                            (e.get("result") for e in evts if
                             e.get("message type") in ("update", "test end") and e.get("result")),
                            None
                        )
                        if img_url:
                            # Map "/images/…/file" → local "images/…/file"
                            local_path = None
                            if "/images/" in str(img_url):
                                local_path = os.path.join("images", str(img_url).split("/images/")[1])
                            elif str(img_url).startswith("images" + os.sep) or str(img_url).startswith("images/"):
                                local_path = str(img_url)

                            ws = writer.book[sheet]
                            if local_path and os.path.exists(local_path):
                                ws.add_image(XLImage(local_path), "A3")
                            else:
                                ws.cell(row=3, column=1, value=f"Image not found: {img_url}")

                    else:
                        # Fallback: dump raw events for unknown types
                        pd.DataFrame(evts).to_excel(writer, sheet_name=sheet, index=False)

        # Optional rolling full log (for debugging)
        pd.DataFrame(self.test_data).to_excel("full_log.xlsx", index=False)

    def parse_results(self, df_map, workbook):
        """
        Given a dict of DataFrames from an Excel results file,
        return (metadata_dict, [result_event_dicts]) suitable for the frontend.
        """
        # 1) Metadata from the "Details" sheet
        details = df_map.get("Details")
        if details is None:
            raise ValueError("Missing 'Details' sheet")
        meta_row = details.iloc[0].to_dict()
        metadata = {
            'script name': meta_row.get("Script Name") or meta_row.get("script"),
            'operatorName': meta_row.get("Operator Name") or meta_row.get("operator"),
            'timestamp': meta_row.get("Date/Time") or meta_row.get("timestamp"),
            'unitIndex': meta_row.get("Unit Index") or meta_row.get("unitIndex"),
            'serial': meta_row.get("Device Serial No.") or meta_row.get("serial"),
            'comments': meta_row.get("Additional Comments") or meta_row.get("comments"),
        }

        # 2) Flatten each test-sheet into a sequence of “events”
        events = []
        for sheet, df in df_map.items():
            if sheet == "Details":
                continue

            # BOOLEAN: one row, 'result' column holds the pass/fail
            if 'result type' in df.columns and df['result type'].iloc[0].lower() == 'boolean':
                for _, r in df.iterrows():
                    pass_val = r.get("pass", r["result"])
                    events.append({
                        'message type': "test end",
                        'test name': r["test name"],
                        'unit index': metadata['unitIndex'],
                        'result type': r['result type'],
                        'result': r['result'],
                        'pass': pass_val,
                        'expected range': None,
                    })

            # NUMBER: final numeric value + pass/fail
            elif 'result type' in df.columns and df['result type'].iloc[0].lower() == 'number':
                # we assume columns: test name, expected range, result value, pass
                for _, r in df.iterrows():
                    raw = r.get("expected range")
                    from ast import literal_eval
                    try:
                        rng = literal_eval(raw) if isinstance(raw, str) else raw
                        expected = list(rng)
                    except Exception:
                        expected = []
                    # ---- new: read the single result-unit as string ----
                    unit = r.get("result unit", "")
                    unit_str = str(unit)
                    events.append({
                        'message type': "test end",
                        'test name': r["test name"],
                        'unit index': metadata['unitIndex'],
                        'result type': r['result type'],
                        'result': r.get("result value") or r.get("result"),
                        'pass': r['pass'],
                        'result unit': unit_str,
                        'expected range': expected,
                    })

            # VECTOR: extract x/y plus metadata columns from the sheet
            elif "x" in df.columns and "y" in df.columns:
                exp = df["expected range"].iloc[0] if "expected range" in df.columns else None
                from ast import literal_eval
                try:
                    rng = literal_eval(exp) if isinstance(exp, str) else exp
                    expected = list(rng)
                except Exception:
                    expected = []
                raw_p = df["pass"].iloc[0] if "pass" in df.columns else None
                p = str(raw_p)
                # ---- new: parse header's result unit into two strings ----
                if "result unit" in df.columns:
                    raw_u = df["result unit"].iloc[0]
                    raw_u = re.sub("[!@#$()']", "", raw_u)
                else:
                    raw_u = ""
                # split on comma if present, else duplicate
                if isinstance(raw_u, str) and "," in raw_u:
                    parts = [u.strip() for u in raw_u.split(",", 1)]
                    ru = parts if len(parts) == 2 else [parts[0], parts[0]]
                else:
                    u = str(raw_u)
                    ru = [u, u]
                # emit one update per x/y row, carrying metadata
                for _, r in df.iterrows():
                    events.append({
                        'message type': "update",
                        'test name': sheet,
                        'unit index': metadata['unitIndex'],
                        'result type': "vector",
                        'result': [r["x"], r["y"]],
                        'pass': p.lower(),
                        'result unit': ru,
                        'expected range': expected,
                    })
                # final “test end” event for this test
                events.append({
                    'message type': "test end",
                    'test name': sheet,
                    'unit index': metadata['unitIndex'],
                    'result type': "vector",
                    'result': None,
                    'pass': p.lower(),
                    'result unit': ru,
                    'expected range': expected,
                })

            # IMAGE: extract embedded pictures *and* pick up pass/expected range
            ws = workbook[sheet]
            if hasattr(ws, "_images") and ws._images:
                # pull metadata from the DataFrame header
                img_df = df_map.get(sheet, pd.DataFrame())
                raw_p = img_df["pass"].iloc[0] if "pass" in img_df.columns else None
                p = str(raw_p)
                # create a timestamp-based temp folder with a filesystem-safe name
                raw_ts = metadata.get("timestamp", "")
                if isinstance(raw_ts, datetime):
                    ts = raw_ts.strftime("%Y%m%d_%H%M%S")
                else:
                    ts = str(raw_ts)
                    # replace any non-alphanumeric, non-underscore, non-hyphen chars with '_'
                    ts = re.sub(r'[^A-Za-z0-9_-]', '_', ts)
                dirpath = os.path.join("images", "past_images_temp", ts)
                os.makedirs(dirpath, exist_ok=True)

                for idx, img in enumerate(ws._images):
                    # build a filename: script_test_serial_timestamp_idx.jpg
                    safe_name = metadata["script name"].replace(" ", "_")
                    safe_test = sheet.replace(" ", "_")
                    serial = metadata.get("serial", "")
                    fname = f"{safe_name}_{safe_test}_{serial}_{ts}_{idx}.jpg"
                    fullpath = os.path.join(dirpath, fname)

                    # extract PIL image from openpyxl Image object
                    bio = BytesIO(img._data())
                    pil = Image.open(bio)
                    pil.convert("RGB").save(fullpath, format="JPEG")

                    # URL that the frontend can fetch
                    url = f"http://localhost:5000/images/past_images_temp/{ts}/{fname}"

                    # send it exactly like a 'test end' event
                    events.append({
                        "message type": "test end",
                        "test name": sheet,
                        "unit index": metadata["unitIndex"],
                        "result type": "image",
                        "result": url,
                        "pass": p.lower(),
                        "expected range": None
                    })
                # done with this sheet
                continue

        return metadata, events

    def stop_test(self):
        self.running = False

    def is_running(self):
        return self.running