// Console client-side behaviour, served same-origin so a strict CSP (script-src 'self')
// can forbid every other script origin. Nothing here fetches anything external.
//
// Two features, each guarded by the element it needs, so this one file is safe to load on
// every page: the prompt page's copy button, and the message-flow graph.

(function () {
  "use strict";

  // -- copy to clipboard --------------------------------------------------
  // Any button carrying data-copy="<id>" copies that element's text. A secret shown
  // once should never depend on the reader selecting it accurately by hand.
  function textOf(el) {
    return el ? (typeof el.value === "string" ? el.value : el.textContent || "") : "";
  }

  // Select the element's text, whatever kind of element it is. `select()` exists only
  // on inputs; a <code> block needs a Range, and without one the "press ctrl/cmd+C"
  // fallback below would be advice about a selection that was never made.
  function selectText(el) {
    if (typeof el.select === "function") {
      el.select();
      return;
    }
    var range = document.createRange();
    range.selectNodeContents(el);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  }

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", async function () {
      var target = document.getElementById(button.getAttribute("data-copy"));
      var said = document.getElementById(button.getAttribute("data-said") || "said");
      if (!target) return;
      var text = textOf(target).trim();
      selectText(target);

      // navigator.clipboard exists only in a secure context. A self-hosted hub is
      // typically plain http on a LAN name — neither https nor localhost — so on
      // Chrome and its derivatives the whole API is simply absent, and the button
      // appeared to do nothing at all.
      if (window.isSecureContext && navigator.clipboard) {
        try {
          await navigator.clipboard.writeText(text);
          if (said) said.textContent = "Copied.";
          return;
        } catch (e) {
          // Permission refused; fall through to the older path.
        }
      }

      // execCommand is deprecated and still the only thing that copies over http.
      try {
        if (document.execCommand("copy")) {
          if (said) said.textContent = "Copied.";
          return;
        }
      } catch (e) {
        // Nothing left to try.
      }
      if (said) said.textContent = "Selected — press ctrl/cmd+C.";
    });
  });

  // -- message-flow graph -------------------------------------------------
  // Data is injected as a non-executable <script type="application/json">, which a strict
  // script-src allows because it is data, not code. vis is the vendored, same-origin lib.
  var mount = document.getElementById("graph");
  var dataEl = document.getElementById("graph-data");
  if (mount && dataEl && typeof vis !== "undefined") {
    var payload = JSON.parse(dataEl.textContent || "{}");
    var dark =
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;

    var nodes = new vis.DataSet(
      (payload.nodes || []).map(function (n) {
        return {
          id: n.id,
          label: n.label || n.id,
          value: n.value || 1,
          color: {
            background: n.recent ? "#dcfce7" : "#e5e7eb",
            border: n.recent ? "#16a34a" : "#9ca3af",
          },
        };
      })
    );
    var edges = new vis.DataSet(
      (payload.edges || []).map(function (e, i) {
        return { id: i, from: e.from, to: e.to, label: String(e.count), value: e.count };
      })
    );

    var net = new vis.Network(
      mount,
      { nodes: nodes, edges: edges },
      {
        nodes: {
          shape: "dot",
          scaling: { min: 10, max: 30 },
          borderWidth: 2,
          font: {
            size: 13,
            color: dark ? "#e6e8eb" : "#111",
            face: "system-ui",
          },
        },
        edges: {
          arrows: { to: { enabled: true, scaleFactor: 0.7 } },
          smooth: { type: "curvedCW", roundness: 0.25 },
          color: { color: "#93a4c4", highlight: "#4a90d9" },
          font: {
            size: 16,
            color: dark ? "#e6e8eb" : "#111",
            bold: true,
            strokeWidth: 6,
            strokeColor: dark ? "#15171c" : "#fff",
            align: "horizontal",
          },
          scaling: { min: 1, max: 8 },
        },
        physics: {
          barnesHut: { springLength: 170, gravitationalConstant: -7000 },
          stabilization: { iterations: 300 },
        },
        interaction: { hover: true },
      }
    );

    // Click a node → open that mailbox, exactly as the old graph did.
    net.on("click", function (p) {
      if (p.nodes.length) {
        location.href = "/mailbox/" + encodeURIComponent(p.nodes[0]);
      }
    });
  }
})();
