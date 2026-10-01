'use strict';

(() => {
  const state = {summary:null,history:[],weeks:[],weekIndex:0,view:'forecast',uploaded:null};
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const number = new Intl.NumberFormat('en-GB',{maximumFractionDigits:0});
  const decimal = new Intl.NumberFormat('en-GB',{maximumFractionDigits:1});
  const compact = new Intl.NumberFormat('en-GB',{notation:'compact',maximumFractionDigits:1});
  const escape = (value) => String(value ?? '').replace(/[&<>"']/g,(character) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const finite = (value) => typeof value === 'number' && Number.isFinite(value);
  const count = (value) => finite(value) ? number.format(value) : '—';
  const percent = (value) => finite(value) ? `${decimal.format(value > 1 ? value : value * 100)}%` : '—';
  const dateObject = (date) => new Date(`${String(date).slice(0,10)}T12:00:00Z`);
  const date = (value, options = {day:'numeric',month:'short',year:'numeric'}) => value ? dateObject(value).toLocaleDateString('en-GB',{...options,timeZone:'UTC'}) : '—';
  const weekday = (value) => date(value,{weekday:'long'});
  const pointsOf = (forecast) => Array.isArray(forecast?.points) ? forecast.points : [];
  const sum = (values) => values.reduce((total,value) => total + (finite(value) ? value : 0),0);
  const metric = (label,value,unit,detail='',subdued=false) => `<article class="metric${subdued ? ' metric-subdued' : ''}"><p class="metric-label">${escape(label)}</p><div class="metric-value">${escape(value)}${unit ? `<span class="metric-unit">${escape(unit)}</span>` : ''}</div><p class="metric-detail">${escape(detail)}</p></article>`;
  const selectedModel = () => state.summary.models.find((model) => model.id === state.summary.overview.selected_model || model.name === state.summary.overview.selected_model) || state.summary.models.find((model) => model.selected) || {name:state.summary.overview.selected_model || 'Selected model'};

  async function request(url,options) {
    const response = await fetch(url,options);
    let result;
    try { result = await response.json(); } catch { throw new Error('The service did not return a readable response. Please try again.'); }
    if (!response.ok) throw new Error(typeof result.error === 'string' ? result.error : result.message || `The service returned error ${response.status}.`);
    return result;
  }

  function showView(view,updateHash=true) {
    if (!['forecast','replay','evidence','method'].includes(view)) view = 'forecast';
    state.view = view;
    $$('.view-tab').forEach((tab) => {
      const active = tab.dataset.view === view;
      tab.classList.toggle('active',active);
      if (active) tab.setAttribute('aria-current','page'); else tab.removeAttribute('aria-current');
    });
    $$('.view-panel').forEach((panel) => { panel.hidden = panel.id !== `view-${view}`; });
    if (updateHash) history.replaceState(null,'',`#${view}`);
    if (state.summary) {
      if (view === 'forecast') renderForecast();
      if (view === 'replay') renderReplay();
    }
  }

  function chartScale(values) {
    const max = Math.max(...values.filter(finite),1);
    const rough = max / 4;
    const magnitude = 10 ** Math.floor(Math.log10(rough));
    const factor = rough / magnitude;
    const step = (factor <= 1 ? 1 : factor <= 2 ? 2 : factor <= 2.5 ? 2.5 : factor <= 5 ? 5 : 10) * magnitude;
    return {max:Math.ceil(max / step) * step,step};
  }

  function forecastChart(container,points,reveal=false) {
    if (!points.length) { container.innerHTML = '<p class="quiet">No forecast is available.</p>'; return; }
    const width = Math.max(340,Math.round(container.clientWidth || 730));
    const small = width < 470;
    const height = small ? 278 : 282;
    const left = small ? 38 : 49, right = 15, top = 16, bottom = 205;
    const {max,step} = chartScale(points.flatMap((point) => [point.upper,point.prediction,reveal ? point.actual : null]));
    const plotWidth = width-left-right;
    const x = (index) => left + plotWidth * ((index + .5) / points.length);
    const y = (value) => bottom - Math.max(0,value) / max * (bottom-top);
    const bandWidth = Math.min(small ? 25 : 37,plotWidth/points.length*.42);
    const grid = [];
    for (let value=0;value<=max+.001;value+=step) grid.push(`<line x1="${left}" x2="${width-right}" y1="${y(value)}" y2="${y(value)}" class="grid-line"/><text x="${left-8}" y="${y(value)+3}" text-anchor="end" class="chart-axis">${escape(compact.format(value))}</text>`);
    const bands = points.map((point,index) => `<rect x="${x(index)-bandWidth/2}" y="${y(point.upper)}" width="${bandWidth}" height="${Math.max(1,y(point.lower)-y(point.upper))}" rx="2" class="forecast-range"><title>${escape(`${date(point.date)}: forecast ${count(point.prediction)} hires; range ${count(point.lower)}–${count(point.upper)} hires`)}</title></rect>`).join('');
    const line = points.map((point,index) => `${x(index)},${y(point.prediction)}`).join(' ');
    const actualPoints = points.filter((point) => finite(point.actual));
    const actualLine = reveal && actualPoints.length ? `<polyline points="${points.filter((point) => finite(point.actual)).map((point) => `${x(points.indexOf(point))},${y(point.actual)}`).join(' ')}" class="actual-line"/>` : '';
    const dots = points.map((point,index) => `<circle cx="${x(index)}" cy="${y(point.prediction)}" r="4.5" class="forecast-point"/>${reveal && finite(point.actual) ? `<circle cx="${x(index)}" cy="${y(point.actual)}" r="4" class="actual-point"><title>${escape(`Observed: ${count(point.actual)} hires`)}</title></circle>` : ''}`).join('');
    const labels = points.map((point,index) => `<text x="${x(index)}" y="226" text-anchor="middle" class="chart-label">${escape(date(point.date,{weekday:'short'}))}</text><text x="${x(index)}" y="241" text-anchor="middle" class="chart-sub-label">${escape(date(point.date,{day:'2-digit',month:'short'}))}</text><text x="${x(index)}" y="264" text-anchor="middle" class="chart-value">${escape(small ? compact.format(point.prediction) : count(point.prediction))}</text>`).join('');
    const accessible = points.map((point) => `${date(point.date)}: forecast ${count(point.prediction)}, range ${count(point.lower)} to ${count(point.upper)} hires${reveal && finite(point.actual) ? `, observed ${count(point.actual)}` : ''}`).join('; ');
    container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(accessible)}">${grid.join('')}${bands}<polyline points="${line}" class="forecast-line"/>${actualLine}${dots}${labels}</svg>`;
  }

  function precedingHistory(forecast) {
    if (Array.isArray(forecast?.history90)) return forecast.history90;
    if (Array.isArray(forecast?.history)) return forecast.history.slice(-90);
    return state.history.filter((point) => point.date <= forecast.origin).slice(-90);
  }

  function historyChart(container,history) {
    const observations = history.filter((point) => finite(point.hires));
    if (!observations.length) { container.innerHTML = '<p class="quiet">No observed history is available for this origin.</p>'; return; }
    const width = Math.max(340,Math.round(container.clientWidth || 980));
    const height = 170, left = width < 470 ? 38 : 49, right = 14, top = 12, bottom = 137;
    const {max,step} = chartScale(observations.map((point) => point.hires));
    const x = (index) => left + index / Math.max(1,observations.length-1) * (width-left-right);
    const y = (value) => bottom - value / max * (bottom-top);
    const grid = [];
    for (let value=0;value<=max+.001;value+=step) grid.push(`<line x1="${left}" x2="${width-right}" y1="${y(value)}" y2="${y(value)}" class="grid-line"/><text x="${left-8}" y="${y(value)+3}" text-anchor="end" class="chart-axis">${escape(compact.format(value))}</text>`);
    const line = observations.map((point,index) => `${x(index)},${y(point.hires)}`).join(' ');
    const dates = [0,Math.floor((observations.length-1)/2),observations.length-1].map((index) => `<text x="${x(index)}" y="160" text-anchor="${index===0?'start':index===observations.length-1?'end':'middle'}" class="chart-axis">${escape(date(observations[index].date,{day:'numeric',month:'short'}))}</text>`).join('');
    container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Observed daily hires from ${escape(date(observations[0].date))} to ${escape(date(observations.at(-1).date))}">${grid.join('')}<polygon points="${left},${bottom} ${line} ${width-right},${bottom}" class="history-area"/><polyline points="${line}" class="history-line"/><circle cx="${x(observations.length-1)}" cy="${y(observations.at(-1).hires)}" r="3" class="history-marker"/>${dates}</svg>`;
  }

  function renderForecast() {
    const forecast = state.uploaded || state.summary.next_forecast;
    const points = pointsOf(forecast);
    if (!points.length) return;
    const overview = state.summary.overview;
    const total = sum(points.map((point) => point.prediction));
    const peak = points.reduce((current,point) => point.prediction > current.prediction ? point : current);
    $('#forecast-dates').textContent = `${date(points[0].date)} – ${date(points.at(-1).date)}${state.uploaded ? ' · your supplied history' : ' · saved source snapshot'}`;
    $('#data-cutoff').textContent = `History ends ${date(forecast.origin)}`;
    $('#model-name').textContent = selectedModel().name;
    $('#forecast-metrics').innerHTML = metric('Expected week',count(total),'hires','Sum of seven daily point forecasts') + metric('Busiest forecast day',weekday(peak.date),'',`${count(peak.prediction)} hires · ${date(peak.date,{day:'numeric',month:'short'})}`,true) + metric('Test average error',count(overview.mae),'hires / day','Measured on held-out forecast weeks');
    $('#forecast-insight-title').textContent = `${weekday(peak.date)} leads the outlook.`;
    const lowest = points.reduce((current,point) => point.prediction < current.prediction ? point : current);
    $('#forecast-insight').textContent = `The model expects ${count(peak.prediction)} hires on ${weekday(peak.date)}, compared with ${count(lowest.prediction)} on ${weekday(lowest.date)}. These estimates describe demand across London, with daily ranges shown beside each forecast.`;
    const warnings = Array.isArray(forecast.warnings) ? forecast.warnings : [];
    $('#forecast-warning').hidden = warnings.length === 0;
    const sundayOrigin = dateObject(forecast.origin).getUTCDay()===0;
    const warningLead = !sundayOrigin ? `Range coverage was measured for Sunday origins. This ${weekday(forecast.origin)}-origin outlook follows a different schedule; its range coverage is unassessed.` : 'Your supplied history uses the original model and historical calibration. Its prediction ranges may be less reliable for a different period or distribution.';
    $('#forecast-warning').innerHTML = warnings.length ? `<strong>Read the ranges with care.</strong> ${escape(warningLead)}<details><summary>Forecast notes (${warnings.length})</summary><ul>${warnings.map((warning) => `<li>${escape(warning)}</li>`).join('')}</ul></details>` : '';
    $('#forecast-footnote').textContent = `${percent(overview.nominal_coverage)} nominal target for daily ranges, calibrated on Sunday origins. The weekly total is a point estimate; daily bounds are not a calibrated weekly interval.`;
    const history = precedingHistory(forecast);
    forecastChart($('#forecast-chart'),points);
    historyChart($('#latest-history-chart'),history);
    $('#forecast-export').href = '/api/download';
    $('#forecast-export').onclick = state.uploaded ? (event) => { event.preventDefault(); downloadUploaded(forecast); } : null;
  }

  function renderReplay() {
    if (!state.weeks.length) return;
    state.weekIndex = Math.min(Math.max(0,state.weekIndex),state.weeks.length-1);
    const forecast = state.weeks[state.weekIndex];
    const points = pointsOf(forecast);
    const reveal = $('#show-actual').checked;
    const total = sum(points.map((point) => point.prediction));
    const truthAvailable = points.every((point) => finite(point.actual));
    const actualTotal = truthAvailable ? sum(points.map((point) => point.actual)) : null;
    const mae = truthAvailable ? sum(points.map((point) => Math.abs(point.prediction-point.actual))) / points.length : null;
    $('#week-select').value = String(state.weekIndex);
    $('#week-range').value = String(state.weekIndex);
    $('#week-position').textContent = `${state.weekIndex+1} / ${state.weeks.length}`;
    $('#previous-week').disabled = state.weekIndex===0;
    $('#next-week').disabled = state.weekIndex===state.weeks.length-1;
    $('#replay-origin').textContent = `Forecast frozen at ${date(forecast.origin)}`;
    $('#replay-dates').textContent = `${date(points[0].date)} – ${date(points.at(-1).date)}`;
    $('#replay-metrics').innerHTML = metric('Forecast week',count(total),'hires','Sum of seven daily point forecasts') + metric('Observed week',reveal ? count(actualTotal) : 'Hidden','hires',reveal ? 'Observed totals in the test period' : 'Reveal observed demand to compare',!reveal) + metric('This week’s error',reveal ? count(mae) : 'Hidden','hires / day',reveal ? 'Mean absolute error over seven days' : 'Measured after the week has passed',!reveal);
    $('#actual-legend').hidden = !reveal;
    $('#show-actual').disabled = !truthAvailable;
    forecastChart($('#replay-chart'),points,reveal);
    historyChart($('#replay-history-chart'),precedingHistory(forecast));
    $('#replay-day-table').innerHTML = `<table class="day-table"><caption class="visually-hidden">Daily forecasts and ${reveal ? 'observed demand' : 'prediction ranges'}</caption><thead><tr><th scope="col">Day</th><th scope="col">Forecast</th><th scope="col">Daily range</th>${reveal ? '<th scope="col">Observed</th><th scope="col">Absolute error</th>' : ''}</tr></thead><tbody>${points.map((point) => `<tr><td>${escape(date(point.date,{weekday:'short',day:'numeric',month:'short'}))}</td><td>${count(point.prediction)}</td><td>${count(point.lower)}–${count(point.upper)}</td>${reveal ? `<td class="observed-cell">${count(point.actual)}</td><td>${finite(point.actual) ? count(Math.abs(point.actual-point.prediction)) : '—'}</td>` : ''}</tr>`).join('')}</tbody></table>`;
    $('#replay-export').href = `/api/download?origin=${encodeURIComponent(forecast.origin)}`;
  }

  function barChart(container,rows,label) {
    const maximum = Math.max(...rows.map((row) => row.mae).filter(finite),1);
    container.innerHTML = rows.map((row) => `<div class="bar-row"><span class="bar-label">${escape(label(row))}</span><div class="bar-track" aria-hidden="true"><div class="bar-fill" style="width:${Math.max(0,Math.min(100,row.mae/maximum*100))}%"></div></div><span class="bar-number">${count(row.mae)}</span></div>`).join('') + '<p class="bar-unit">MAE · hires / day</p>';
  }

  function metadataDate(name) {
    const metadata = state.summary.metadata;
    if (metadata[name]) return metadata[name];
    const [split,boundary] = name.split('_');
    return metadata.splits?.[split]?.[boundary] || metadata.split?.[split]?.[boundary] || null;
  }

  function renderEvidence() {
    const {overview,models,diagnostics,metadata} = state.summary;
    const selected = selectedModel();
    const testStart = metadataDate('test_start');
    const testEnd = metadataDate('test_end');
    $('#test-period').textContent = `${count(overview.test_weeks)} held-out weeks · ${count(overview.test_days)} daily forecasts${testStart && testEnd ? ` · ${date(testStart)} – ${date(testEnd)}` : ''}`;
    $('#evidence-metrics').innerHTML = metric('Average absolute error',count(overview.mae),'hires / day','Selected model · held-out test') + metric('Versus seasonal baseline',`${decimal.format(overview.baseline_improvement_percent)}%`,'less MAE','Same test dates, same forecast origins') + metric('Daily range coverage',percent(overview.coverage),'of observations',`${percent(overview.nominal_coverage)} nominal target`);
    $('#leaderboard-body').innerHTML = [...models].sort((a,b) => a.mae-b.mae).map((model) => `<tr class="${model.id===selected.id ? 'selected' : ''}"><td>${escape(model.name)}${model.id===selected.id ? '<span class="model-tag">Selected on validation</span>' : ''}</td><td>${count(model.mae)}</td><td>${count(model.rmse)}</td><td>${finite(model.wape) ? `${decimal.format(model.wape)}%` : '—'}</td></tr>`).join('');
    barChart($('#horizon-chart'),diagnostics.by_horizon || [],(row) => `Day ${row.horizon}`);
    barChart($('#weekday-chart'),diagnostics.by_weekday || [],(row) => String(row.weekday ?? row.day ?? '').slice(0,3));
    $('#coverage-title').textContent = `${percent(overview.coverage)} of observed days fell inside.`;
    $('#coverage-copy').textContent = `The nominal target is ${percent(overview.nominal_coverage)}. These measurements use Sunday-origin test weeks. Coverage is unassessed for other origin weekdays, including the latest saved outlook. Changing demand can also make later coverage differ.`;
    const coverage = overview.coverage>1 ? overview.coverage : overview.coverage*100;
    $('#coverage-fill').style.width = `${Math.max(0,Math.min(100,coverage))}%`;
    $('#coverage-width').textContent = `Mean daily range width: ${count(overview.mean_interval_width)} hires`;
    const names = [['train','Training'],['validation','Validation'],['calibration','Calibration'],['test','Test']];
    $('#split-timeline').innerHTML = names.map(([key,label]) => `<div class="split-block"><span class="split-label">${label}</span><span class="split-dates">${date(metadataDate(`${key}_start`))}<br>to ${date(key==='train' && metadata.initial_train_end ? metadata.initial_train_end : metadataDate(`${key}_end`))}</span></div>`).join('');
    const sourceUrl = metadata.source_url || metadata.dataset_url;
    if (sourceUrl && /^https:\/\//.test(sourceUrl)) { $('#footer-source-link').href = sourceUrl; $('#method-source-link').href = sourceUrl; }
    if (metadata.licence_url && /^https:\/\//.test(metadata.licence_url)) $('#data-licence-link').href = metadata.licence_url;
    const start = metadata.data_start || metadata.start_date || metadataDate('train_start');
    const end = metadata.source_cutoff || metadata.data_end || metadata.end_date || state.summary.next_forecast.origin;
    $('#source-period').textContent = `${date(start)} – ${date(end)}`;
  }

  function downloadUploaded(forecast) {
    const content = ['origin,date,horizon,prediction,lower,upper,actual,seasonal_naive,weekday_mean,ridge',...pointsOf(forecast).map((point) => `${forecast.origin},${point.date},${point.horizon},${point.prediction},${point.lower},${point.upper},,${point.seasonal_naive ?? ''},${point.weekday_mean ?? ''},${point.ridge ?? ''}`)].join('\n');
    const url = URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'}));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `londonpulse-forecast-${forecast.origin}.csv`;
    document.body.append(anchor);anchor.click();anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url),1000);
  }

  function showUploadError(message) { $('#upload-error').textContent = message; $('#upload-error').hidden = false; }

  async function uploadHistory() {
    const text = $('#history-text').value.trim();
    $('#upload-error').hidden = true;
    if (!text) { showUploadError('Choose a CSV file or paste a daily history first.'); return; }
    if (new TextEncoder().encode(text).length > 500000) { showUploadError('This history is larger than 500 KB. Please use a shorter daily history.'); return; }
    $('#run-upload').disabled = true;
    $('#run-upload').textContent = 'Analysing history…';
    try {
      const result = await request('/api/predict',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
      const forecast = result.forecast || result;
      if (!pointsOf(forecast).length) throw new Error('The service returned no daily forecast. Please check the history and try again.');
      state.uploaded = forecast;
      $('#upload-dialog').close();
      showView('forecast');
      $('#forecast-title').focus({preventScroll:true});
      $('#forecast-title').scrollIntoView({behavior:'smooth',block:'start'});
    } catch (error) { showUploadError(error.message); }
    finally { $('#run-upload').disabled = false; $('#run-upload').innerHTML = 'Generate outlook <span aria-hidden="true">→</span>'; }
  }

  $$('.view-tab').forEach((button) => button.addEventListener('click',() => showView(button.dataset.view)));
  $$('[data-goto]').forEach((link) => link.addEventListener('click',(event) => { event.preventDefault();showView(link.dataset.goto); }));
  $('.brand').addEventListener('click',(event) => { event.preventDefault();state.uploaded=null;showView('forecast'); });
  $('#week-select').addEventListener('change',(event) => { state.weekIndex=Number(event.target.value);renderReplay(); });
  $('#week-range').addEventListener('input',(event) => { state.weekIndex=Number(event.target.value);renderReplay(); });
  $('#previous-week').addEventListener('click',() => { state.weekIndex--;renderReplay(); });
  $('#next-week').addEventListener('click',() => { state.weekIndex++;renderReplay(); });
  $('#show-actual').addEventListener('change',renderReplay);
  $('#open-upload').addEventListener('click',() => { $('#upload-error').hidden=true;$('#upload-dialog').showModal(); });
  $('#close-upload').addEventListener('click',() => $('#upload-dialog').close());
  $('#upload-dialog').addEventListener('click',(event) => { if (event.target===$('#upload-dialog')) { const bounds=event.target.getBoundingClientRect();if (event.clientX<bounds.left || event.clientX>bounds.right || event.clientY<bounds.top || event.clientY>bounds.bottom) event.target.close(); } });
  $('#run-upload').addEventListener('click',uploadHistory);
  $('#history-file').addEventListener('change',async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    $('#upload-error').hidden = true;
    if (file.size > 500000) { showUploadError('This file is larger than 500 KB. Please use a shorter daily history.');event.target.value='';return; }
    try { $('#history-text').value=await file.text();$('#upload-file-name').textContent=file.name; }
    catch { showUploadError('The file could not be read. Please try a plain CSV file.'); }
  });
  let resizeTimer;
  window.addEventListener('resize',() => { clearTimeout(resizeTimer);resizeTimer=setTimeout(() => { if (state.summary) { if (state.view==='forecast') renderForecast();if (state.view==='replay') renderReplay(); } },120); });
  window.addEventListener('hashchange',() => showView(location.hash.slice(1),false));
  $('#forecast-title').setAttribute('tabindex','-1');

  async function initialise() {
    try {
      const [summary,historyResult,weeksResult] = await Promise.all([request('/api/summary'),request('/api/history'),request('/api/weeks')]);
      state.summary = summary;
      state.history = historyResult.history || [];
      state.weeks = [...(weeksResult.weeks || [])].sort((a,b) => a.origin.localeCompare(b.origin));
      if (!summary.overview || !summary.next_forecast || !summary.models || !state.weeks.length) throw new Error('The saved experiment is incomplete. Please check that the model and data artefacts have been generated.');
      $('#week-select').innerHTML = state.weeks.map((week,index) => `<option value="${index}">${escape(date(week.origin))}</option>`).join('');
      $('#week-range').max = String(state.weeks.length-1);
      $('#load-status').hidden = true;
      renderEvidence();
      showView(location.hash.slice(1) || 'forecast',false);
    } catch (error) { $('#load-status').hidden=true;$('#app-error').textContent=error.message;$('#app-error').hidden=false; }
  }
  initialise();
})();
