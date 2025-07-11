import React, { useState, useEffect, useRef } from "react";
import io from "socket.io-client";
import {
  Container,
  Typography,
  FormControl,
  InputLabel,
  FormControlLabel,
  Select,
  MenuItem,
  Button,
  Box,
  Checkbox,
  Paper,
  List,
  ListItem,
  ListItemText,
  Collapse,
  IconButton,
  TextField,
  Tabs,
  Tab,
} from "@mui/material";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  ReferenceArea,
  Tooltip,
} from "recharts";

const socket = io("http://localhost:5000");

// Convert backend tests object into array of nodes with children
function convertTestsToItems(testsObj, parent = "") {
  return Object.entries(testsObj).map(([key, value]) => {
    const fullId = parent ? `${parent}/${key}` : key;
    return {
      id: fullId,
      label: key,
      children: convertTestsToItems(value || {}, fullId),
    };
  });
}

// Utility: collect all node IDs that have children (for default open)
function collectAllIds(nodes, map = {}) {
  nodes.forEach((node) => {
    if (node.children && node.children.length) {
      map[node.id] = true;
      collectAllIds(node.children, map);
    }
  });
  return map;
}

// Recursive Tree Node component
function TreeNode({ node, selected, onToggle, openState, onToggleOpen, level = 0 }) {
  return (
    <>
      <ListItem sx={{ pl: level * 4, display: 'flex', alignItems: 'center' }}>
        {node.children.length > 0 ? (
          <IconButton size="small" onClick={() => onToggleOpen(node.id)} sx={{ mr: 1 }}>
            {openState[node.id] ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          </IconButton>
        ) : (
            <Box sx={{ width: 32, mr: 1 }} />
          )}
        <Checkbox
          checked={!!selected[node.id]}
          onClick={() => onToggle(node.id)}
          sx={{ mr: 1 }}
        />
        <ListItemText primary={node.label} />
      </ListItem>
      {node.children.length > 0 && (
        <Collapse in={openState[node.id]} timeout="auto" unmountOnExit>
          <List disablePadding>
            {node.children.map((child) => (
              <TreeNode
                key={child.id}
                node={child}
                selected={selected}
                onToggle={onToggle}
                openState={openState}
                onToggleOpen={onToggleOpen}
                level={level + 1}
              />
            ))}
          </List>
        </Collapse>
      )}
    </>
  );
}


function NumberLine({ value, expectedRange }) {
  if (value == null) return null;

  const [min, max] = expectedRange;
  const range = max - min;
  // extended domain: –25% to 125%
  const start = min - 0.25 * range;
  const end = min + 1.25 * range;
  const full = end - start;

  // Tick locations at –25%, 0%, 25%, 50%, 75%, 100%, 125%
  const ticks = [
    start,
    min,
    min + 0.25 * range,
    min + 0.5 * range,
    min + 0.75 * range,
    max,
    end,
  ];

  return (
    <Box
      sx={{
        position: "relative",
        height: 100,
        my: 2,
        px: 2,                 // horizontal margin from container
        border: "1px solid #ddd",
        borderRadius: 1,
      }}
    >
      {/* Expected‐range band (min→max), inset 5%–95% */}
      <Box
        sx={{
          position: "absolute",
          top: 48,
          left: `calc(5% + ${((min - start) / full) * 90}%)`,
          width: `${((max - min) / full) * 90}%`,
          height: 8,
          backgroundColor: "#bbdefb",
        }}
      />

      {/* Base line, from 5% to 95% */}
      <Box
        sx={{
          position: "absolute",
          top: 52,
          left: "5%",
          right: "5%",
          height: 2,
          backgroundColor: "#000",
        }}
      />

      {/* Render all ticks + labels */}
      {ticks.map((t) => {
        const pct = ((t - start) / full) * 100;
        const pos = `calc(5% + ${pct * 0.9}%)`;
        return (
          <React.Fragment key={t}>
            {/* Tick */}
            <Box
              sx={{
                position: "absolute",
                top: 46,
                left: pos,
                width: 2,
                height: 12,
                backgroundColor: "#000",
                transform: "translateX(-50%)",
              }}
            />
            {/* Label under */}
            <Typography
              variant="caption"
              sx={{
                position: "absolute",
                top: 66,
                left: pos,
                transform: "translateX(-50%)",
              }}
            >
              {t.toFixed(2)}
            </Typography>
          </React.Fragment>
        );
      })}

      {/* Data point, tick + label ABOVE line */}
      {value != null && (() => {
        const pct = ((value - start) / full) * 100;
        const pos = `calc(5% + ${pct * 0.9}%)`;
        return (
          <React.Fragment>
            <Box
              sx={{
                position: "absolute",
                top: 44,
                left: pos,
                width: 4,
                height: 18,
                backgroundColor: "#d32f2f",
                transform: "translateX(-50%)",
              }}
            />
            <Typography
              variant="caption"
              sx={{
                position: "absolute",
                top: 24,    // above the line, not below
                left: pos,
                transform: "translateX(-50%)",
                fontWeight: "bold",
                color: "#d32f2f",
              }}
            >
              {value.toFixed(2)}
            </Typography>
          </React.Fragment>
        );
      })()}
    </Box>
  );
}


function a11yProps(index) {
  return {
    id: `unit-tab-${index}`,
    "aria-controls": `unit-tabpanel-${index}`,
  };
}
export default function App() {
  const [scripts, setScripts] = useState([]);
  const [selectedScript, setSelectedScript] = useState("");
  const [multiUnitSupported, setMultiUnitSupported] = useState(1);
  const [selectedUnits, setSelectedUnits] = useState([]);

  const [treeItems, setTreeItems] = useState([]);
  const [selectedTests, setSelectedTests] = useState({});
  const [openState, setOpenState] = useState({});
  const [testRunning, setTestRunning] = useState(false);
  const [allComplete, setAllComplete] = useState(false);
  const [activeUnit, setActiveUnit] = useState(null);

  // testResults will be an object keyed by unitIndex: { 1: { testName: … }, 2: { … } }
  const [testResults, setTestResults] = useState({});
  const [tabIndex, setTabIndex] = useState(0);

  // Details per unit
  const [serials, setSerials] = useState([""]);
  const [comments, setComments] = useState([""]);
  const [operatorName, setOperatorName] = useState("");
  // state & ref for historical results
  const fileInputRef = useRef(null);
  const [pastMetadata, setPastMetadata] = useState(null);
  const [pastResults,  setPastResults]  = useState(null);
  

  // Fetch scripts & subscribe
  useEffect(() => {
    fetch("http://localhost:5000/scripts")
      .then((res) => res.json())
      .then((data) => setScripts(data.scripts || []));
  }, []);

  useEffect(() => {
    const handleUpdate = (data) => {
      const unit = data["unit index"] || 1;
      setActiveUnit(unit);
      setTestResults((prev) => {
        const unitMap = prev[unit] || {};
        const name = data["test name"];
        const entry = unitMap[name] || {
          testName: name,
          resultType: data["result type"],
          expectedRange: data["expected range"],
          unit: data["result unit"],
          updates: [],
          status: "in progress",
        };

        let { updates, status, finalResult } = entry;
        if (data["message type"] === "new test") {
          updates = [];
          status = "in progress";
        } else if (data["message type"] === "update") {
          // dedupe updates if needed…
          updates = [...updates, { result: data.result, pass: data.pass }];
          status = data.pass;
        } else if (data["message type"] === "test end") {
          status = data.pass;
          finalResult = data.result;
        }

        return {
          ...prev,
          [unit]: {
            ...unitMap,
            [name]: { ...entry, updates, status, finalResult },
          },
        };
      });
    };
    socket.on("test_update", handleUpdate);
    socket.on("test_complete", () => {
      setTestRunning(false);
      setAllComplete(true);
    });
    return () => {
      socket.off("test_update", handleUpdate);
      socket.off("test_complete");
    };
  }, []);

  // Load tests & fetch multi‐unit support
  const loadTests = async () => {
    if (!selectedScript) return;
    const res = await fetch("http://localhost:5000/script_tests", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ script: selectedScript }),
    });
    if (!res.ok) {
      console.error("Load tests failed:", res.status, await res.text());
      return;
    }
    const data = await res.json();

    // assume script_tests now returns { tests: {...}, multiUnitSupportedNumber: N }
    const { tests, multiUnitSupportedNumber } = data;
    setMultiUnitSupported(multiUnitSupportedNumber || 1);
    // default: enable all units [1…N]
    setSelectedUnits(
      Array.from({ length: multiUnitSupportedNumber }, (_, i) => i + 1)
    );

    const items = convertTestsToItems(tests);
    setTreeItems(items);
    // init selections…
    const sel = {};
    const initSel = (nodes) => {
      nodes.forEach((n) => {
        sel[n.id] = true;
        if (n.children.length) initSel(n.children);
      });
    };
    initSel(items);
    setSelectedTests(sel);
    setOpenState(collectAllIds(items, {}));
    setTestResults({});

    // reset details arrays to length 1
    setSerials(Array(1).fill(""));
    setComments(Array(1).fill(""));
  };

  useEffect(() => {
    setSerials((prev) =>
      Array.from({ length: selectedUnits.length }, (_, i) => prev[i] || "")
    );
    setComments((prev) =>
      Array.from({ length: selectedUnits.length }, (_, i) => prev[i] || "")
    );
    setTestResults({});
    setTabIndex(0);
  }, [selectedUnits]);

  const handleToggle = (id) => {
    setSelectedTests((prev) => {
      const next = { ...prev, [id]: !prev[id] };
      const findNode = (nodes) => nodes.find((n) => n.id === id) || nodes.map((n) => findNode(n.children)).find(Boolean);
      const node = findNode(treeItems);
      const toggleDesc = (children) => {
        children.forEach((c) => {
          next[c.id] = next[id];
          if (c.children.length) toggleDesc(c.children);
        });
      };
      if (node && node.children.length) toggleDesc(node.children);
      return next;
    });
  };
  const handleToggleOpen = (id) => setOpenState((prev) => ({ ...prev, [id]: !prev[id] }));

  const startOrResume = async () => {
    const tests = Object.keys(selectedTests).filter((k) => selectedTests[k]);
    await fetch("http://localhost:5000/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        script: selectedScript,
        tests,
        details: {
          serials,
          comments,
          operatorName,
        },
        selectedUnitNumbers: selectedUnits,
      }),
    });
    setTestRunning(true);
    setAllComplete(false);
  };
  const stopTest = async () => { await fetch("http://localhost:5000/stop", { method: 'POST' }); setTestRunning(false); };

  // Open OS file dialog
  const handleViewResults = () => {
    if (fileInputRef.current) {
      fileInputRef.current.value = null;
      fileInputRef.current.click();
    }
  };

  // When user picks a file, upload & parse
  const handleFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("http://localhost:5000/results/upload", {
      method: "POST",
      body: form
    });
    if (!res.ok) {
      console.error("Failed to load results", await res.text());
      return;
    }
    const { metadata, results } = await res.json();
    setPastMetadata(metadata);
    setPastResults(results);
  };


  return (
    <Container sx={{ mt: 4 }}>
      {/* —————————————————————————————————————————————— */}
      {/*            SYSTEM TITLE                          */}
      {/* —————————————————————————————————————————————— */}
      <Typography
        variant="h2"
        align="center"
        gutterBottom
        sx={{ fontWeight: 'bold' }}
      >
        TestMaster 3000
      </Typography>

      {/* --- Select & Load Tests --- */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h4" align="center">
          Select & Load Tests
        </Typography>
        {/* Script selector */}
        <FormControl fullWidth sx={{ mt: 2 }}>
          <InputLabel>Script</InputLabel>
          <Select
            value={selectedScript}
            onChange={(e) => setSelectedScript(e.target.value)}
            disabled={testRunning}
          >
            <MenuItem value="">
              <em>None</em>
            </MenuItem>
            {scripts.map((s) => (
              <MenuItem key={s} value={s}>
                {s}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {/* Unit checkboxes, underneath the script dropdown */}
        {multiUnitSupported > 1 && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle1">Enable Units</Typography>
            <FormControl component="fieldset" sx={{ display: "flex", flexWrap: "wrap", gap: 1, mt: 1 }}>
              {Array.from({ length: multiUnitSupported }, (_, i) => i + 1).map((n) => (
                <FormControlLabel
                  key={n}
                  control={
                    <Checkbox
                      checked={selectedUnits.includes(n)}
                      onChange={() =>
                        setSelectedUnits((prev) =>
                          prev.includes(n)
                            ? prev.filter((u) => u !== n)
                            : [...prev, n].sort((a, b) => a - b)
                        )
                      }
                      disabled={testRunning}
                    />
                  }
                  label={`Unit ${n}`}
                />
              ))}
            </FormControl>
          </Box>
        )}

        {/* Action buttons below the checkboxes */}
        <Box sx={{ display: "flex", gap: 2, mt: 2 }}>
          <Button
            variant="contained"
            onClick={loadTests}
            disabled={!selectedScript || testRunning}
          >
            Load Tests
          </Button>

          <Button
            variant="outlined"
            onClick={handleViewResults}
            disabled={testRunning}
          >
            View Results
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
        </Box>
      </Paper>
        {/* ——— Historical Results Display ——— */}
       {pastResults && (
         <Paper sx={{ p: 3, mt: 3 }}>
           <Typography variant="h4" align="center" gutterBottom>
             Historical Results
           </Typography>
           <Box sx={{ mb: 2 }}>
             <Typography>Script: {pastMetadata["script name"]}</Typography>
             <Typography>Operator: {pastMetadata.operatorName}</Typography>
             <Typography>Timestamp: {pastMetadata.timestamp}</Typography>
             <Typography>Unit: {pastMetadata.unitIndex}</Typography>
             <Typography>Serial: {pastMetadata.serial}</Typography>
             <Typography>Comments: {pastMetadata.comments}</Typography>
           </Box>
        
           {/* Render each result using your existing components */}
           {pastResults.map((r, i) => {
            // Only render vector tests on their 'test end' events
            if (r["result type"] === "vector" && r["message type"] !== "test end") {
              return null;
            }

            // Background tint based on pass/fail
            const bgColor =
              r.pass === true || r.pass === "true"
                ? "rgba(200,255,200,0.5)"
                : r.pass === false || r.pass === "false"
                ? "rgba(255,200,200,0.5)"
                : "transparent";

            return (
              <Box
                key={i}
                sx={{
                  mb: 2,
                  p: 2,
                  border: "1px solid #ccc",
                  borderRadius: 1,
                  backgroundColor: bgColor,
                }}
              >
                {/* Test name */}
                <Typography variant="h6">{r["test name"]}</Typography>

                {/* Boolean */}
                {r["result type"] === "boolean" && (
                  <Typography>Status: {String(r.pass)}</Typography>
                )}

                {/* Number */}
                {r["result type"] === "number" && (
                  <>
                    <NumberLine
                      value={r.result}
                      expectedRange={r["expected range"]}
                    />
                    <Typography>
                       Value: {r.result} [{r["result unit"]}]; pass = {String(r.pass)}
                    </Typography>
                  </>
                )}

                {/* Vector */}
                {r["result type"] === "vector" && (
                  (() => {
                    // only render once, on the 'test end' event
                    if (r["message type"] !== "test end") return null;

                    // pull out axis labels and expected range
                    const [xLabel = "", yLabel = ""] = r["result unit"] || [];
                    const [min = 0, max = 0] = r["expected range"] || [];

                    // gather just the update points
                    const chartData = pastResults
                      .filter(
                        (ev) =>
                          ev["result type"] === "vector" &&
                          ev["test name"] === r["test name"] &&
                          ev["message type"] === "update" &&
                          Array.isArray(ev.result)
                      )
                      .map((ev) => ({
                        x: ev.result[0],
                        y: ev.result[1],
                      }));

                    return (
                      <>
                        <Box sx={{ width: "100%", height: 200, my: 2 }}>
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart
                              data={chartData}
                              margin={{ top: 20, right: 30, left: 20, bottom: 20 }}
                            >
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis
                                dataKey="x"
                                label={{
                                  value: xLabel,
                                  position: "insideBottomRight",
                                  offset: -10,
                                }}
                              />
                              <YAxis
                                domain={[min, max]}
                                label={{
                                  value: yLabel,
                                  angle: -90,
                                  position: "insideLeft",
                                }}
                              />
                              <ReferenceArea
                                y1={min}
                                y2={max}
                                fill="blue"
                                fillOpacity={0.2}
                              />
                              <Line
                                type="monotone"
                                dataKey="y"
                                stroke="#8884d8"
                                dot={false}
                                isAnimationActive={false}
                              />
                              <Tooltip />
                            </LineChart>
                          </ResponsiveContainer>
                        </Box>
                        <Typography>pass = {String(r.pass)}</Typography>
                      </>
                    );
                  })()
                )}

                {/* Image */}
                {r["result type"] === "image" && (
                  <>
                    <img
                      src={r.result}
                      alt={r["test name"]}
                      style={{ maxWidth: "100%" }}
                    />
                    <Typography>pass = {String(r.pass)}</Typography>
                  </>
                )}
              </Box>
            );
          })}
         </Paper>
       )}

      {/* --- Details per unit --- */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h5" gutterBottom>
          Details
        </Typography>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {selectedUnits.map((unit, idx) => (
            <TextField
              key={`serial-${idx}`}
              label={`Serial # unit ${unit}`}
              value={serials[idx] || ""}
              onChange={(e) =>
                setSerials((prev) => {
                  const next = [...prev];
                  next[idx] = e.target.value;
                  return next;
                })
              }
              disabled={testRunning}
              fullWidth
            />
          ))}
          {selectedUnits.map((unit, idx) => (
            <TextField
              key={`comments-${idx}`}
              label={`Comments unit ${unit}`}
              value={comments[idx] || ""}
              onChange={(e) =>
                setComments((prev) => {
                  const next = [...prev];
                  next[idx] = e.target.value;
                  return next;
                })
              }
              disabled={testRunning}
              multiline
              rows={2}
              fullWidth
            />
          ))}

          <TextField
            label="Operator Name"
            value={operatorName}
            onChange={(e) => setOperatorName(e.target.value)}
            disabled={testRunning}
            fullWidth
          />
        </Box>
      </Paper>

      <Paper sx={{ p: 3, mb: 3 }}>
        <Typography variant="h5" gutterBottom>Tests</Typography>
        <List>
          {treeItems.map((node) => (
            <TreeNode
              key={node.id}
              node={node}
              selected={selectedTests}
              onToggle={handleToggle}
              openState={openState}
              onToggleOpen={handleToggleOpen}
            />
          ))}
        </List>
        <Box sx={{ textAlign: 'center', mt: 2 }}>
          <Button
            variant="contained"
            color={testRunning ? 'secondary' : 'primary'}
            onClick={testRunning ? stopTest : startOrResume}
            disabled={!treeItems.length || !selectedScript || selectedUnits.length === 0}
          >
            {testRunning ? 'Stop Test' : 'Start Test'}
          </Button>
        </Box>
      </Paper>

      {/* --- Results Tabs --- */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          Results
        </Typography>
        {(
        <Tabs
          value={tabIndex}
          onChange={(_, v) => setTabIndex(v)}
          sx={{ mb: 2 }}
        >
          {selectedUnits.map((unit, idx) => (
            <Tab
              key={idx}
              label={`Unit ${unit}`}
              {...a11yProps(idx)}
              sx={
                activeUnit === unit
                  ? { fontWeight: "bold", color: "primary.main" }
                  : {}
              }
            />
          ))}
        </Tabs>
        )}
        {allComplete && (
          <Box sx={{ my: 1, textAlign: "center" }}>
            <Typography variant="subtitle1" color="success.main">
              🎉 All tests completed!
    </Typography>
          </Box>
        )}

        {selectedUnits.map((unit, idx) => {
          const resultsForUnit = testResults[unit] || {};
          return (
            <div
              role="tabpanel"
              hidden={tabIndex !== idx}
              key={`panel-${idx}`}
              id={`unit-tabpanel-${idx}`}
              aria-labelledby={`unit-tab-${idx}`}
            >
              {tabIndex === idx && (
                Object.values(resultsForUnit).length === 0 ? (
                  <Typography>No results yet for unit {unit}.</Typography>
                ) : (
                    Object.values(resultsForUnit).map((res) => {
                      const [x_label = "", y_label = ""] = res.unit || [];
                      return (
                        <Box
                          key={res.testName}
                          sx={{
                            mb: 2,
                            p: 2,
                            border: "1px solid #ccc",
                            borderRadius: 1,
                            backgroundColor:
                              res.status === "true"
                                ? "rgba(200,255,200,0.5)"
                                : res.status === "false"
                                  ? "rgba(255,200,200,0.5)"
                                  : "transparent",
                          }}
                        >
                          <Typography variant="h6">{res.testName}</Typography>


                          {res.resultType === 'number' && (
                            <>
                              <NumberLine
                                value={res.updates.length ? res.updates[res.updates.length - 1].result : null}
                                expectedRange={res.expectedRange}
                              />
                              <Typography>
                                Value:{" "}
                                {res.updates.length
                                  ? `${res.updates[res.updates.length - 1].result} [${res.unit}]`
                                  : "N/A"
                                }{" "}
                                ; pass = {res.status}
                              </Typography>
                            </>
                          )}

                          {res.resultType === 'boolean' && (
                            <Typography>
                              Status: {res.updates.length ? res.updates[res.updates.length - 1].result.toString() : 'N/A'}; pass = {res.status}
                            </Typography>
                          )}

                          {res.resultType === "vector" && (
                            <>
                              <Box sx={{ width: "100%", height: 200 }}>
                                <ResponsiveContainer width="100%" height="100%">
                                  <LineChart
                                    data={res.updates.map((u) => ({
                                      x: u.result[0],
                                      y: u.result[1],
                                    }))}
                                    margin={{ top: 20, right: 30, left: 20, bottom: 20 }}
                                  >
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis
                                      dataKey="x"
                                      label={{
                                        value: x_label,
                                        position: "insideBottomRight",
                                        offset: -10
                                      }}
                                    />
                                    <YAxis
                                      domain={res.expectedRange}
                                      label={{
                                        value: y_label,
                                        angle: -90,
                                        position: "insideLeft"
                                      }}
                                    />
                                    <Tooltip />
                                    <ReferenceArea
                                      y1={res.expectedRange[0]}
                                      y2={res.expectedRange[1]}
                                      fill="blue"
                                      fillOpacity={0.2}
                                    />
                                    <Line
                                      type="monotone"
                                      dataKey="y"
                                      stroke="#8884d8"
                                      dot={false}
                                      isAnimationActive={false}
                                    />
                                  </LineChart>
                                </ResponsiveContainer>
                              </Box>
                              <Typography>pass = {res.status}</Typography>
                            </>
                          )}

                          {res.resultType === 'image' && res.finalResult && (
                            <Box>
                              <img src={res.finalResult} alt={res.testName} style={{ maxWidth: '100%' }} />
                              <Typography>pass = {res.status}</Typography>
                            </Box>
                          )}
                        </Box>
                      );
                    })
                  )
              )}
            </div>
          );
        })}
      </Paper>
    </Container>
  );
}
