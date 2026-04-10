(function () {
  const h = React.createElement
  const { useEffect, useMemo, useRef, useState } = React

  async function fetchJson(path, options) {
    const response = await fetch(path, options)
    if (!response.ok) {
      let message = `Request failed (${response.status})`
      try {
        const payload = await response.json()
        if (payload && typeof payload.detail === "string") {
          message = payload.detail
        }
      } catch (_) {
        // Use default message when the response is not JSON.
      }
      throw new Error(message)
    }
    return response.json()
  }

  function Header({ activeView, setActiveView }) {
    const tabs = [
      ["graph", "Graph Visualization"],
      ["activity", "Activity Feed"],
      ["review", "Review Workflow"],
      ["health", "Health Dashboard"],
      ["escalated", "Escalated Items"],
    ]

    return h(
      "header",
      { className: "header" },
      h(
        "div",
        { className: "title-row" },
        h(
          "div",
          null,
          h("h1", { className: "title" }, "A-Priori Human Audit UI"),
          h(
            "p",
            { className: "subtitle" },
            "Single-process local SPA for graph auditing and reviewer actions"
          )
        ),
        h(
          "nav",
          { className: "nav" },
          tabs.map(([id, label]) =>
            h(
              "button",
              {
                key: id,
                className: activeView === id ? "active" : "",
                onClick: () => setActiveView(id),
              },
              label
            )
          )
        )
      )
    )
  }

  function GraphView({ active }) {
    const [concepts, setConcepts] = useState([])
    const [centerId, setCenterId] = useState("")
    const [radius, setRadius] = useState(2)
    const [edgeType, setEdgeType] = useState("")
    const [minConfidence, setMinConfidence] = useState(0)
    const [highlightLabel, setHighlightLabel] = useState("")
    const [layout, setLayout] = useState("cose")
    const [graphData, setGraphData] = useState(null)
    const [selectedData, setSelectedData] = useState(null)
    const [status, setStatus] = useState("idle")
    const [error, setError] = useState("")
    const cyRef = useRef(null)
    const containerRef = useRef(null)

    useEffect(() => {
      fetchJson("/api/concepts")
        .then((rows) => {
          setConcepts(rows)
          if (rows.length > 0) {
            setCenterId(String(rows[0].id))
          }
        })
        .catch((err) => setError(err.message))
    }, [])

    const allLabels = useMemo(() => {
      const labels = new Set()
      concepts.forEach((concept) => {
        ;(concept.labels || []).forEach((label) => labels.add(label))
      })
      return Array.from(labels).sort()
    }, [concepts])

    useEffect(() => {
      if (!centerId) {
        return
      }
      const params = new URLSearchParams({
        center: centerId,
        radius: String(radius),
        layout,
      })
      if (edgeType) {
        params.set("edge_type", edgeType)
      }
      if (minConfidence > 0) {
        params.set("min_confidence", String(minConfidence))
      }
      if (highlightLabel) {
        params.set("highlight_label", highlightLabel)
      }
      setStatus("loading")
      setError("")
      fetchJson(`/api/graph?${params.toString()}`)
        .then((payload) => {
          setGraphData(payload)
          setStatus("ready")
        })
        .catch((err) => {
          setError(err.message)
          setStatus("error")
        })
    }, [centerId, radius, edgeType, minConfidence, highlightLabel, layout])

    useEffect(() => {
      if (!active || !graphData || !containerRef.current) {
        return
      }
      if (cyRef.current) {
        cyRef.current.destroy()
      }
      const elements = []
      ;(graphData.nodes || []).forEach((node) => {
        elements.push({ data: node.data, position: node.position || undefined })
      })
      ;(graphData.edges || []).forEach((edge) => {
        elements.push({ data: edge.data })
      })

      const cy = cytoscape({
        container: containerRef.current,
        elements,
        style: [
          {
            selector: "node",
            style: {
              label: "data(label)",
              "font-size": 11,
              "text-wrap": "ellipsis",
              "text-max-width": 120,
              "text-halign": "center",
              "text-valign": "center",
              width: 16,
              height: 16,
              "background-color": "data(color)",
              opacity: "data(opacity)",
              "border-width": "mapData(highlighted, 0, 1, 0, 3)",
              "border-color": "#0c4a6e",
            },
          },
          {
            selector: "edge",
            style: {
              width: "mapData(weight, 0, 1, 1, 4)",
              "line-color": "#64748b",
              "target-arrow-color": "#64748b",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              opacity: "data(opacity)",
              "line-style": "data(line_style)",
            },
          },
          {
            selector: ":selected",
            style: {
              "overlay-color": "#0369a1",
              "overlay-opacity": 0.15,
              "overlay-padding": 6,
            },
          },
        ],
        layout: { name: layout, animate: false },
      })

      cy.on("tap", "node, edge", (event) => {
        setSelectedData(event.target.data())
      })
      cyRef.current = cy

      return () => {
        cy.destroy()
      }
    }, [active, graphData, layout])

    return h(
      "section",
      {
        id: "graph-view",
        className: "panel",
        style: { display: active ? "block" : "none" },
      },
      h("h2", null, "Graph Visualization"),
      h(
        "p",
        { className: "meta" },
        "Interactive graph with edge type, confidence threshold, and label highlighting filters"
      ),
      h(
        "div",
        { className: "controls" },
        h(
          "label",
          null,
          "Center concept",
          h(
            "select",
            { value: centerId, onChange: (event) => setCenterId(event.target.value) },
            concepts.map((concept) =>
              h("option", { key: concept.id, value: String(concept.id) }, concept.name)
            )
          )
        ),
        h(
          "label",
          null,
          "Radius",
          h("input", {
            type: "number",
            min: 1,
            max: 4,
            value: radius,
            onChange: (event) => setRadius(Number(event.target.value) || 1),
          })
        ),
        h(
          "label",
          null,
          "Edge type",
          h(
            "select",
            { value: edgeType, onChange: (event) => setEdgeType(event.target.value) },
            h("option", { value: "" }, "All"),
            ["structural", "semantic", "temporal", "causal", "similarity", "dependency", "hierarchical", "usage"].map((value) =>
              h("option", { key: value, value }, value)
            )
          )
        ),
        h(
          "label",
          null,
          "Min confidence",
          h("input", {
            type: "number",
            min: 0,
            max: 1,
            step: 0.05,
            value: minConfidence,
            onChange: (event) => setMinConfidence(Number(event.target.value) || 0),
          })
        ),
        h(
          "label",
          null,
          "Highlight label",
          h(
            "select",
            {
              value: highlightLabel,
              onChange: (event) => setHighlightLabel(event.target.value),
            },
            h("option", { value: "" }, "None"),
            allLabels.map((label) => h("option", { key: label, value: label }, label))
          )
        ),
        h(
          "label",
          null,
          "Layout",
          h(
            "select",
            { value: layout, onChange: (event) => setLayout(event.target.value) },
            ["cose", "breadthfirst", "circle", "concentric", "grid"].map((name) =>
              h("option", { key: name, value: name }, name)
            )
          )
        )
      ),
      error ? h("div", { className: "error" }, error) : null,
      h(
        "div",
        { className: "split" },
        h(
          "div",
          null,
          h("div", { className: "cytoscape-canvas", ref: containerRef }),
          h(
            "p",
            { className: "meta" },
            status === "loading"
              ? "Loading graph..."
              : graphData
                ? `${graphData.nodes.length} nodes, ${graphData.edges.length} edges`
                : "No graph loaded"
          )
        ),
        h(
          "div",
          { className: "card" },
          h("h3", null, "Inspect Selection"),
          selectedData
            ? h("pre", { className: "code-block" }, JSON.stringify(selectedData, null, 2))
            : h("p", { className: "meta" }, "Click a node or edge to inspect payload fields")
        )
      )
    )
  }

  function ActivityView({ active }) {
    const [entries, setEntries] = useState([])
    const [expanded, setExpanded] = useState({})
    const [error, setError] = useState("")

    useEffect(() => {
      if (!active) {
        return
      }
      fetchJson("/api/activity?limit=50")
        .then(setEntries)
        .catch((err) => setError(err.message))
    }, [active])

    return h(
      "section",
      { className: "panel", style: { display: active ? "block" : "none" } },
      h("h2", null, "Activity Feed"),
      error ? h("div", { className: "error" }, error) : null,
      h(
        "div",
        { className: "list" },
        entries.map((entry) => {
          const isOpen = !!expanded[entry.id]
          return h(
            "article",
            { className: "card", key: entry.id },
            h(
              "div",
              { style: { display: "flex", justifyContent: "space-between", gap: "0.5rem" } },
              h(
                "div",
                null,
                h("h3", null, `Iteration ${entry.iteration}`),
                h(
                  "p",
                  { className: "meta" },
                  `${new Date(entry.created_at).toLocaleString()} • ${entry.work_item ? entry.work_item.item_type : "no work item"}`
                )
              ),
              h(
                "span",
                { className: `badge ${entry.passed ? "pass" : "fail"}` },
                entry.passed ? "PASS" : "FAIL"
              )
            ),
            h(
              "p",
              null,
              entry.concept
                ? `Concept: ${entry.concept.name}`
                : "No concept linked"
            ),
            h(
              "p",
              { className: "meta" },
              `Scores: ${entry.co_regulation_scores ? JSON.stringify(entry.co_regulation_scores) : "none"}`
            ),
            entry.failure_record
              ? h(
                  "div",
                  null,
                  h(
                    "button",
                    {
                      onClick: () =>
                        setExpanded((prev) => ({
                          ...prev,
                          [entry.id]: !isOpen,
                        })),
                    },
                    isOpen ? "Hide failure details" : "Show failure details"
                  ),
                  isOpen
                    ? h(
                        "pre",
                        { className: "code-block" },
                        JSON.stringify(entry.failure_record, null, 2)
                      )
                    : null
                )
              : null
          )
        })
      )
    )
  }

  function ReviewView({ active }) {
    const [concepts, setConcepts] = useState([])
    const [conceptId, setConceptId] = useState("")
    const [detail, setDetail] = useState(null)
    const [errorTypes, setErrorTypes] = useState([])
    const [reviewer, setReviewer] = useState("human-reviewer")
    const [errorType, setErrorType] = useState("")
    const [description, setDescription] = useState("")
    const [correctionDetails, setCorrectionDetails] = useState("")
    const [statusMessage, setStatusMessage] = useState("")
    const [error, setError] = useState("")

    useEffect(() => {
      if (!active) {
        return
      }
      Promise.all([fetchJson("/api/concepts"), fetchJson("/api/review/error-types")])
        .then(([list, errors]) => {
          setConcepts(list)
          if (list.length > 0 && !conceptId) {
            setConceptId(String(list[0].id))
          }
          const values = (errors && errors.error_types) || []
          setErrorTypes(values)
          if (values.length > 0 && !errorType) {
            setErrorType(values[0])
          }
        })
        .catch((err) => setError(err.message))
    }, [active])

    useEffect(() => {
      if (!active || !conceptId) {
        return
      }
      fetchJson(`/api/concepts/${conceptId}`)
        .then((payload) => {
          setDetail(payload)
          setDescription(payload.description || "")
        })
        .catch((err) => setError(err.message))
    }, [active, conceptId])

    async function runAction(action) {
      if (!conceptId) {
        return
      }
      setError("")
      setStatusMessage("")
      try {
        if (action === "verify") {
          await fetchJson(`/api/concepts/${conceptId}/verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reviewer }),
          })
        }
        if (action === "flag") {
          await fetchJson(`/api/concepts/${conceptId}/flag`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reviewer }),
          })
        }
        if (action === "correct") {
          await fetchJson(`/api/concepts/${conceptId}/correct`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              reviewer,
              error_type: errorType,
              correction_details: correctionDetails || null,
              description,
            }),
          })
        }
        const updated = await fetchJson(`/api/concepts/${conceptId}`)
        setDetail(updated)
        setStatusMessage(`Action '${action}' submitted successfully`)
      } catch (err) {
        setError(err.message)
      }
    }

    return h(
      "section",
      { className: "panel", style: { display: active ? "block" : "none" } },
      h("h2", null, "Review Workflow"),
      h(
        "div",
        { className: "controls" },
        h(
          "label",
          null,
          "Concept",
          h(
            "select",
            { value: conceptId, onChange: (event) => setConceptId(event.target.value) },
            concepts.map((concept) =>
              h("option", { key: concept.id, value: String(concept.id) }, concept.name)
            )
          )
        ),
        h(
          "label",
          null,
          "Reviewer",
          h("input", {
            type: "text",
            value: reviewer,
            onChange: (event) => setReviewer(event.target.value),
          })
        )
      ),
      error ? h("div", { className: "error" }, error) : null,
      statusMessage ? h("p", { className: "meta" }, statusMessage) : null,
      detail
        ? h(
            "div",
            { className: "split" },
            h(
              "div",
              { className: "card" },
              h("h3", null, detail.name),
              h("p", null, detail.description),
              h(
                "div",
                { style: { display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.6rem" } },
                h("button", { className: "success", onClick: () => runAction("verify") }, "Verify"),
                h("button", { className: "warning", onClick: () => runAction("correct") }, "Correct"),
                h("button", { className: "danger", onClick: () => runAction("flag") }, "Flag")
              ),
              h("h4", null, "Correction Form"),
              h(
                "div",
                { className: "controls" },
                h(
                  "label",
                  null,
                  "Error type",
                  h(
                    "select",
                    { value: errorType, onChange: (event) => setErrorType(event.target.value) },
                    errorTypes.map((value) => h("option", { key: value, value }, value))
                  )
                ),
                h(
                  "label",
                  null,
                  "Correction details",
                  h("input", {
                    type: "text",
                    value: correctionDetails,
                    onChange: (event) => setCorrectionDetails(event.target.value),
                  })
                )
              ),
              h(
                "label",
                null,
                "Updated description",
                h("textarea", {
                  rows: 4,
                  value: description,
                  onChange: (event) => setDescription(event.target.value),
                })
              )
            ),
            h(
              "div",
              { className: "card" },
              h("h3", null, "Code References"),
              (detail.code_references || []).length === 0
                ? h("p", { className: "meta" }, "No code references available")
                : detail.code_references.map((ref, index) =>
                    h(
                      "div",
                      { key: `${ref.file_path}-${index}` },
                      h(
                        "p",
                        { className: "meta" },
                        `${ref.symbol || "(symbol)"} • ${ref.file_path}${ref.line_range ? `:${ref.line_range[0]}-${ref.line_range[1]}` : ""}`
                      ),
                      h("pre", { className: "code-block" }, ref.snippet || "No snippet available")
                    )
                  )
            )
          )
        : h("p", { className: "meta" }, "Select a concept to review")
    )
  }

  function HealthView({ active }) {
    const [health, setHealth] = useState(null)
    const [error, setError] = useState("")

    const load = () => {
      fetchJson("/api/health")
        .then(setHealth)
        .catch((err) => setError(err.message))
    }

    useEffect(() => {
      if (active) {
        load()
      }
    }, [active])

    function renderMetric(label, value, target) {
      const ratio = Math.max(0, Math.min(1, value / (target || 1)))
      return h(
        "div",
        { className: "card", key: label },
        h("h3", null, label),
        h("p", null, `Current: ${(value * 100).toFixed(1)}%`),
        h("p", { className: "meta" }, `Target: ${(target * 100).toFixed(1)}%`),
        h("div", { className: "metric-bar" }, h("span", { style: { width: `${ratio * 100}%` } }))
      )
    }

    return h(
      "section",
      { className: "panel", style: { display: active ? "block" : "none" } },
      h("h2", null, "Health Dashboard"),
      h("button", { className: "primary", onClick: load }, "Refresh"),
      error ? h("div", { className: "error" }, error) : null,
      health
        ? h(
            "div",
            { className: "list", style: { marginTop: "0.75rem" } },
            h(
              "div",
              { className: "metric-grid" },
              renderMetric(
                "Coverage",
                health.metrics.coverage,
                health.targets.coverage
              ),
              renderMetric(
                "Freshness",
                health.metrics.freshness,
                health.targets.freshness
              ),
              renderMetric(
                "Blast Radius",
                health.metrics.blast_radius_completeness,
                health.targets.blast_radius_completeness
              )
            ),
            h(
              "div",
              { className: "card" },
              h("h3", null, "Effective Priority Weights"),
              h(
                "pre",
                { className: "code-block" },
                JSON.stringify(health.effective_priority_weights, null, 2)
              )
            ),
            h(
              "div",
              { className: "card" },
              h("h3", null, "Queue Status"),
              h("p", null, `Work queue depth: ${health.work_queue_depth}`),
              h("p", null, `Escalated count: ${health.escalated_count}`)
            )
          )
        : h("p", { className: "meta" }, "Loading health metrics...")
    )
  }

  function EscalatedItemsView({ active }) {
    const [items, setItems] = useState([])
    const [expanded, setExpanded] = useState({})
    const [error, setError] = useState("")

    useEffect(() => {
      if (!active) {
        return
      }
      fetchJson("/api/escalated-items")
        .then(setItems)
        .catch((err) => setError(err.message))
    }, [active])

    return h(
      "section",
      { className: "panel", style: { display: active ? "block" : "none" } },
      h("h2", null, "Escalated Items"),
      error ? h("div", { className: "error" }, error) : null,
      h(
        "div",
        { className: "list" },
        items.map((item) => {
          const key = String(item.id)
          const isOpen = !!expanded[key]
          return h(
            "article",
            { className: "card", key },
            h("h3", null, item.description || item.item_type),
            h(
              "p",
              { className: "meta" },
              `Concept: ${item.associated_concept.name || item.associated_concept.id}`
            ),
            h("p", null, `Failure count: ${item.failure_count}`),
            h(
              "button",
              {
                onClick: () =>
                  setExpanded((prev) => ({
                    ...prev,
                    [key]: !isOpen,
                  })),
              },
              isOpen ? "Hide failure history" : "Show failure history"
            ),
            isOpen
              ? h(
                  "div",
                  { className: "list", style: { marginTop: "0.5rem" } },
                  (item.failure_history || []).map((attempt, index) =>
                    h(
                      "div",
                      { className: "card", key: `${key}-attempt-${index}` },
                      h(
                        "p",
                        { className: "meta" },
                        `${new Date(attempt.attempted_at).toLocaleString()} • ${attempt.model_used}`
                      ),
                      h("p", null, `Reason: ${attempt.failure_reason}`),
                      h(
                        "p",
                        null,
                        `Scores: ${attempt.quality_scores ? JSON.stringify(attempt.quality_scores) : "none"}`
                      ),
                      h("p", null, `Feedback: ${attempt.reviewer_feedback || "none"}`)
                    )
                  )
                )
              : null
          )
        })
      )
    )
  }

  function App() {
    const [activeView, setActiveView] = useState("graph")
    return h(
      "div",
      { className: "app" },
      h(Header, { activeView, setActiveView }),
      h(
        "main",
        { className: "main" },
        h(GraphView, { active: activeView === "graph" }),
        h(ActivityView, { active: activeView === "activity" }),
        h(ReviewView, { active: activeView === "review" }),
        h(HealthView, { active: activeView === "health" }),
        h(EscalatedItemsView, { active: activeView === "escalated" })
      )
    )
  }

  const root = document.getElementById("graph-view")
  ReactDOM.createRoot(root).render(h(App))
})()
