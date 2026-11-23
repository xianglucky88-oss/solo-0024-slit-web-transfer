const $ = (id) => document.getElementById(id);

const headings = {
  id: '布局', knife_count: '刀数', strip_count: '条数', longest_run: '最短板可保长段(mm)',
  total_loss: '走卷净长损失(mm)', total_usable: '可保净长合计(mm)',
  edge_waste: '两侧边料(mm)', trim_waste: '带内富余(mm)', width_waste: '幅宽边料合计(mm)',
  knife_positions: '下刀坐标(mm)', major_hits: '命中重大疵点', state: '状态', release: '口径',
  start: '起点(mm)', end: '终点(mm)', width: '带宽(mm)', excess: '富余(mm)',
  loss: '净长损失(mm)', longest: '可保长段(mm)', usable: '可保净长(mm)',
  major: '重大疵点', minor: '轻微疵点', blocked: '封锁走卷区间',
  width_signature: '等宽带宽序列', equivalent: '是否等价', reasons: '不等价理由',
  strip_evidence: '逐带证据', left: '布局甲', right: '布局乙', detail: '说明',
};

const layoutColumns = ['id', 'strip_count', 'longest_run', 'total_loss', 'edge_waste',
  'trim_waste', 'width_waste', 'major_hits', 'state', 'release'];
const stripColumns = ['id', 'start', 'end', 'width', 'excess', 'longest', 'loss', 'major', 'minor', 'blocked'];
const pairColumns = ['id', 'width_signature', 'equivalent', 'reasons', 'strip_evidence'];

function el(tag, text) {
  const node = document.createElement(tag);
  if (text !== undefined && typeof text !== 'object') node.textContent = text;
  return node;
}

function view(value) {
  if (value === null || value === undefined) return '—';
  if (Array.isArray(value)) {
    if (!value.length) return '—';
    if (value.every((part) => typeof part !== 'object')) return value.join('、');
    return value.map((part) => view(part)).join('；');
  }
  if (typeof value === 'object') {
    if ('detail' in value && Object.keys(value).length <= 2) return value.detail;
    return Object.entries(value).map(([key, item]) => `${headings[key] || key}: ${view(item)}`).join('；');
  }
  if (typeof value === 'boolean') return value ? '等价' : '不等价';
  if (typeof value === 'number') return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(value);
  return headings[value] || String(value);
}

function renderTable(tableId, rows, columns) {
  const table = $(tableId);
  const head = el('thead');
  const headRow = el('tr');
  for (const key of columns) headRow.append(el('th', headings[key] || key));
  head.append(headRow);
  const body = el('tbody');
  for (const row of rows) {
    const tr = el('tr');
    for (const key of columns) {
      const td = el('td');
      td.append(el('span', view(row[key])));
      if (key === 'state' || key === 'equivalent') td.firstChild.dataset.state = row[key];
      tr.append(td);
    }
    body.append(tr);
  }
  table.replaceChildren(head, body);
}

function renderDiagnosis(box, result) {
  box.replaceChildren();
  box.append(el('h3', result.state === 'infeasible' ? '找不到可行布局的约束说明' : '试算口径'));
  const list = el('ul');
  const notes = result.state === 'infeasible'
    ? [el('li', result.reason), ...result.diagnosis.map((note) => el('li', note.detail))]
    : [
      el('li', `母卷宽 ${result.constraints.width} mm × 长 ${result.constraints.length} mm`),
      el('li', `净幅 ${result.constraints.net_width} mm，最少 ${result.constraints.minimum_strips} 条；可用刀位格 ${result.constraints.slot_count} 个`),
      el('li', `实际转印预留 ${result.constraints.transfer_margin} mm，两端预留 ${result.constraints.reserve_margin} mm`),
      el('li', `共枚举 ${result.candidate_count} 套可行布局${result.truncated ? `，达到 ${result.truncated_at} 套上限后截断` : ''}`),
    ];
  for (const item of notes) list.append(item);
  const warn = el('p', result.notice);
  warn.className = 'trial-notice';
  box.append(list, warn);
}

export function initPlanning(request, guarded, note) {
  async function run() {
    let body;
    try {
      body = JSON.parse($('planning-source').value);
    } catch {
      throw new Error('试算请求不是有效的 JSON');
    }
    const result = await request('knife-plan', body);
    renderDiagnosis($('planning-diagnosis'), result);
    $('planning-layout-title').textContent =
      result.state === 'feasible'
        ? `可行布局（按${result.ranking === 'length' ? '保住长段' : '减少幅宽边料'}择优，前 ${result.layouts.length} 套）`
        : '可行布局';
    renderTable('planning-layout-table', result.layouts, layoutColumns);
    const stripRows = result.layouts.flatMap((layout) =>
      layout.strips.map((strip) => ({ ...strip, id: `${layout.id}/${strip.id}` })));
    renderTable('planning-strip-table', stripRows, stripColumns);
    $('planning-pair-title').textContent = `等宽布局为何不等价（${result.equal_width_pairs.length} 对）`;
    renderTable('planning-pair-table', result.equal_width_pairs, pairColumns);
    note(result.state === 'feasible'
      ? `刀位试算完成：${result.candidate_count} 套备选，仅用于试切排刀，未经复检不得放行`
      : '刀位试算：当前约束下无可行布局，见约束说明');
  }

  $('planning-run').addEventListener('click', () => guarded(run));
  $('planning-sample').addEventListener('click', () => guarded(async () => {
    const data = await request('planning-sample');
    $('planning-source').value = JSON.stringify(data, null, 2);
    await run();
  }));
  $('planning-infeasible').addEventListener('click', () => guarded(async () => {
    const data = await request('planning-infeasible');
    $('planning-source').value = JSON.stringify(data, null, 2);
    await run();
  }));
}
