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


    def save_results(self):
        """Save test results into separate Excel files per unit_index."""
        os.makedirs("results", exist_ok=True)

        # Build common filename prefix
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        op = self.details.get("operatorName", "").strip()

        # pull the arrays out of details
        serials = self.details.get("serials", [])
        comments = self.details.get("comments", [])

        # Group all callbacks by unit_index
        by_unit = defaultdict(list)
        for entry in self.test_data:
            unit = entry.get("unit index", 0)
            if not unit:
                # no unit_index or zero ⇒ ignore
                continue
            by_unit[unit].append(entry)

        # For each unit, write its own results file
        for unit_idx, entries in by_unit.items():

            serial = ""
            comment = ""
            if unit_idx in self.selected_units:
                idx = self.selected_units.index(unit_idx)
                if idx < len(serials):
                    serial = str(serials[idx]).strip()
                if idx < len(comments):
                    comment = comments[idx]

            # sanitize unit index (in case 0 means "no unit" or similar)
            fn = f"{self.script_name}_{serial}_{ts}_{op}_unit{unit_idx}.xlsx"
            out_path = os.path.join("results", fn)


            with pd.ExcelWriter(out_path, engine="openpyxl", mode="w") as writer:
                # 1) DETAILS sheet
                info = {
                    "Script Name": self.script_name,
                    "Device Serial No.": serial,
                    "Operator Name": op,
                    "Date/Time": datetime.now().isoformat(sep=" "),
                    "Additional Comments": comment,
                    "Unit Index": unit_idx,
                }
                pd.DataFrame([info]).to_excel(writer, sheet_name="Details", index=False)

                # 2) Group this unit's entries by test name
                tests = defaultdict(list)
                for e in entries:
                    tests[e["test name"]].append(e)

                # 3) For each test, reproduce your Boolean/Number/Vector logic
                for test_name, evts in tests.items():
                    # sanitize sheet name
                    sheet = test_name[:31]
                    for ch in r'[]:?*\/':
                        sheet = sheet.replace(ch, "_")

                    rtype = evts[0].get("result type", "").lower()

                    if rtype == "boolean":
                        end = next((e for e in evts if e["message type"] == "test end"), evts[-1])
                        df = pd.DataFrame([{
                            "test name": test_name,
                            "result type": end["result type"],
                            "result": end["pass"],
                        }])
                        df.to_excel(writer, sheet_name=sheet, index=False)
                    elif rtype == "number":
                        new = next((e for e in evts if e["message type"] == "new test"), evts[0])
                        end = next((e for e in evts if e["message type"] == "test end"), evts[-1])
                        df = pd.DataFrame([{
                            "test name": test_name,
                            "result type": end["result type"],
                            "result unit": new.get("result unit"),
                            "expected range": new["expected range"],
                            "result value": end["result"],
                            "pass": end["pass"],
                        }])
                        df.to_excel(writer, sheet_name=sheet, index=False)
                    elif rtype == "vector":
                        # -- New: write metadata only on the first data row --
                        new = next((e for e in evts if e["message type"] == "new test"), evts[0])
                        end = next((e for e in evts if e["message type"] == "test end"), evts[-1])

                        # Gather only the update events for this test
                        updates = [
                            u for u in evts
                            if u["message type"] == "update"
                            and isinstance(u.get("result"), (list, tuple))
                            and len(u["result"]) >= 2
                        ]

                        rows = []
                        for idx, u in enumerate(updates):
                            x_val, y_val = u["result"]
                            rows.append({
                                # metadata only for first row (idx==0), else blank
                                "test name":      test_name if idx == 0 else None,
                                "result unit":    new.get("result unit") if idx == 0 else None,
                                "expected range": new.get("expected range") if idx == 0 else None,
                                "pass":           end.get("pass") if idx == 0 else None,
                                "x":               x_val,
                                "y":               y_val,
                            })

                        # Write out with exactly these columns; Excel will show blanks for None
                        df = pd.DataFrame(rows, columns=[
                            "test name",
                            "result unit",
                            "expected range",
                            "pass",
                            "x",
                            "y",
                        ])
                        df.to_excel(writer, sheet_name=sheet, index=False)
                    elif rtype == "image":
                        # 》 embed the image into the sheet 《
                        # a) Write a small header with test name & pass/fail status
                        end_evt = next((e for e in evts if e["message type"] == "test end"), evts[-1])
                        header_df = pd.DataFrame([{"test name": test_name, "result type": end_evt["result type"], "pass": end_evt["pass"]}])
                        header_df.to_excel(writer, sheet_name=sheet, index=False)
                        # b) Extract the image URL from the 'update' or 'test end' event
                        last_img_url = next((e["result"] for e in evts if e["message type"] in ("update", "test end")), None)
                        if last_img_url:
                        # parse out just the filename (assumes format "http://host/images/filename")
                            filename = os.path.basename(last_img_url)
                            local_path = os.path.join("images", filename)
                            if os.path.exists(local_path):
                                ws = writer.book[sheet]
                                img = XLImage(local_path)
                                # place the image roughly below the header (e.g. at cell A3)
                                ws.add_image(img, "A3")
                            else:
                                # if the file doesn't exist locally, write a note
                                ws = writer.book[sheet]
                                ws.cell(row=3, column=1,value=f"⚠︎ Image not found: {filename}")
                    else:
                        # fallback: dump raw events
                        pd.DataFrame(evts).to_excel(writer, sheet_name=sheet, index=False)

        full_messages = pd.DataFrame(self.test_data)
        full_messages.to_excel("full_log.xlsx", index=False)

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