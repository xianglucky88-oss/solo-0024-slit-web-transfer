const ns = 'http://www.w3.org/2000/svg';
function mark(svg, tag, attrs, text) {
  const node = document.createElementNS(ns, tag);
  Object.entries(attrs).forEach(([k, v]) => node.setAttribute(k, v));
  if (text !== undefined) node.textContent = text;
  svg.append(node);
  return node;
}
const line = (svg, x1, y1, x2, y2, cls = 'line') => mark(svg, 'line', { x1, y1, x2, y2, class: cls });
const rect = (svg, x, y, width, height, cls) => mark(svg, 'rect', { x, y, width, height, class: cls });
const dot = (svg, cx, cy, cls, r = 3) => mark(svg, 'circle', { cx, cy, r, class: cls });
const text = (svg, x, y, value) => mark(svg, 'text', { x, y }, value);
const path = (svg, points, cls) => mark(svg, 'polyline', { points: points.map((p) => p.join(',')).join(' '), class: cls });
function scale(lo, hi, a, b) { return (n) => a + (b - a) * (n - lo) / (hi - lo || 1); }
function range(values, fallback = [0, 1]) { return values.length ? [Math.min(...values), Math.max(...values)] : fallback; }
function grid(svg, a, b, unit) {
  for (let index = 0; index <= 5; index++) {
    const x = 58 + index * 122;
    line(svg, x, 30, x, 197);
    text(svg, x - 7, 217, Number((a + (b - a) * index / 5).toPrecision(4)));
  }
  text(svg, 686, 217, unit);
}

function render(svg, { source, outputs }) {
    grid(svg, 0, source.length, '毫米');
    const x = scale(0, source.length, 58, 668);
    const rows = outputs.layout.slice(0, 8);
    const h = Math.min(46, 150 / rows.length);
    for (const [i, row] of rows.entries()) {
      const y = 36 + i * h;
      text(svg, 8, y + 11, row.id.slice(0, 4));
      rect(svg, 58, y, 610, h - 5, 'band');
      for (const [a,b] of outputs.coverage[i].missing) rect(svg, x(a), y, x(b) - x(a), h - 5, 'empty-mark');
      for (const defect of outputs.transfer.filter((d) => d.child === row.id)) {
        rect(svg, x(defect.y0), y + 3, Math.max(2, x(defect.y1) - x(defect.y0)), Math.max(2, h - 11), defect.state === 'major' ? 'warning' : 'mark');
      }
    }
}

export function draw(svg, packet, config) {
  svg.replaceChildren();
  mark(svg, 'title', {}, config.plot);
  render(svg, packet);
}
