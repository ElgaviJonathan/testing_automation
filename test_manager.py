from _datetime import datetime
import importlib.util
import json
import os
import pandas as pd
from collections import defaultdict


SCRIPTS_DIR = "test_scripts"

class TestManager:
    def __init__(self, socketio):
        self.socketio = socketio
        self.running = False
        self.test_data = []
        self.details = {}
        self.script_name = ""

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


    def run_tests(self, script_name, selected_tests, details, selected_number_of_units):
        """
        Runs selected tests from the chosen script in multi‐unit, exec_ordered fashion.
        Tests with exec_order = -1 run once (when encountered in tree), after all previous tests
        have finished on all units. Other tests run per‐unit in ascending exec_order.
        """
        self.running = True
        self.test_data = []
        self.details = details
        self.script_name = script_name

        # 1) Load the script and AVAILABLE_TESTS
        spec = importlib.util.spec_from_file_location(script_name, os.path.join(SCRIPTS_DIR, f"{script_name}.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        raw = getattr(mod, "AVAILABLE_TESTS", {})

        # 2) Flatten the tree into:
        #    - ordered_tests: list of full names in tree order
        #    - funcs_map:    full_name → [callable funcs]
        #    - exec_order_map: full_name → exec_order
        ordered_tests   = []
        funcs_map       = {}
        exec_order_map  = {}

        def extract(tree, parent=""):
            for name, subtree in tree.items():
                if name in ("funcs", "exec_order"):
                    continue
                full = f"{parent}/{name}" if parent else name
                ordered_tests.append(full)
                funcs_map[full]      = subtree.get("funcs", [])
                exec_order_map[full] = subtree.get("exec_order",  0)
                extract(subtree, full)

        extract(raw)

        # 3) Filter to only the tests the user selected
        ordered_tests = [t for t in ordered_tests if t in selected_tests]

        # 4) Tracker per-test per-unit so we never re-run the same unit/test
        tracker = {t: [False]*selected_number_of_units for t in ordered_tests}

        # 5) Helper to emit & record each callback
        def report_callback(result):
            self.socketio.emit("test_update", result)
            self.test_data.append(result)

        max_exec = max([o for o in exec_order_map.values() if o > 0], default=0)

        # trackers
        tracker       = {t: [False]*selected_number_of_units for t in ordered_tests}
        executed_once = {t: False                               for t,o in exec_order_map.items() if o == -1}

        unit_idx = 0      # 0‐based index into units
        exec_loop = 1     # start at order==1

        while True:
            # walk entire test list in tree order
            for idx, t in enumerate(ordered_tests):
                if not self.running:
                    return   # abort immediately

                order = exec_order_map[t]

                if order == -1:
                    # “once‐only” setup: only when all prior tests are done on every unit
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
                            # run it exactly once (unit=None)
                            for fn in funcs_map[t]:
                                fn(report_callback, t, selected_number_of_units, None)
                            executed_once[t] = True

                elif order == exec_loop:
                    # per‐unit run
                    if not tracker[t][unit_idx]:
                        for fn in funcs_map[t]:
                            fn(report_callback, t, selected_number_of_units, unit_idx+1)
                        tracker[t][unit_idx] = True

                # else: skip any order < exec_loop or order > exec_loop

            # end of one full pass over ordered_tests

            # have we finished everything?
            if exec_loop > max_exec and all(executed_once.values()):
                break

            # advance unit or exec_loop
            if unit_idx < selected_number_of_units - 1:
                unit_idx += 1
            else:
                unit_idx = 0
                exec_loop += 1

        # 9) All done
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
            if 1 <= unit_idx <= len(serials):
                serial = str(serials[unit_idx-1]).strip()
            if 1 <= unit_idx <= len(comments):
                comment = comments[unit_idx-1]

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
                        # header block
                        new = next((e for e in evts if e["message type"] == "new test"), evts[0])
                        end = next((e for e in evts if e["message type"] == "test end"), evts[-1])
                        info_df = pd.DataFrame(
                            [[
                                test_name,
                                new.get("result unit"),
                                new["expected range"],
                                end["pass"]
                            ]],
                            columns=["test name", "result unit", "expected range", "pass"]
                        )
                        info_df.to_excel(writer, sheet_name=sheet, index=False)

                        # x/y data from update messages
                        rows = [
                            {"x": u["result"][0], "y": u["result"][1]}
                            for u in evts if u["message type"] == "update"
                            if isinstance(u.get("result"), (list, tuple)) and len(u["result"]) >= 2
                        ]
                        data_df = pd.DataFrame(rows)
                        start_row = info_df.shape[0] + 3
                        data_df.to_excel(writer, sheet_name=sheet, index=False, startrow=start_row)

                    else:
                        # fallback: dump raw events
                        pd.DataFrame(evts).to_excel(writer, sheet_name=sheet, index=False)

        full_messages = pd.DataFrame(self.test_data)
        full_messages.to_excel("full_log.xlsx", index=False)

    def stop_test(self):
        self.running = False

    def is_running(self):
        return self.running