// ===== App State =====
const App = (() => {
  let currentScreen = 'morning';
  let projects = [];

  // ===== Routing =====
  function showScreen(name) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-btn[data-screen]').forEach(b => b.classList.remove('active'));
    document.getElementById(`screen-${name}`).classList.add('active');
    document.querySelector(`.nav-btn[data-screen="${name}"]`)?.classList.add('active');
    currentScreen = name;
    loadScreen(name);
  }

  async function loadScreen(name) {
    switch (name) {
      case 'morning':  await loadMorning();  break;
      case 'evening':  await loadEvening();  break;
      case 'ideas':    await loadIdeas();    break;
      case 'horizon':  await loadHorizon();  break;
      case 'projects': await loadProjects(); break;
    }
  }

  // ===== Morning Screen =====
  async function loadMorning() {
    const el = document.getElementById('screen-morning');

    try {
      const data = await API.getMorning();

      // Update date
      el.querySelector('.screen-date').textContent = formatDate(data.date);

      // Quote
      const qCard = el.querySelector('.quote-card');
      qCard.querySelector('.quote-text').textContent = `«${data.quote.text}»`;
      qCard.querySelector('.quote-author').textContent = data.quote.author;

      // Warn banner
      const warn = el.querySelector('#warnNoRest');
      warn.style.display = data.warn_no_rest ? 'flex' : 'none';

      // Tasks
      renderTasks(el.querySelector('.task-list'), data.tasks, () => loadMorning());

      // Evening suggestion for late hours
      const hour = new Date().getHours();
      const suggestion = el.querySelector('.evening-suggestion');
      if (suggestion) suggestion.style.display = hour >= 18 ? 'flex' : 'none';
    } catch (err) {
      showError(el, 'morning-content', err.message);
    }
  }

  // ===== Evening Screen =====
  async function loadEvening() {
    const el = document.getElementById('screen-evening');

    try {
      const data = await API.getEvening();

      el.querySelector('.screen-date').textContent = formatDate(data.date);

      // Summary
      el.querySelector('.summary-text').textContent = data.summary;

      // Completed
      const doneList = el.querySelector('.done-list');
      if (data.completed.length === 0) {
        doneList.innerHTML = '<div class="empty-state"><div class="empty-icon">○</div>Нет выполненных задач</div>';
      } else {
        doneList.innerHTML = '';
        data.completed.forEach(t => doneList.appendChild(buildTaskItem(t, null)));
      }

      // Moved
      const movedSection = el.querySelector('.moved-section');
      if (data.moved.length === 0) {
        movedSection.style.display = 'none';
      } else {
        movedSection.style.display = 'block';
        const movedList = el.querySelector('.moved-list');
        movedList.innerHTML = '';
        data.moved.forEach(t => {
          const item = buildTaskItem(t, null);
          const badge = document.createElement('span');
          badge.className = 'moved-badge';
          badge.textContent = 'перенесено';
          item.querySelector('.task-body').appendChild(badge);
          movedList.appendChild(item);
        });
      }

      // Tomorrow
      const tmrList = el.querySelector('.tomorrow-list');
      if (data.tomorrow.length === 0) {
        tmrList.innerHTML = '<div class="empty-state"><div class="empty-icon">○</div>Завтра пока пусто</div>';
      } else {
        tmrList.innerHTML = '';
        data.tomorrow.forEach(t => tmrList.appendChild(buildTaskItem(t, null)));
      }
    } catch (err) {
      showError(el, 'evening-content', err.message);
    }
  }

  // ===== Ideas Screen =====
  async function loadIdeas() {
    const el = document.getElementById('screen-ideas');
    const list = el.querySelector('.ideas-list');
    list.innerHTML = '<div class="loading-spinner">Загрузка</div>';

    try {
      const ideas = await API.getIdeas();
      list.innerHTML = '';
      if (ideas.length === 0) {
        list.innerHTML = '<div class="empty-state"><div class="empty-icon">💡</div>Идеи здесь не теряются</div>';
        return;
      }
      ideas.forEach(idea => {
        const div = document.createElement('div');
        div.className = 'idea-item';
        div.innerHTML = `
          <div class="idea-content">
            <div>${escHtml(idea.content)}</div>
            ${idea.remind_at ? `<div class="idea-remind">Напомнить: ${formatDate(idea.remind_at)}</div>` : ''}
          </div>
          <button class="idea-archive-btn" title="Архивировать">✓</button>
        `;
        div.querySelector('.idea-archive-btn').addEventListener('click', async () => {
          try {
            await API.archiveIdea(idea.id);
            div.style.opacity = '0';
            div.style.transition = 'opacity .3s';
            setTimeout(() => { div.remove(); }, 300);
            showToast('Идея архивирована');
          } catch (e) { showToast(`Ошибка: ${e.message}`); }
        });
        list.appendChild(div);
      });
    } catch (err) {
      list.innerHTML = `<div class="empty-state" style="color:#EF4444">${err.message}</div>`;
    }
  }

  // ===== Horizon Screen =====
  async function loadHorizon() {
    const el = document.getElementById('screen-horizon');
    const list = el.querySelector('.horizon-list');
    list.innerHTML = '<div class="loading-spinner">Загрузка</div>';

    try {
      const items = await API.getHorizon();
      list.innerHTML = '';
      if (items.length === 0) {
        list.innerHTML = '<div class="empty-state"><div class="empty-icon">✦</div>Большие намерения живут здесь</div>';
        return;
      }
      items.forEach(item => list.appendChild(buildHorizonItem(item)));
    } catch (err) {
      list.innerHTML = `<div class="empty-state" style="color:#EF4444">${err.message}</div>`;
    }
  }

  function buildHorizonItem(item) {
    const div = document.createElement('div');
    div.className = 'horizon-item';
    div.innerHTML = `
      <div class="horizon-star">✦</div>
      <div class="horizon-body">
        <div class="horizon-content">${escHtml(item.content)}</div>
        ${item.timeframe ? `<span class="horizon-timeframe">${escHtml(item.timeframe)}</span>` : ''}
      </div>
      <button class="horizon-delete-btn" title="Удалить">×</button>
    `;
    div.querySelector('.horizon-delete-btn').addEventListener('click', async () => {
      try {
        await API.deleteHorizon(item.id);
        div.style.opacity = '0';
        div.style.transition = 'opacity .3s';
        setTimeout(() => div.remove(), 300);
        showToast('Намерение удалено');
      } catch (e) { showToast(`Ошибка: ${e.message}`); }
    });
    return div;
  }

  // ===== Projects Screen =====
  async function loadProjects() {
    const el = document.getElementById('screen-projects');
    const grid = el.querySelector('.projects-grid');
    grid.innerHTML = '<div class="loading-spinner" style="grid-column:1/-1">Загрузка</div>';

    try {
      projects = await API.getProjects();
      grid.innerHTML = '';
      projects.forEach(p => {
        const card = document.createElement('div');
        card.className = 'project-card';
        card.style.setProperty('--project-color', p.color);
        card.innerHTML = `
          <div class="project-name">${escHtml(p.name)}</div>
          <div class="project-desc">${escHtml(p.description || '')}</div>
        `;
        grid.appendChild(card);
      });
    } catch (err) {
      grid.innerHTML = `<div class="empty-state" style="color:#EF4444">${err.message}</div>`;
    }
  }

  // ===== Task Rendering =====
  function renderTasks(container, tasks, onRefresh) {
    container.innerHTML = '';
    if (tasks.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">○</div>Задач нет. Чистый день.</div>';
      return;
    }
    tasks.forEach(t => container.appendChild(buildTaskItem(t, onRefresh)));
  }

  function buildTaskItem(task, onRefresh) {
    const div = document.createElement('div');
    div.className = `task-item${task.completed ? ' done' : ''}`;
    div.dataset.id = task.id;

    const timeStr = task.time_start ? `<span class="task-time">${task.time_start.slice(0,5)}</span>` : '';
    const projStr = task.project_name
      ? `<span class="task-project" style="border-left:2px solid ${task.project_color || '#6B7280'};padding-left:5px">${escHtml(task.project_name)}</span>`
      : '';
    const type = task.type || 'work';

    div.innerHTML = `
      <input type="checkbox" class="task-check" ${task.completed ? 'checked' : ''}>
      <div class="task-dot ${type}"></div>
      <div class="task-body">
        <div class="task-title">${escHtml(task.title)}</div>
        <div class="task-meta">
          <span class="task-type-badge ${type}">${typeLabel(type)}</span>
          ${timeStr}${projStr}
        </div>
      </div>
      ${onRefresh ? '<button class="task-delete-btn" title="Удалить">×</button>' : ''}
    `;

    const checkbox = div.querySelector('.task-check');
    if (checkbox && onRefresh) {
      checkbox.addEventListener('change', async () => {
        try {
          await API.toggleTask(task.id);
          div.classList.toggle('done');
        } catch (e) {
          checkbox.checked = !checkbox.checked;
          showToast(`Ошибка: ${e.message}`);
        }
      });
    }

    const delBtn = div.querySelector('.task-delete-btn');
    if (delBtn && onRefresh) {
      delBtn.addEventListener('click', async () => {
        try {
          await API.deleteTask(task.id);
          div.style.opacity = '0';
          div.style.transition = 'opacity .3s';
          setTimeout(() => { div.remove(); }, 300);
          showToast('Задача удалена');
        } catch (e) { showToast(`Ошибка: ${e.message}`); }
      });
    }

    return div;
  }

  // ===== Modal =====
  let modalMode = 'task'; // 'task' | 'idea' | 'horizon'
  let selectedType = 'work';

  function openModal(mode) {
    modalMode = mode;
    selectedType = 'work';

    const overlay = document.getElementById('modalOverlay');
    const title   = document.getElementById('modalTitle');
    const forms   = overlay.querySelectorAll('.modal-form');
    forms.forEach(f => f.style.display = 'none');

    if (mode === 'task') {
      title.textContent = 'Новая задача';
      document.getElementById('taskForm').style.display = 'block';
      document.getElementById('taskDate').value = todayISO();
      document.getElementById('taskTitle').value = '';
      document.getElementById('taskTime').value = '';
      document.getElementById('taskProject').value = '';
      selectType('work');
      populateProjectSelect();
    } else if (mode === 'idea') {
      title.textContent = 'Новая идея';
      document.getElementById('ideaForm').style.display = 'block';
      document.getElementById('ideaContent').value = '';
      document.getElementById('ideaRemind').value = '';
    } else if (mode === 'horizon') {
      title.textContent = 'Новое намерение';
      document.getElementById('horizonForm').style.display = 'block';
      document.getElementById('horizonContent').value = '';
      document.getElementById('horizonTimeframe').value = '';
    }

    overlay.classList.add('open');
    setTimeout(() => {
      const firstInput = overlay.querySelector('textarea, input[type="text"]');
      if (firstInput) firstInput.focus();
    }, 350);
  }

  function closeModal() {
    document.getElementById('modalOverlay').classList.remove('open');
  }

  function selectType(type) {
    selectedType = type;
    document.querySelectorAll('.type-btn').forEach(b => {
      b.classList.toggle('selected', b.dataset.type === type);
    });
  }

  function populateProjectSelect() {
    const sel = document.getElementById('taskProject');
    sel.innerHTML = '<option value="">Без проекта</option>';
    projects.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.name;
      sel.appendChild(opt);
    });
  }

  // ===== Form Submissions =====
  async function submitTask() {
    const title = document.getElementById('taskTitle').value.trim();
    const date  = document.getElementById('taskDate').value;
    const time  = document.getElementById('taskTime').value;
    const proj  = document.getElementById('taskProject').value;

    if (!title) { showToast('Введите название задачи'); return; }
    if (!date)  { showToast('Выберите дату'); return; }

    const btn = document.getElementById('taskSubmitBtn');
    btn.disabled = true;
    btn.textContent = 'Сохраняю...';

    try {
      await API.createTask({
        title,
        type: selectedType,
        date,
        time_start: time || null,
        project_id: proj ? parseInt(proj) : null,
      });
      closeModal();
      showToast('Задача добавлена');
      if (currentScreen === 'morning') loadMorning();
    } catch (e) {
      showToast(`Ошибка: ${e.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Сохранить';
    }
  }

  async function submitIdea() {
    const content  = document.getElementById('ideaContent').value.trim();
    const remindAt = document.getElementById('ideaRemind').value;

    if (!content) { showToast('Введите идею'); return; }

    const btn = document.getElementById('ideaSubmitBtn');
    btn.disabled = true;
    btn.textContent = 'Сохраняю...';

    try {
      await API.createIdea({ content, remind_at: remindAt || null });
      closeModal();
      showToast('Идея сохранена');
      if (currentScreen === 'ideas') loadIdeas();
    } catch (e) {
      showToast(`Ошибка: ${e.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Сохранить';
    }
  }

  async function submitHorizon() {
    const content   = document.getElementById('horizonContent').value.trim();
    const timeframe = document.getElementById('horizonTimeframe').value.trim();

    if (!content) { showToast('Введите намерение'); return; }

    const btn = document.getElementById('horizonSubmitBtn');
    btn.disabled = true;
    btn.textContent = 'Сохраняю...';

    try {
      await API.createHorizon({ content, timeframe: timeframe || null });
      closeModal();
      showToast('Намерение добавлено');
      if (currentScreen === 'horizon') loadHorizon();
    } catch (e) {
      showToast(`Ошибка: ${e.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = 'Сохранить';
    }
  }

  // ===== Helpers =====
  function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove('show'), 3000);
  }

  function showLoading(screen, contentId) {
    const c = screen.querySelector(`#${contentId}`);
    if (c) c.innerHTML = '<div class="loading-spinner">Загрузка</div>';
  }

  function showError(screen, contentId, msg) {
    const c = screen.querySelector(`#${contentId}`);
    if (c) c.innerHTML = `<div class="empty-state" style="color:#EF4444">${msg}</div>`;
  }

  function todayISO() {
    return new Date().toLocaleDateString('en-CA');
  }

  function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
  }

  function typeLabel(type) {
    return { work: 'работа', personal: 'личное', rest: 'отдых', growth: 'рост' }[type] || type;
  }

  function escHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ===== Init =====
  function init() {
    // Nav buttons
    document.querySelectorAll('.nav-btn[data-screen]').forEach(btn => {
      btn.addEventListener('click', () => showScreen(btn.dataset.screen));
    });

    // Voice button
    document.getElementById('voiceNavBtn').addEventListener('click', () => Voice.open());

    // Add buttons
    document.getElementById('addTaskBtn').addEventListener('click', async () => {
      if (projects.length === 0) projects = await API.getProjects().catch(() => []);
      openModal('task');
    });
    document.getElementById('addIdeaBtn').addEventListener('click', () => openModal('idea'));
    document.getElementById('addHorizonBtn').addEventListener('click', () => openModal('horizon'));

    // Modal close
    document.getElementById('modalOverlay').addEventListener('click', e => {
      if (e.target.id === 'modalOverlay') closeModal();
    });
    document.getElementById('modalCloseBtn').addEventListener('click', closeModal);

    // Type selector
    document.querySelectorAll('.type-btn').forEach(btn => {
      btn.addEventListener('click', () => selectType(btn.dataset.type));
    });

    // Form submissions
    document.getElementById('taskSubmitBtn').addEventListener('click', submitTask);
    document.getElementById('ideaSubmitBtn').addEventListener('click', submitIdea);
    document.getElementById('horizonSubmitBtn').addEventListener('click', submitHorizon);

    // Enter key for single-line inputs
    ['taskTitle'].forEach(id => {
      document.getElementById(id)?.addEventListener('keydown', e => {
        if (e.key === 'Enter') submitTask();
      });
    });

    // Evening suggestion → go to evening screen
    document.getElementById('goToEveningBtn')?.addEventListener('click', () => showScreen('evening'));

    // Voice result → refresh current screen
    window.addEventListener('voice-added', (e) => {
      if (currentScreen === 'morning') loadMorning();
      if (currentScreen === 'ideas' && e.detail.type === 'idea') loadIdeas();
    });

    // Smart default: if >= 18:00 suggest evening
    const hour = new Date().getHours();
    const initialScreen = 'morning';
    showScreen(initialScreen);

    // Load projects in background for use in modal
    API.getProjects().then(p => { projects = p; }).catch(() => {});
  }

  // Public
  return { init, showToast, showScreen };
})();

// ===== Bootstrap =====
document.addEventListener('DOMContentLoaded', () => {
  App.init();

  // Register service worker
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
});
