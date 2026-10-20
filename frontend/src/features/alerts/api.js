export function createAlertApi(request) {
  return {
    markSeen: (id) => request(`/alerts/${id}/seen`, { method: 'POST' }),
    respond: (id, response) => request(`/alerts/${id}/response`, { method: 'POST', body: { response } }),
    generateGuide: (id) => request(`/alerts/${id}/guide`, { method: 'POST' }),
  };
}
