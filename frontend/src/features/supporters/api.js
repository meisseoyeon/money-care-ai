export function createSupporterApi(request) {
  return {
    revokeShare: (id) => request(`/alert-shares/${id}/revoke`, { method: 'POST' }),
    setLink: (id, active) => request(`/supporter-links/${id}/${active ? 'accept' : 'revoke'}`, { method: 'POST' }),
  };
}
