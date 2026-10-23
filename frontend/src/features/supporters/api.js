export function createSupporterApi(request) {
  return {
    loadLinks: () => request('/supporter-links'),
    loadShares: () => request('/alert-shares'),
    loadSharedAlerts: () => request('/shared-alerts'),
    revokeShare: (id) => request(`/alert-shares/${id}/revoke`, { method: 'POST' }),
    setLink: (id, active) => request(`/supporter-links/${id}/${active ? 'accept' : 'revoke'}`, { method: 'POST' }),
  };
}
