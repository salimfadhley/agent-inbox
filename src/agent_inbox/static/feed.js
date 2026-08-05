/* The live feed, mounted twice: the Realtime tab and an agent's own page.
 *
 * Vanilla, vendored, same-origin. No framework and no build step, because the console
 * has neither and adding one for a list of rows would be the most expensive thing in
 * the repository.
 *
 * Two rules are requirements rather than style, and both are easy to lose in a
 * refactor:
 *
 *   1. **Connection state is never inferred.** The relay publishes `open`,
 *      `reconnecting` or `lost`; this file renders whichever it was told. There is no
 *      timer here that decides a feed has gone quiet for too long, because from the
 *      browser a hub with nothing to say and a connection that has died are the same
 *      silence. Guessing would make the head row confidently wrong, which is worse
 *      than blank.
 *
 *   2. **Direction is computed per viewer.** The same message is "sent" on one agent's
 *      page and "received" on another's, so the wire carries no direction field. A
 *      page tells the feed whose page it is; the hub-wide tab tells it nobody, and
 *      every row is rendered plain.
 */
(function () {
  "use strict";

  var MAX_ROWS = 200;

  function ago(then) {
    var s = Math.floor((Date.now() - then) / 1000);
    if (s < 5) return "just now";
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m";
    return new Date(then).toLocaleTimeString("en-GB", { hour12: false }).slice(0, 5);
  }

  function clock() {
    return new Date().toLocaleTimeString("en-GB", { hour12: false });
  }

  /* The words that go with the colour, so direction reads without the hue. */
  var WORD = { in: "from", out: "to" };

  function Feed(root) {
    this.root = root;
    /* Whose page this is, or "" for the hub-wide tab. Direction is derived from it. */
    this.subject = root.getAttribute("data-subject") || "";
    this.filter = "all";
    this.rows = root.querySelector(".feed-rows");
    this.stateText = root.querySelector(".feed-state");
    this.clockText = root.querySelector(".feed-clock");
    this.empty = root.querySelector(".feed-empty");
    this.bind();
    this.tick();
    var self = this;
    /* The only timer in this file, and it moves the clock — never the state. */
    setInterval(function () { self.tick(); }, 1000);
  }

  Feed.prototype.bind = function () {
    var self = this;
    var pills = this.root.querySelectorAll(".feed-pills button");
    Array.prototype.forEach.call(pills, function (pill) {
      pill.addEventListener("click", function () {
        self.filter = pill.getAttribute("data-f") || "all";
        Array.prototype.forEach.call(pills, function (other) {
          other.setAttribute("aria-pressed", other === pill ? "true" : "false");
        });
        self.apply();
      });
    });
  };

  /* Re-render the ageing times, and the head-row clock. Not the state. */
  Feed.prototype.tick = function () {
    if (this.clockText) this.clockText.textContent = clock();
    var whens = this.rows ? this.rows.querySelectorAll(".feed-when") : [];
    Array.prototype.forEach.call(whens, function (el) {
      var at = Number(el.getAttribute("data-at"));
      if (at) el.textContent = ago(at);
    });
  };

  Feed.prototype.setState = function (state) {
    this.root.setAttribute("data-state", state);
    if (this.stateText) {
      this.stateText.textContent =
        state === "open" ? "Line open"
        : state === "reconnecting" ? "Reconnecting"
        : "Line lost";
    }
  };

  Feed.prototype.directionOf = function (event) {
    if (!this.subject) return "";
    return event.from === this.subject ? "out" : "in";
  };

  /* Who *else* was involved. On an agent's page the agent is a given, so repeating
     their name in every row is noise. */
  Feed.prototype.otherParty = function (event, direction) {
    if (direction === "out") {
      var to = event.to || event.recipients;
      if (Array.isArray(to)) return to.join(", ");
      return to || "—";
    }
    return event.from || "—";
  };

  Feed.prototype.add = function (event) {
    if (!this.rows) return;
    var direction = this.directionOf(event);
    var at = Date.parse(event.published) || Date.now();

    var row = document.createElement("li");
    row.className = "feed-row fresh" + (direction ? " " + direction : "");
    row.setAttribute("data-dir", direction || "none");

    var rail = document.createElement("span");
    rail.className = "feed-rail";
    rail.setAttribute("aria-hidden", "true");

    var body = document.createElement("div");
    body.className = "feed-body";

    var meta = document.createElement("div");
    meta.className = "feed-meta";

    if (direction) {
      var dir = document.createElement("span");
      dir.className = "feed-dir";
      dir.textContent = WORD[direction];
      meta.appendChild(dir);
    }

    var who = document.createElement("span");
    who.className = "feed-who";
    /* Each name links to its own page — the most natural thing here to click. Built as
       elements rather than markup: a name is somebody else's text, and `textContent`
       is what keeps it text. Several recipients get several anchors, because one link
       around "alice, bob" would point at an agent called "alice, bob". */
    var parties = this.otherParty(event, direction).split(",");
    parties.forEach(function (raw, index) {
      var name = raw.trim();
      if (index) who.appendChild(document.createTextNode(", "));
      if (!name || name === "—") {
        who.appendChild(document.createTextNode(name || "—"));
        return;
      }
      var link = document.createElement("a");
      link.href = "/agent/" + encodeURIComponent(name);
      link.textContent = name;
      who.appendChild(link);
    });
    meta.appendChild(who);

    var when = document.createElement("span");
    when.className = "feed-when";
    when.setAttribute("data-at", String(at));
    when.setAttribute("title", new Date(at).toISOString());
    when.textContent = ago(at);
    meta.appendChild(when);

    var subject = document.createElement("p");
    subject.className = "feed-subject";
    if (event.subject) {
      subject.textContent = event.subject;
    } else {
      subject.className += " none";
      subject.textContent = "no subject";
    }

    body.appendChild(meta);
    body.appendChild(subject);
    row.appendChild(rail);
    row.appendChild(body);

    this.rows.insertBefore(row, this.rows.firstChild);
    while (this.rows.children.length > MAX_ROWS) {
      this.rows.removeChild(this.rows.lastChild);
    }
    if (this.empty) this.empty.hidden = true;
    this.apply();
  };

  /* Hidden rows are retained, never dropped: switching the filter back must show
     what arrived while the other direction was displayed. */
  Feed.prototype.apply = function () {
    if (!this.rows) return;
    var filter = this.filter;
    Array.prototype.forEach.call(this.rows.children, function (row) {
      var dir = row.getAttribute("data-dir");
      row.hidden = filter !== "all" && dir !== filter;
    });
  };

  Feed.prototype.listen = function () {
    var self = this;
    var source = new EventSource("/events");

    source.addEventListener("mail", function (message) {
      var event;
      try {
        event = JSON.parse(message.data);
      } catch (err) {
        return; /* a frame we cannot read is not a reason to break the page */
      }
      self.add(event);
    });

    source.addEventListener("line", function (message) {
      self.setState(String(message.data || "").trim());
    });

    /* Deliberately no `onerror` handler that sets a state. The browser's own view of
       the connection is about the console, not about the hub — and the relay is the
       only thing that knows which. Reporting "lost" here would contradict a head row
       the relay had just said was open. EventSource reconnects on its own. */
  };

  function start() {
    var roots = document.querySelectorAll(".feed[data-live]");
    Array.prototype.forEach.call(roots, function (root) {
      var feed = new Feed(root);
      feed.listen();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
