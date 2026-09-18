self.onInit = function () {
  var canvasElem = document.getElementById('orb-canvas');
  self.ctx.container = self.ctx.$container ? self.ctx.$container[0] : (self.ctx.container || (canvasElem && canvasElem.closest ? canvasElem.closest('.orbit-card') : null));
  if (!self.ctx.container) return;

  var root = self.ctx.container;
  var canvas = root.querySelector('#orb-canvas');
  if (!canvas) return;
  var ctx2d = canvas.getContext('2d');

  var kpiX = root.querySelector('#orb-kpi-x');
  var kpiY = root.querySelector('#orb-kpi-y');
  var kpiR = root.querySelector('#orb-kpi-r');
  var kpiPp = root.querySelector('#orb-kpi-pp');
  var chip = root.querySelector('#orb-chip');
  var orbTitle = root.querySelector('#orb-title');
  var orbSub = root.querySelector('#orb-sub');
  var scaleBadge = root.querySelector('#orb-scale');

  if (orbTitle && self.ctx.widgetConfig && self.ctx.widgetConfig.title) {
    orbTitle.textContent = self.ctx.widgetConfig.title;
  }
  if (orbSub && self.ctx.settings && self.ctx.settings.subtitle) {
    orbSub.textContent = self.ctx.settings.subtitle;
  }

  self.ctx.renderOrbit = function (xVal, yVal) {
    self.ctx.lastX = xVal;
    self.ctx.lastY = yVal;
    var rVal = Math.sqrt(xVal * xVal + yVal * yVal);

    var w = canvas.width;
    var h = canvas.height;
    if (w < 40 || h < 40) return;
    var cx = w / 2;
    var cy = h / 2;

    // Adaptive Full Scale (FS) so that small/normal vibrations fill 60-80% of the canvas
    var peak = Math.max(Math.abs(xVal), Math.abs(yVal), rVal);
    var fs = 0.5;
    if (peak > 4.0) {
      fs = 8.0;
    } else if (peak > 2.0) {
      fs = 4.0;
    } else if (peak > 0.8) {
      fs = 2.0;
    } else if (peak > 0.35) {
      fs = 1.0;
    } else {
      fs = 0.5;
    }

    var radius = Math.min(w, h) / 2 - 28;
    var scale = radius / fs;

    ctx2d.clearRect(0, 0, w, h);

    // Crosshairs
    ctx2d.strokeStyle = 'rgba(148, 163, 184, 0.35)';
    ctx2d.lineWidth = 1;
    ctx2d.setLineDash([2, 4]);
    ctx2d.beginPath();
    ctx2d.moveTo(cx, cy - radius - 8); ctx2d.lineTo(cx, cy + radius + 8);
    ctx2d.moveTo(cx - radius - 8, cy); ctx2d.lineTo(cx + radius + 8, cy);
    ctx2d.stroke();
    ctx2d.setLineDash([]);

    // Grid concentric range rings with high-contrast styling
    var rings = [0.25 * fs, 0.50 * fs, 0.75 * fs, 1.00 * fs];
    rings.forEach(function (r, idx) {
      var rPx = r * scale;
      ctx2d.beginPath();
      ctx2d.arc(cx, cy, rPx, 0, 2 * Math.PI);
      if (idx === 3) {
        ctx2d.strokeStyle = 'rgba(148, 163, 184, 0.50)';
        ctx2d.lineWidth = 1.5;
        ctx2d.stroke();
      } else {
        ctx2d.strokeStyle = 'rgba(148, 163, 184, 0.22)';
        ctx2d.lineWidth = 1;
        ctx2d.setLineDash([3, 3]);
        ctx2d.stroke();
        ctx2d.setLineDash([]);
      }

      // Range label along 45 degree diagonal
      ctx2d.fillStyle = 'rgba(203, 213, 225, 0.85)';
      ctx2d.font = '10px Roboto, sans-serif';
      ctx2d.fillText(r.toFixed(2) + ' mm/s', cx + rPx * 0.707 + 4, cy - rPx * 0.707 - 2);
    });

    // ISO 10816-3 Warning limit (4.5 mm/s) if in range
    if (4.5 <= fs) {
      ctx2d.strokeStyle = '#f59e0b';
      ctx2d.lineWidth = 1.5;
      ctx2d.setLineDash([5, 4]);
      ctx2d.beginPath();
      ctx2d.arc(cx, cy, 4.5 * scale, 0, 2 * Math.PI);
      ctx2d.stroke();
      ctx2d.setLineDash([]);
    }

    // ISO 10816-3 Alarm limit (6.0 mm/s) if in range
    if (6.0 <= fs) {
      ctx2d.strokeStyle = '#ef4444';
      ctx2d.lineWidth = 1.5;
      ctx2d.beginPath();
      ctx2d.arc(cx, cy, 6.0 * scale, 0, 2 * Math.PI);
      ctx2d.stroke();
    }

    // Lissajous Orbit Loop (shaft precession dynamic trajectory)
    ctx2d.save();
    ctx2d.shadowColor = 'rgba(0, 229, 255, 0.6)';
    ctx2d.shadowBlur = 8;
    ctx2d.strokeStyle = '#00e5ff';
    ctx2d.lineWidth = 2.5;
    ctx2d.beginPath();
    var steps = 120;
    var ax = Math.max(0.04, Math.abs(xVal));
    var ay = Math.max(0.04, Math.abs(yVal));
    for (var s = 0; s <= steps; s++) {
      var theta = (s / steps) * 2 * Math.PI;
      var sx = cx + (ax * Math.cos(theta)) * scale;
      var sy = cy - (ay * Math.sin(theta + 0.35)) * scale;
      if (s === 0) ctx2d.moveTo(sx, sy);
      else ctx2d.lineTo(sx, sy);
    }
    ctx2d.stroke();
    ctx2d.restore();

    // Shaft Center Dynamic Position & Glow
    var curPx = cx + xVal * scale;
    var curPy = cy - yVal * scale;

    // Center halo
    ctx2d.fillStyle = 'rgba(245, 158, 11, 0.25)';
    ctx2d.beginPath();
    ctx2d.arc(curPx, curPy, 11, 0, 2 * Math.PI);
    ctx2d.fill();

    // Center outer marker ring
    ctx2d.strokeStyle = '#fbbf24';
    ctx2d.lineWidth = 2;
    ctx2d.beginPath();
    ctx2d.arc(curPx, curPy, 6, 0, 2 * Math.PI);
    ctx2d.stroke();

    // Center solid dot
    ctx2d.fillStyle = '#ffffff';
    ctx2d.beginPath();
    ctx2d.arc(curPx, curPy, 2.5, 0, 2 * Math.PI);
    ctx2d.fill();

    // Update KPI metrics
    if (kpiX) kpiX.textContent = xVal.toFixed(2);
    if (kpiY) kpiY.textContent = yVal.toFixed(2);
    if (kpiR) kpiR.textContent = rVal.toFixed(2);
    if (kpiPp) kpiPp.textContent = (rVal * 2.0).toFixed(2);

    if (scaleBadge) {
      scaleBadge.textContent = 'FS: ±' + fs.toFixed(2) + ' mm/s';
    }

    if (chip) {
      if (rVal > 4.5) {
        chip.className = 'orbit-chip alarm';
        chip.textContent = 'ALARM';
      } else if (rVal > 2.8) {
        chip.className = 'orbit-chip warning';
        chip.textContent = 'WARNING';
      } else {
        chip.className = 'orbit-chip normal';
        chip.textContent = 'NORMAL';
      }
    }
  };

  self.onResize = function () {
    var wrap = root.querySelector('.orbit-canvas-wrap');
    if (wrap && canvas) {
      var rect = wrap.getBoundingClientRect();
      if (rect.width > 20 && rect.height > 20) {
        canvas.width = Math.floor(rect.width);
        canvas.height = Math.floor(rect.height);
        if (self.ctx.lastX !== undefined && self.ctx.lastY !== undefined) {
          self.ctx.renderOrbit(self.ctx.lastX, self.ctx.lastY);
        }
      }
    }
  };

  self.onResize();
  self.ctx.renderOrbit(0.20, 0.25);
};

self.onDataUpdated = function () {
  if (!self.ctx.data || !self.ctx.renderOrbit) return;
  var xVal = null;
  var yVal = null;
  self.ctx.data.forEach(function (ds) {
    if (ds && ds.data && ds.data.length > 0) {
      var last = ds.data[ds.data.length - 1][1];
      var keyName = ds.dataKey ? (ds.dataKey.name || '') : '';
      var keyLabel = ds.dataKey ? (ds.dataKey.label || '') : '';
      if (keyLabel === 'X' || keyName.indexOf('600') >= 0 || keyName.indexOf('604') >= 0) {
        xVal = Number(last);
      } else if (keyLabel === 'Y' || keyName.indexOf('601') >= 0 || keyName.indexOf('605') >= 0) {
        yVal = Number(last);
      }
    }
  });
  if (xVal !== null && yVal !== null && !isNaN(xVal) && !isNaN(yVal)) {
    self.ctx.renderOrbit(xVal, yVal);
  }
};

self.onDestroy = function () {
};
