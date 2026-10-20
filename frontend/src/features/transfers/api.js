export function createTransferApi(request) {
  return {
    loadRecipients: () => request('/demo/recipients'),
    requestTransferHelp: (payload) => request('/transfer-help-requests', { method: 'POST', body: payload }),
    transfer: (payload) => request('/transfers', { method: 'POST', body: payload }),
  };
}
