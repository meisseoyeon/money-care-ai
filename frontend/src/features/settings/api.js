export function createSettingsApi(request) {
  return {
    setMonitoring: (enabled) => request('/demo/me/monitoring-consent', { method: 'PUT', body: { consented: enabled } }),
  };
}
