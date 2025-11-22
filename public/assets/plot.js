(() => {
  const dataEl = document.getElementById("neuro-data");
  const plotEl = document.getElementById("neuro-plot");
  const legendEl = document.getElementById("nt-legend");
  const PlotLib = window.Plot;

  if (!dataEl || !plotEl || !PlotLib) {
    return;
  }

  const payload = JSON.parse(dataEl.textContent || "{}");
  const methods =
    (Array.isArray(payload.methods) && payload.methods.length
      ? payload.methods
      : Array.from(new Set((payload.points || []).map((d) => d.method || "Unknown")))) || [];
  const xRange = payload.xRange || { min: 0, max: 1 };
  const clampSeriesX = (series = []) =>
    series.filter(
      (point) =>
        typeof point.decimalYear === "number" &&
        point.decimalYear >= xRange.min &&
        point.decimalYear <= xRange.max
    );
  const regressions = payload.regressions || {};
  const rawFrontierSeries = clampSeriesX(regressions.frontier?.series || []);
  const rawMethodRegressions = Array.isArray(payload.methodRegressions)
    ? payload.methodRegressions.map((reg) => ({
        ...reg,
        series: clampSeriesX(reg.series || []),
      }))
    : [];
  const dataMax =
    Number(payload.maxNeurons) ||
    Math.max(1, ...((payload.points || []).map((d) => Number(d.neurons)) || [1]));
  const references = Array.isArray(payload.references) ? payload.references : [];
  const palette = [
    "#6c2e2e",
    "#267fb5",
    "#248232",
    "#d8576b",
    "#b48b7d",
    "#f0a202",
    "#50514f",
    "#7f95d1",
  ];

  const methodColors = new Map();
  methods.forEach((method, idx) => {
    const normalized = typeof method === "string" ? method : "Unknown";
    methodColors.set(normalized, palette[idx % palette.length]);
  });
  if (!methodColors.has("Unknown")) {
    methodColors.set("Unknown", "#50514f");
  }

  const formatter = new Intl.NumberFormat("en-US");
  const points = Array.isArray(payload.points)
    ? payload.points.map((point) => ({
        ...point,
        color: methodColors.get(point.method) || methodColors.get("Unknown"),
        tipTitle: [
          `${point.dateLabel} · ${point.publication}`,
          `${formatter.format(point.neurons)} neurons (${point.method})`,
          point.authors,
          point.doi,
        ]
          .filter(Boolean)
          .join("\n"),
      }))
    : [];

  if (legendEl) {
    legendEl.replaceChildren(
      ...methods.map((method) => {
        const wrapper = document.createElement("div");
        wrapper.className = "nt-legend-item";
        const swatch = document.createElement("span");
        swatch.className = "nt-legend-swatch";
        swatch.style.backgroundColor = methodColors.get(method);
        const label = document.createElement("span");
        label.className = "nt-legend-label";
        label.textContent = method;
        wrapper.appendChild(swatch);
        wrapper.appendChild(label);
        return wrapper;
      })
    );
  }

  const referenceMax = references.reduce(
    (max, ref) => Math.max(max, Number(ref.neurons) || 0),
    0
  );
  const axisMax = Math.max(dataMax, referenceMax, 1);
  const maxPower = Math.max(0, Math.ceil(Math.log10(axisMax)));
  const yTicks = Array.from({ length: maxPower + 1 }, (_, idx) => 10 ** idx);
  const yDomainMax = Math.max(axisMax, yTicks[yTicks.length - 1] || axisMax);
  const clampYValue = (value) => Math.min(Math.max(value, 1), yDomainMax);
  const clampSeriesY = (series = []) =>
    series.map((point) => ({
      ...point,
      neurons: clampYValue(Number(point.neurons) || 1),
    }));
  const frontierSeries = clampSeriesY(rawFrontierSeries);
  const methodRegressions = rawMethodRegressions.map((reg) => ({
    ...reg,
    series: clampSeriesY(reg.series || []),
  }));
  const visibleReferences = references.filter((ref) => ref.neurons <= yDomainMax);
  const tickLabel = (value) => {
    if (!value || value < 1) return "";
    const power = Math.round(Math.log10(value));
    return Number.isFinite(power) ? `1e${power}` : formatter.format(value);
  };

  const renderPlot = () => {
    const width = plotEl.clientWidth || 960;
    const marks = [];

    if (visibleReferences.length && PlotLib.ruleY) {
      marks.push(
        PlotLib.ruleY(visibleReferences, {
          y: "neurons",
          stroke: "#b5985a",
          strokeDasharray: "3,4",
          strokeOpacity: 0.8,
        })
      );
    }

    if (visibleReferences.length && PlotLib.text) {
      marks.push(
        PlotLib.text(visibleReferences, {
          y: "neurons",
          text: (d) => d.label.replace(/\s*\(.*?\)/, ""),
          frameAnchor: "right",
          dx: 8,
          dy: 0,
          clip: false,
          textAnchor: "start",
          fill: "#6c2e2e",
          fontSize: 11,
          stroke: "white",
          strokeWidth: 4,
          paintOrder: "stroke",
        })
      );
    }

    if (Array.isArray(frontierSeries) && frontierSeries.length && PlotLib.line) {
      marks.push(
        PlotLib.line(frontierSeries, {
          x: "decimalYear",
          y: "neurons",
          stroke: "#d8576b",
          strokeWidth: 2.5,
          strokeDasharray: "6,3",
        })
      );
    }

    methodRegressions.forEach((reg) => {
      if (!reg?.series?.length || !PlotLib.line) return;
      marks.push(
        PlotLib.line(reg.series, {
          x: "decimalYear",
          y: "neurons",
          stroke: methodColors.get(reg.method) || "#267fb5",
          strokeWidth: 2,
          strokeDasharray: "4,2",
        })
      );
    });

    if (points.length && PlotLib.dot) {
      marks.push(
        PlotLib.dot(points, {
          x: "decimalYear",
          y: "neurons",
          fill: (d) => d.color,
          stroke: "#111",
          strokeWidth: 0.5,
          r: 4,
          title: (d) => d.tipTitle,
        })
      );
    }

    if (points.length && PlotLib.pointer && PlotLib.dot) {
      marks.push(
        PlotLib.dot(
          points,
          PlotLib.pointer({
            x: "decimalYear",
            y: "neurons",
            r: 8,
            fill: (d) => d.color,
            stroke: "#f5f4e9",
            strokeWidth: 2,
            maxRadius: 80,
          })
        )
      );
    }

    if (points.length && PlotLib.tip && PlotLib.pointer) {
      marks.push(
        PlotLib.tip(
          points,
          PlotLib.pointer({
            x: "decimalYear",
            y: "neurons",
            title: (d) => d.tipTitle,
            lineHeight: 1.3,
            textOverflow: "ellipsis",
            anchor: "top-left",
            preferredAnchor: "top-left",
          })
        )
      );
    }

    if (PlotLib.ruleY) {
      marks.unshift(PlotLib.ruleY([1], { stroke: "#bbb", strokeWidth: 0.5 }));
    }

    const chart = PlotLib.plot({
      width,
      height: 460,
      marginTop: 24,
      marginRight: 120,
      marginBottom: 55,
      marginLeft: 70,
      x: {
        label: "Year",
        domain: [xRange.min, xRange.max],
        tickFormat: (d) => `${Math.floor(d)}`,
        grid: true,
      },
      y: {
        label: "Neurons simultaneously recorded",
        type: "log",
        grid: true,
        domain: [1, yDomainMax],
        tickFormat: tickLabel,
        ticks: yTicks,
      },
      marks,
    });

    plotEl.replaceChildren(chart);

    chart.addEventListener("click", (event) => {
      const value = chart.value;
      const datum = Array.isArray(value) ? value[0] : value;
      if (datum?.doi) {
        window.open(datum.doi, "_blank", "noopener");
        event.stopPropagation();
      }
    });
  };

  renderPlot();

  let resizeHandle;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeHandle);
    resizeHandle = window.setTimeout(renderPlot, 200);
  });
})();
