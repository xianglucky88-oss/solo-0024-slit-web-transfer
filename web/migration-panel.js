const $ = (id) => document.getElementById(id);

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function value(name, model) {
  return model.values[name] || String(name);
}

const verdicts = { eligible: '可保', blind: '禁保·缺检', blocked: '禁保·重大', mixed: '禁保·双因' };
function verdict(name) {
  return verdicts[name] || (name ? String(name) : '—');
}

function span(pair) {
  return pair ? `${pair[0]}–${pair[1]}` : '—';
}

function cellText(row, key) {
  if (key === 'evidence' && row.evidence) {
    const describe = (side) => [side.major.length ? `重大 ${side.major.join('、')}` : '',
      side.blind ? '缺检' : ''].filter(Boolean).join('；') || '无';
    return `早版 ${describe(row.evidence.before)} / 晚版 ${describe(row.evidence.after)}`;
  }
  if (Array.isArray(row[key])) return span(row[key]);
  return String(row[key]);
}

function strips(list, model) {
  if (!list || !list.length) return '—';
  return list.map((item) => `${value(item.state, model)} ${span([item.x0, item.x1])}`).join('；');
}

function table(target, columns, rows, model) {
  const header = el('thead');
  const headRow = el('tr');
  for (const key of columns) headRow.append(el('th', model.columns[key] || key));
  header.append(headRow);
  const body = el('tbody');
  for (const row of rows) {
    const tr = el('tr');
    for (const key of columns) {
      const cell = el('td');
      if (row[key] === null || row[key] === undefined) {
        cell.append(el('span', '—'));
      } else if (key === 'state' || key === 'cause') {
        const node = el('span', value(row[key], model), 'state');
        node.dataset.state = row[key];
        cell.append(node);
      } else if (key === 'before' || key === 'after') {
        cell.append(el('span', verdict(row[key])));
      } else if (key === 'strips') {
        cell.append(el('span', strips(row[key], model)));
      } else {
        cell.append(el('span', cellText(row, key)));
      }
      tr.append(cell);
    }
    body.append(tr);
  }
  target.replaceChildren(header, body);
  target.hidden = rows.length === 0;
}

export function renderMigration(result, model) {
  $('migration-pane').hidden = false;
  const summary = $('migration-summary');
  summary.replaceChildren();
  if (!result.comparable) {
    summary.append(el('p', result.reason, 'migration-note'));
    $('migration-regions').hidden = true;
    $('migration-domains').hidden = true;
    $('migration-domain-empty').hidden = true;
    return;
  }
  const totals = result.totals;
  const line = (label, text) => {
    const item = el('p');
    item.append(el('strong', `${label}：`), el('span', text));
    summary.append(item);
  };
  line('损失总长', `${totals.loss_before} → ${totals.loss_after} 毫米（${totals.delta === 0 ? '恰好抵消' : `差 ${totals.delta > 0 ? '+' : ''}${totals.delta}`}）`);
  line('分项', `缺检 ${totals.gap_before} → ${totals.gap_after} 毫米；重大 ${totals.defect_before} → ${totals.defect_after} 毫米`);
  line('实物区段', `继续可保 ${totals.retained}；解除禁保 ${totals.released}；转为禁保 ${totals.restricted}；维持禁保 ${totals.held}；幅域差异 ${totals.domain} 毫米`);
  const moved = result.domains.length;
  line('幅域', moved ? `${moved} 条刀带的幅域或绕向发生变化，其差异不按原地修复核计` : '两版刀带幅域与绕向一致');

  const spec = model.migration || { columns: ['id', 'start', 'end', 'length', 'state', 'cause', 'before', 'after'], domainColumns: ['id', 'state', 'before', 'after', 'strips'] };
  table($('migration-regions'), spec.columns, result.regions, model);
  table($('migration-domains'), spec.domainColumns, result.domains, model);
  $('migration-domain-empty').hidden = result.domains.length !== 0;
  $('migration-pane').hidden = result.regions.length === 0 && result.domains.length === 0;
}

export function clearMigration() {
  $('migration-pane').hidden = true;
  $('migration-summary').replaceChildren();
  $('migration-regions').hidden = true;
  $('migration-domains').hidden = true;
  $('migration-domain-empty').hidden = true;
}
