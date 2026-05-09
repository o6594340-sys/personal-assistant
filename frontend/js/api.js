// All API calls use relative URLs — works both on localhost:8000 and any deployment

const API = {
  async get(path) {
    const res = await fetch(path);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  async post(path, body) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    if (res.status === 204) return null;
    return res.json();
  },

  async put(path, body) {
    const res = await fetch(path, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  async delete(path) {
    const res = await fetch(path, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return true;
  },

  // --- Morning & Evening ---
  getMorning()  { return this.get('/api/morning'); },
  getEvening()  { return this.get('/api/evening'); },

  // --- Tasks ---
  getTasks(forDate) {
    const qs = forDate ? `?for_date=${forDate}` : '';
    return this.get(`/api/tasks${qs}`);
  },
  getCalendar(year, month) { return this.get(`/api/calendar?year=${year}&month=${month}`); },
  createTask(data)       { return this.post('/api/tasks', data); },
  updateTask(id, data)   { return this.put(`/api/tasks/${id}`, data); },
  toggleTask(id)         { return this.put(`/api/tasks/${id}/toggle`); },
  deleteTask(id)         { return this.delete(`/api/tasks/${id}`); },

  // --- Voice ---
  sendVoice(text)        { return this.post('/api/voice', { text }); },

  // --- Projects ---
  getProjects()          { return this.get('/api/projects'); },

  // --- Ideas ---
  getIdeas()             { return this.get('/api/ideas'); },
  createIdea(data)       { return this.post('/api/ideas', data); },
  archiveIdea(id)        { return this.put(`/api/ideas/${id}/archive`); },

  // --- Horizon ---
  getHorizon()           { return this.get('/api/horizon'); },
  createHorizon(data)    { return this.post('/api/horizon', data); },
  deleteHorizon(id)      { return this.delete(`/api/horizon/${id}`); },
};
